"""分层提示词层：以「角色 / Agent」为核心组织提示词。

设计动机：给模型一个明确的**角色**与边界，是约束输出最有效的手段——它一句话就能
框定语气、视角、可做与不可做。因此本包把每个 LLM 调用建模成「一个具名角色（Agent）
在执行一项任务」，而不是一堆零散的指令拼接。

层级模型（自顶向下）：
1. ``roles`` —— 角色名册（the cast）。每个 ``Role`` 是一份可复用的人设：
   ``identity``（身份与使命）+ ``directives``（该角色恒定遵循的行为准则，逐层保留
   原始排版）+ ``output_contract``（输出纪律：只输出什么、用什么包裹、禁止什么）。
   角色被渲染为 **system** 消息——这正是「赋予角色」之处。
2. 各阶段模块（``transcript`` / ``summary`` / ``translate``）—— 用 ``Prompt`` 把
   一个角色绑定到它的「任务层」（user 侧：任务说明 + 输入），并声明调参旋钮。
3. ``render`` —— 注入运行时变量，合并 system（角色）与 user（任务）为 OpenAI
   ``messages``，并在开启调试时 dump「哪个角色、哪些层参与了合并」。

最小单元仍是 ``Layer``（一段带 ``{占位符}`` 的文本 + 名字）；``Role`` 由若干 Layer
组成，``Prompt`` 由「一个 Role + 若干任务 Layer」组成。

调试钩子（默认关闭，零开销）：
- ``AIT_PROMPT_DEBUG=1`` —— 把渲染后的最终 system/user 与「角色 + 参与层」打到日志。
- ``AIT_PROMPT_DUMP_DIR=<dir>`` —— 把每次渲染落盘，便于离线对照。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Layer:
    """提示词的最小可复用单元：一段带 ``{var}`` 占位符的文本 + 调试用名字。

    文本本身不得含裸 ``{``/``}``（需要字面花括号请写 ``{{``/``}}``）。``name`` 不参与
    渲染，仅在调试 dump 时标注「这段来自哪一层」。
    """

    name: str
    text: str


@dataclass(frozen=True)
class Role:
    """一个具名、可复用的「角色 / Agent 人设」，渲染为 system 消息。

    三段式：
    - ``identity`` —— 身份与使命（「你是…」），最强的输出约束来源。
    - ``directives`` —— 该角色恒定遵循的行为准则，按 ``Layer`` 逐段保留原始排版
      （编号清单 / 要点 / 小标题各异，不强行归一）。
    - ``output_contract`` —— 输出纪律层（可选）：只输出正文、用何种标签包裹、禁止
      前言尾注等。单独成层便于在多个角色间复用同一套「输出契约」。
    """

    name: str
    identity: str
    directives: tuple[Layer, ...] = ()
    output_contract: Optional[Layer] = None

    def as_layers(self) -> tuple[Layer, ...]:
        """展开为 system 侧的有序层序列：identity → directives → output_contract。"""
        layers = [Layer(f"{self.name}/identity", self.identity), *self.directives]
        if self.output_contract is not None:
            layers.append(self.output_contract)
        return tuple(layers)


@dataclass(frozen=True)
class Prompt:
    """一次 LLM 调用的配方：一个角色（system） + 若干任务层（user） + 调参旋钮。"""

    name: str
    role: Role
    task_layers: tuple[Layer, ...] = field(default_factory=tuple)
    temperature: float = 0.2
    max_tokens: int = 2000

    def render(self, **variables) -> list[dict]:
        return render(self, **variables)


def compose(layers: tuple[Layer, ...], variables: dict) -> str:
    """把若干层合并成一段文本：逐层注入变量后用空行拼接，跳过空层。

    空层（变量注入后为空串，如未命中的可选上下文层）会被丢弃，避免在最终提示词里
    留下多余空行。
    """
    parts = []
    for layer in layers:
        rendered = layer.text.format(**variables).strip()
        if rendered:
            parts.append(rendered)
    return "\n\n".join(parts)


def render(prompt: Prompt, **variables) -> list[dict]:
    """合并角色（system）与任务层（user），返回 ``[{system}, {user}]``。"""
    system = compose(prompt.role.as_layers(), variables)
    user = compose(prompt.task_layers, variables)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    _maybe_dump(prompt, messages)
    return messages


def _maybe_dump(prompt: Prompt, messages: list[dict]) -> None:
    """开启调试时输出渲染后的提示词与「角色 + 参与层」；dump 失败不得影响主流程。"""
    if os.environ.get("AIT_PROMPT_DEBUG") in ("1", "true", "True"):
        role_layers = "+".join(l.name for l in prompt.role.as_layers())
        task_layers = "+".join(l.name for l in prompt.task_layers)
        logger.info(
            "[prompt:%s] role=%s system=[%s] user=[%s]",
            prompt.name, prompt.role.name, role_layers, task_layers,
        )
        for m in messages:
            logger.info("[prompt:%s][%s]\n%s", prompt.name, m["role"], m["content"])

    dump_dir = os.environ.get("AIT_PROMPT_DUMP_DIR")
    if dump_dir:
        try:
            from datetime import datetime

            os.makedirs(dump_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            path = os.path.join(dump_dir, f"{stamp}_{prompt.name}.txt")
            body = "\n\n".join(f"===== {m['role']} =====\n{m['content']}" for m in messages)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        except Exception as e:  # noqa: BLE001 — 调试设施不可拖垮主流程
            logger.debug("提示词 dump 失败（忽略）：%s", e)

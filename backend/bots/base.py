"""Bot 抽象层：所有平台机器人的公共接口与配置/状态模型。

各平台 Bot（telegram/slack/…）实现 BaseBot，由 manager.BotManager 统一启停。
LLM 配置（api_key/base_url/model/summary_language）随 BotConfig 一起下发——
Bot 收到链接时没有前端请求，只能依赖这份随配置保存的快照来跑摘要管线。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class BotStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class LLMConfig:
    """跑摘要管线所需的模型配置，由前端随 Bot 配置一并下发。"""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    summary_language: str = "zh"
    whisper_model: str = ""


@dataclass
class BotConfig:
    enabled: bool = False
    token: str = ""
    llm: LLMConfig = field(default_factory=LLMConfig)
    # extras 承载平台特有字段（如 Slack 的 app_token、飞书的 app_id/app_secret）。
    extras: dict = field(default_factory=dict)


class BaseBot(ABC):
    platform: str  # 'telegram' | 'slack' | 'feishu' | ...

    @abstractmethod
    async def start(self, config: BotConfig) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def get_status(self) -> dict:
        """返回 {"status": "running", "uptime_seconds": 3600,
        "messages_processed": 12, "last_error": None, "bot_name": "@xxx"}"""
        ...

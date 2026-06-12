"""集中配置层：把散落在各处的环境变量收敛为一个可注入、可测试的 Settings 对象。

设计目标：
- 单一事实来源——所有可调参数（上传上限、Whisper 模型、LLM 超时等）都在这里读取，
  其他模块从 ``settings`` 取值，而不是各自调用 ``os.getenv``。
- 零额外依赖——使用标准库 dataclass，不引入 pydantic-settings。
- 可覆盖——``Settings.from_env()`` 读取环境变量；测试可直接构造 ``Settings(...)``。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """运行时配置。冻结为不可变，避免被某处偷偷改写造成隐性耦合。"""

    # ── 本地上传 ──
    upload_max_mb: int = 200
    upload_allowed_ext: frozenset[str] = frozenset(
        {".txt", ".md", ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mkv", ".ogg", ".flac"}
    )

    # ── 转录（Whisper / ASR 后端）──
    whisper_model_size: str = "base"

    # ── LLM ──
    llm_timeout_sec: float = 300.0
    llm_request_timeout_sec: float = 120.0
    llm_max_retries: int = 1
    fast_model: str = "gpt-3.5-turbo"
    advanced_model: str = "gpt-4o"
    openai_api_key: str = ""
    openai_base_url: str = ""

    @property
    def upload_max_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量构建配置；未设置项回落到默认值。"""
        return cls(
            upload_max_mb=_get_int("UPLOAD_MAX_MB", 200),
            whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "base"),
            llm_timeout_sec=_get_float("LLM_TIMEOUT_SEC", 300.0),
            llm_request_timeout_sec=_get_float("LLM_REQUEST_TIMEOUT_SEC", 120.0),
            llm_max_retries=_get_int("LLM_MAX_RETRIES", 1),
            fast_model=os.getenv("FAST_MODEL", "gpt-3.5-turbo"),
            advanced_model=os.getenv("SMART_MODEL", "gpt-4o"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
        )


# 进程级单例：导入即读取一次环境变量。
settings = Settings.from_env()

"""领域异常：用类型化的异常替代到处 ``raise Exception(...)``。

路由层可据此把不同失败映射为合适的 HTTP 状态码（见 ``routers`` 中的处理），
而不是把所有错误都压成 500。每个异常都带一个 ``http_status`` 供路由统一映射。
"""
from __future__ import annotations


class TranscriberError(Exception):
    """转录/摘要管线相关错误的基类。"""

    http_status: int = 500


class SourceError(TranscriberError):
    """输入来源无法获取或无可处理内容（用户侧问题，4xx）。"""

    http_status = 400


class UnsupportedSourceError(SourceError):
    """不支持的来源类型 / 文件类型。"""

    http_status = 415


class TranscriptionError(TranscriberError):
    """音频转文字阶段失败（ASR 后端错误，服务端 5xx）。"""

    http_status = 502


class LLMError(TranscriberError):
    """LLM 调用失败或超时（上游模型错误，5xx）。"""

    http_status = 502

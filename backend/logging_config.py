"""后端统一日志配置。

目标：
- 所有后端入口（uvicorn 直启、start.py 桌面/服务模式）共用同一套日志输出。
- 终端 + 文件双写，文件落到可写目录，方便事后排查。
- 兼容 uvicorn 默认日志，避免它覆盖我们的文件处理器。
"""
from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FILE: Path | None = None
_CONFIGURED = False
# faulthandler 需要一个在进程存活期间始终打开的文件对象，故用模块级变量持有，防止被 GC。
_CRASH_LOG_FP = None


def _get_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "ai-transcriber"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ai-transcriber"
        else:
            base = Path.home() / ".local" / "share" / "ai-transcriber"
        log_dir = base / "logs"
    else:
        # 使用 task_store.TEMP_DIR 保证与 db.py / pipeline 同一数据目录
        from task_store import TEMP_DIR  # delayed import — avoid circular import
        log_dir = TEMP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file() -> Path:
    global _LOG_FILE
    if _LOG_FILE is None:
        _LOG_FILE = _get_log_dir() / "backend.log"
    return _LOG_FILE


def _enable_crash_dump(log_dir: Path) -> None:
    """开启 faulthandler，让原生致命错误也能在日志里留痕。

    像 MLX / CTranslate2 这类 C++ 扩展抛出的未捕获异常会触发 abort()（SIGABRT），
    直接绕过 Python：sys.excepthook / threading.excepthook 都抓不到，信息只打到终端
    stderr，日志文件里一片空白。faulthandler 在收到 SIGABRT/SIGSEGV/SIGBUS/SIGFPE/
    SIGILL 时会把所有线程的 Python 调用栈转储到指定文件，给原生崩溃留下排查线索。
    文件需在进程存活期间保持打开（见 _CRASH_LOG_FP）。
    """
    global _CRASH_LOG_FP
    if _CRASH_LOG_FP is not None:
        return
    try:
        # buffering=1（行缓冲）确保崩溃瞬间已写入的栈不会滞留在缓冲区里丢失。
        _CRASH_LOG_FP = open(log_dir / "crash.log", "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_CRASH_LOG_FP, all_threads=True)
    except Exception:  # 任何环境（受限 fd / 只读盘等）下都不应阻断启动
        pass


def configure_logging(level: int | None = None) -> Path:
    """配置 root logger，并让 uvicorn 日志复用同一套处理器。"""
    global _CONFIGURED

    if level is None:
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    log_file = get_log_file()
    if _CONFIGURED:
        return log_file

    # 原生崩溃转储：在配置其余日志前先挂上，尽早覆盖启动期的扩展加载。
    _enable_crash_dump(log_file.parent)

    formatter = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        mode="a",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # uvicorn 默认会挂自己的 handler；这里改成向 root 传播，保证也能写入文件。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(level)

    def _sys_excepthook(exc_type, exc, tb):
        logging.getLogger("uncaught").error("Uncaught exception", exc_info=(exc_type, exc, tb))

    def _thread_excepthook(args):
        logging.getLogger("uncaught").error(
            "Uncaught thread exception in %s",
            getattr(args.thread, "name", "thread"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook

    logging.captureWarnings(True)
    _CONFIGURED = True
    return log_file

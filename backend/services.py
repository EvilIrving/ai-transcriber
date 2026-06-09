"""依赖/服务层：共享处理器单例与上传配置。

路由与编排层都从这里取得处理器实例，避免在 main.py 里集中初始化、
被各处直接引用而造成耦合。
"""
import os

from video_processor import VideoProcessor
from transcriber import Transcriber
from summarizer import Summarizer
from translator import Translator
from rss_reader import RSSReader
from task_store import TEMP_DIR

# ── 处理器单例 ────────────────────────────────────────────────
video_processor = VideoProcessor()
transcriber = Transcriber()
summarizer = Summarizer()
translator = Translator()
rss_reader = RSSReader(data_dir=TEMP_DIR)

# ── 本地上传：允许的类型与大小上限（MB），可用环境变量 UPLOAD_MAX_MB 调整 ──
UPLOAD_ALLOWED_EXT = frozenset(
    {".txt", ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mkv", ".ogg", ".flac"}
)
UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "200"))

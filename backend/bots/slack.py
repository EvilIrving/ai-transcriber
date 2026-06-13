"""Slack Bot：Socket Mode（WebSocket）接收事件，零额外依赖（websockets + httpx）。

不走 slack-sdk：用 apps.connections.open 换取 WSS 地址，再用 websockets 直连，
手动按 envelope_id 回 ack。出站连接，无需公网 URL，契合纯本地服务约束。

需要两个 Token（在 Slack App 后台获取）：
  - bot token  (xoxb-)  → BotConfig.token，调 Web API（chat/files）
  - app token  (xapp-)  → extras["app_token"]，开 Socket Mode 连接
订阅 message.im（私聊）与 app_mention（@机器人）事件。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import httpx
import websockets

from .base import BaseBot, BotConfig, BotStatus
from .common import extract_url, run_transcription, split_long_message

logger = logging.getLogger(__name__)

# Slack 消息单条上限约 40000 字符，但展示效果以 ~3500 分片更好。
_SLACK_MSG_LIMIT = 3500


class SlackBot(BaseBot):
    platform = "slack"

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._status = BotStatus.STOPPED
        self._last_error: Optional[str] = None
        self._bot_name = ""
        self._messages_processed = 0
        self._started_at = 0.0
        self._bot_token = ""
        self._app_token = ""
        self._seen_envelopes: set[str] = set()

    # ── 生命周期 ──────────────────────────────────────────────
    async def start(self, config: BotConfig) -> None:
        await self.stop()
        self._bot_token = config.token.strip()
        self._app_token = str(config.extras.get("app_token", "")).strip()
        self._llm = config.llm
        self._status = BotStatus.STARTING
        self._last_error = None

        if not self._bot_token or not self._app_token:
            self._status = BotStatus.ERROR
            self._last_error = "需要 Bot Token (xoxb-) 与 App Token (xapp-)"
            raise ValueError(self._last_error)

        # 用 bot token 校验并取得名字（auth.test），失败则不启轮询。
        name = await self._auth_test()
        if not name:
            self._status = BotStatus.ERROR
            self._last_error = "Bot Token 无效"
            raise ValueError(self._last_error)

        self._bot_name = name
        self._client = httpx.AsyncClient(timeout=30)
        self._started_at = time.time()
        self._task = asyncio.create_task(self._socket_loop())
        self._status = BotStatus.RUNNING
        logger.info("Slack Bot 已启动: %s", name)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        self._status = BotStatus.STOPPED

    def get_status(self) -> dict:
        uptime = int(time.time() - self._started_at) if self._status == BotStatus.RUNNING else 0
        return {
            "status": self._status.value,
            "uptime_seconds": uptime,
            "messages_processed": self._messages_processed,
            "last_error": self._last_error,
            "bot_name": self._bot_name,
        }

    # ── Slack Web API ────────────────────────────────────────
    async def _auth_test(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {self._bot_token}"},
                )
            data = resp.json()
            if data.get("ok"):
                return data.get("user") or data.get("bot_id") or "bot"
            self._last_error = data.get("error", "auth.test 失败")
        except Exception as e:
            logger.warning("Slack auth.test 失败: %s", e)
        return None

    async def _open_connection(self) -> Optional[str]:
        """apps.connections.open：用 app token 换取一次性 WSS 地址。"""
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://slack.com/api/apps.connections.open",
                headers={"Authorization": f"Bearer {self._app_token}"},
            )
        data = resp.json()
        if not data.get("ok"):
            self._last_error = data.get("error", "apps.connections.open 失败")
            return None
        return data.get("url")

    async def _post_message(self, channel: str, text: str) -> None:
        assert self._client is not None
        for chunk in split_long_message(text, _SLACK_MSG_LIMIT):
            await self._client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self._bot_token}"},
                data={"channel": channel, "text": chunk},
            )

    async def _upload_file(self, channel: str, path, comment: str = "") -> bool:
        """用外部上传流程发文件（files.upload 已弃用）：取地址→上传→完成。"""
        assert self._client is not None
        try:
            size = path.stat().st_size
            r1 = await self._client.get(
                "https://slack.com/api/files.getUploadURLExternal",
                headers={"Authorization": f"Bearer {self._bot_token}"},
                params={"filename": path.name, "length": size},
            )
            d1 = r1.json()
            if not d1.get("ok"):
                return False
            upload_url, file_id = d1["upload_url"], d1["file_id"]

            with open(path, "rb") as f:
                await self._client.post(upload_url, files={"file": (path.name, f, "text/markdown")})

            r3 = await self._client.post(
                "https://slack.com/api/files.completeUploadExternal",
                headers={"Authorization": f"Bearer {self._bot_token}"},
                data={
                    "files": json.dumps([{"id": file_id, "title": path.name}]),
                    "channel_id": channel,
                    **({"initial_comment": comment} if comment else {}),
                },
            )
            return bool(r3.json().get("ok"))
        except Exception as e:
            logger.warning("Slack 文件上传失败: %s", e)
            return False

    # ── Socket Mode 主循环 ───────────────────────────────────
    async def _socket_loop(self) -> None:
        while True:
            try:
                url = await self._open_connection()
                if not url:
                    await asyncio.sleep(5)
                    continue
                async with websockets.connect(url, open_timeout=20) as ws:
                    async for raw in ws:
                        await self._on_socket_message(ws, raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._last_error = str(e)
                logger.warning("Slack Socket Mode 断开，5 秒后重连: %s", e)
                await asyncio.sleep(5)

    async def _on_socket_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        mtype = msg.get("type")
        if mtype in ("hello", "disconnect"):
            # disconnect 会让外层 async-for 结束并重连；hello 仅握手。
            return

        envelope_id = msg.get("envelope_id")
        if envelope_id:
            # 3 秒内 ack，否则 Slack 会重发。先 ack 再异步处理。
            await ws.send(json.dumps({"envelope_id": envelope_id}))
            if envelope_id in self._seen_envelopes:
                return  # 去重：Slack 可能重发同一 envelope
            self._seen_envelopes.add(envelope_id)

        if mtype == "events_api":
            event = (msg.get("payload") or {}).get("event") or {}
            asyncio.create_task(self._handle_event(event))

    async def _handle_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype not in ("message", "app_mention"):
            return
        # 忽略机器人自己/系统改动消息，避免回环。
        if event.get("bot_id") or event.get("subtype"):
            return
        channel = event.get("channel")
        text = event.get("text", "")
        if not channel:
            return

        url = extract_url(text)
        if not url:
            await self._post_message(
                channel,
                "请发送一个链接，支持 YouTube / Bilibili / TikTok / 播客等 30+ 平台。",
            )
            return

        self._messages_processed += 1
        await self._post_message(channel, f"⏳ 开始处理：{url}")
        try:
            result = await run_transcription(url, self._llm)
            if result.status == "completed":
                title = result.video_title or "处理完成"
                ok = False
                if result.result_path:
                    ok = await self._upload_file(channel, result.result_path, comment=f"✅ {title}")
                if not ok:
                    # 文件上传失败时退回纯文本摘要，保证用户拿到结果。
                    await self._post_message(channel, f"✅ {title}\n\n{result.summary or '（无内容）'}")
            else:
                await self._post_message(channel, f"❌ 处理失败：{result.error}")
        except Exception as e:
            logger.error("Slack 处理消息失败: %s", e, exc_info=True)
            await self._post_message(channel, f"❌ 处理失败：{e}")

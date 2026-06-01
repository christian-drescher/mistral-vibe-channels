from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from vibe.core.logger import logger

if TYPE_CHECKING:
    from telegram import Bot


def _check_telegram_available() -> bool:
    try:
        import telegram  # noqa: F401

        return True
    except ImportError:
        return False


class TelegramIngress:
    def __init__(
        self,
        queue: asyncio.Queue[str],
        *,
        bot_token: str,
        allowed_user_ids: set[int],
    ) -> None:
        self._queue = queue
        self._bot_token = bot_token
        self._allowed_user_ids = allowed_user_ids
        self._app: Any | None = None
        self._bot: Bot | None = None

    @property
    def bot(self) -> Bot | None:
        return self._bot

    @classmethod
    def from_config(
        cls, queue: asyncio.Queue[str], *, bot_token_env: str, allowed_user_ids: list[int]
    ) -> TelegramIngress | None:
        if not _check_telegram_available():
            logger.warning(
                "python-telegram-bot not installed. "
                "Install with: uv add mistral-vibe[telegram]"
            )
            return None

        token = os.environ.get(bot_token_env, "")
        if not token:
            logger.warning(
                "Telegram bot token not found in env var %s — Telegram ingress disabled.",
                bot_token_env,
            )
            return None

        if not allowed_user_ids:
            logger.warning("No allowed Telegram user IDs configured — Telegram ingress disabled.")
            return None

        return cls(queue, bot_token=token, allowed_user_ids=set(allowed_user_ids))

    async def start(self) -> None:
        from telegram import Update
        from telegram.ext import Application, MessageHandler, filters

        self._app = Application.builder().token(self._bot_token).build()
        self._bot = self._app.bot

        async def on_message(update: Update, _ctx: object) -> None:
            if update.effective_user is None or update.message is None:
                return
            if update.effective_user.id not in self._allowed_user_ids:
                return
            text = update.message.text or update.message.caption or ""
            if not text.strip():
                return
            chat_id = update.effective_chat.id if update.effective_chat else "?"
            prefix = f"[telegram:{chat_id}:{update.message.message_id}] "
            content = prefix + text
            if self._queue.full():
                logger.warning("Telegram ingress: queue full, dropping message")
                return
            await self._queue.put(content)

        self._app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, on_message))

        await self._app.initialize()
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling()
        logger.info("Telegram ingress started (polling)")

    async def stop(self) -> None:
        if self._app is None:
            return
        if self._app.updater:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        self._app = None
        self._bot = None
        logger.info("Telegram ingress stopped")

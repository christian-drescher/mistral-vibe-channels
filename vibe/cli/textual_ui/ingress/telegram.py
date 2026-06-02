from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vibe.core.logger import logger

if TYPE_CHECKING:
    from telegram import Bot, File as TelegramFile


def _check_telegram_available() -> bool:
    try:
        import telegram  # noqa: F401

        return True
    except ImportError:
        return False


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class TelegramIngress:
    _TYPING_INTERVAL: float = 4.0

    def __init__(
        self, queue: asyncio.Queue[str], *, bot_token: str, allowed_user_ids: set[int]
    ) -> None:
        self._queue = queue
        self._bot_token = bot_token
        self._allowed_user_ids = allowed_user_ids
        self._app: Any | None = None
        self._bot: Bot | None = None
        self._typing_task: asyncio.Task[None] | None = None

    @property
    def bot(self) -> Bot | None:
        return self._bot

    @classmethod
    def from_config(
        cls,
        queue: asyncio.Queue[str],
        *,
        bot_token_env: str,
        allowed_user_ids: list[int],
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
            logger.warning(
                "No allowed Telegram user IDs configured — Telegram ingress disabled."
            )
            return None

        return cls(queue, bot_token=token, allowed_user_ids=set(allowed_user_ids))

    async def _download_file(self, tg_file: TelegramFile, filename: str) -> Path:
        inbox = Path.cwd() / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        dest = _unique_path(inbox / filename)
        await tg_file.download_to_drive(custom_path=dest)
        return dest

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
            chat_id = update.effective_chat.id if update.effective_chat else "?"
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            prefix = f"[telegram:{chat_id}:{timestamp}] "

            attached: list[str] = []
            msg = update.message

            if msg.document:
                tg_file = await msg.document.get_file()
                filename = (
                    msg.document.file_name or f"document_{msg.document.file_unique_id}"
                )
                dest = await self._download_file(tg_file, filename)
                attached.append(f"inbox/{dest.name}")

            if msg.photo:
                largest = msg.photo[-1]
                tg_file = await largest.get_file()
                filename = f"photo_{largest.file_unique_id}.jpg"
                dest = await self._download_file(tg_file, filename)
                attached.append(f"inbox/{dest.name}")

            if not text.strip() and not attached:
                return

            content = prefix + text
            for path in attached:
                content += f"\n[attached: {path}]"

            if self._queue.full():
                logger.warning("Telegram ingress: queue full, dropping message")
                return
            await self._queue.put(content)

        self._app.add_handler(
            MessageHandler(
                filters.TEXT | filters.CAPTION | filters.Document.ALL | filters.PHOTO,
                on_message,
            )
        )

        await self._app.initialize()
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling()
        logger.info("Telegram ingress started (polling)")

    def start_typing(self, chat_id: int) -> None:
        self.stop_typing()
        if self._bot is None:
            return
        self._typing_task = asyncio.create_task(self._typing_loop(chat_id))

    def stop_typing(self) -> None:
        if self._typing_task is not None:
            self._typing_task.cancel()
            self._typing_task = None

    async def _typing_loop(self, chat_id: int) -> None:
        from telegram.constants import ChatAction as _ChatAction

        while True:
            try:
                if self._bot:
                    await self._bot.send_chat_action(chat_id, _ChatAction.TYPING)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Telegram typing indicator failed for chat_id=%s", chat_id)
            await asyncio.sleep(self._TYPING_INTERVAL)

    async def stop(self) -> None:
        self.stop_typing()
        if self._app is None:
            return
        if self._app.updater:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        self._app = None
        self._bot = None
        logger.info("Telegram ingress stopped")

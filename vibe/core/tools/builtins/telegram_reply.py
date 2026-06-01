from __future__ import annotations

from collections.abc import AsyncGenerator
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.types import ToolStreamEvent

if TYPE_CHECKING:
    from telegram import Bot


class TelegramReplyArgs(BaseModel):
    chat_id: int = Field(
        description="Telegram chat ID from the inbound message prefix."
    )
    text: str = Field(description="Reply text (Markdown supported).")
    files: list[str] | None = Field(
        default=None,
        description="Optional list of absolute file paths to attach as images/documents.",
    )


class TelegramReplyResult(BaseModel):
    status: str


class TelegramReplyConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


_bot_ref: Bot | None = None


def set_telegram_bot(bot: Bot | None) -> None:
    global _bot_ref
    _bot_ref = bot


class TelegramReplyTool(
    BaseTool[TelegramReplyArgs, TelegramReplyResult, TelegramReplyConfig, BaseToolState]
):
    description: ClassVar[str] = (
        "Reply to a Telegram chat. "
        "When a user message is prefixed with [telegram:<chat_id>:<message_id>], "
        "it originated from Telegram. Your normal text output does NOT reach that "
        "user — you MUST call this tool to respond. "
        "Extract the chat_id from the prefix: [telegram:1234567890:123] → "
        "chat_id=1234567890. "
        "The `text` parameter supports Telegram MarkdownV2 formatting. "
        "Optionally attach files via `files` (list of absolute paths); "
        "images are sent as photos, other files as documents."
    )

    @classmethod
    def get_name(cls) -> str:
        return "telegram_reply"

    async def run(
        self, args: TelegramReplyArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | TelegramReplyResult, None]:
        if _bot_ref is None:
            raise ToolError("Telegram bot not initialized.")

        await _bot_ref.send_message(chat_id=args.chat_id, text=args.text)

        for file_path_str in args.files or []:
            path = Path(file_path_str)
            if not path.is_absolute():
                raise ToolError(f"Path must be absolute: {file_path_str}")
            if not path.exists():
                raise ToolError(f"File not found: {file_path_str}")

            mime, _ = mimetypes.guess_type(str(path))
            is_image = mime is not None and mime.startswith("image/")

            with open(path, "rb") as f:
                if is_image:
                    await _bot_ref.send_photo(chat_id=args.chat_id, photo=f)
                else:
                    await _bot_ref.send_document(chat_id=args.chat_id, document=f)

        yield TelegramReplyResult(status="OK")

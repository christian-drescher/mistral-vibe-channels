from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from vibe.core.tools.base import InvokeContext, ToolError


class TestTelegramReplyTool:
    @pytest.mark.asyncio
    async def test_sends_text_message(self) -> None:
        from vibe.core.tools.builtins.telegram_reply import (
            TelegramReplyArgs,
            TelegramReplyTool,
            set_telegram_bot,
        )

        mock_bot = AsyncMock()
        set_telegram_bot(mock_bot)
        try:
            tool = TelegramReplyTool(
                config_getter=lambda: TelegramReplyTool._get_tool_config_class()(),
                state=TelegramReplyTool._get_tool_state_class()(),
            )
            args = TelegramReplyArgs(chat_id=123, text="hello")
            ctx = InvokeContext(tool_call_id="test")

            results = [r async for r in tool.run(args, ctx)]

            assert len(results) == 1
            assert results[0].status == "OK"
            mock_bot.send_message.assert_awaited_once_with(chat_id=123, text="hello")
        finally:
            set_telegram_bot(None)

    @pytest.mark.asyncio
    async def test_sends_image_file(self, tmp_path: Path) -> None:
        from vibe.core.tools.builtins.telegram_reply import (
            TelegramReplyArgs,
            TelegramReplyTool,
            set_telegram_bot,
        )

        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG fake")

        mock_bot = AsyncMock()
        set_telegram_bot(mock_bot)
        try:
            tool = TelegramReplyTool(
                config_getter=lambda: TelegramReplyTool._get_tool_config_class()(),
                state=TelegramReplyTool._get_tool_state_class()(),
            )
            args = TelegramReplyArgs(chat_id=123, text="see this", files=[str(img)])
            ctx = InvokeContext(tool_call_id="test")

            results = [r async for r in tool.run(args, ctx)]

            assert results[0].status == "OK"
            mock_bot.send_message.assert_awaited_once()
            mock_bot.send_photo.assert_awaited_once()
        finally:
            set_telegram_bot(None)

    @pytest.mark.asyncio
    async def test_sends_document_for_non_image(self, tmp_path: Path) -> None:
        from vibe.core.tools.builtins.telegram_reply import (
            TelegramReplyArgs,
            TelegramReplyTool,
            set_telegram_bot,
        )

        doc = tmp_path / "report.pdf"
        doc.write_bytes(b"%PDF fake")

        mock_bot = AsyncMock()
        set_telegram_bot(mock_bot)
        try:
            tool = TelegramReplyTool(
                config_getter=lambda: TelegramReplyTool._get_tool_config_class()(),
                state=TelegramReplyTool._get_tool_state_class()(),
            )
            args = TelegramReplyArgs(chat_id=123, text="report", files=[str(doc)])
            ctx = InvokeContext(tool_call_id="test")

            results = [r async for r in tool.run(args, ctx)]

            assert results[0].status == "OK"
            mock_bot.send_document.assert_awaited_once()
            mock_bot.send_photo.assert_not_awaited()
        finally:
            set_telegram_bot(None)

    @pytest.mark.asyncio
    async def test_raises_when_bot_not_initialized(self) -> None:
        from vibe.core.tools.builtins.telegram_reply import (
            TelegramReplyArgs,
            TelegramReplyTool,
            set_telegram_bot,
        )

        set_telegram_bot(None)
        tool = TelegramReplyTool(
            config_getter=lambda: TelegramReplyTool._get_tool_config_class()(),
            state=TelegramReplyTool._get_tool_state_class()(),
        )
        args = TelegramReplyArgs(chat_id=123, text="hello")
        ctx = InvokeContext(tool_call_id="test")

        with pytest.raises(ToolError, match="not initialized"):
            async for _ in tool.run(args, ctx):
                pass

    @pytest.mark.asyncio
    async def test_raises_for_relative_path(self) -> None:
        from vibe.core.tools.builtins.telegram_reply import (
            TelegramReplyArgs,
            TelegramReplyTool,
            set_telegram_bot,
        )

        mock_bot = AsyncMock()
        set_telegram_bot(mock_bot)
        try:
            tool = TelegramReplyTool(
                config_getter=lambda: TelegramReplyTool._get_tool_config_class()(),
                state=TelegramReplyTool._get_tool_state_class()(),
            )
            args = TelegramReplyArgs(chat_id=123, text="hi", files=["relative/path.txt"])
            ctx = InvokeContext(tool_call_id="test")

            with pytest.raises(ToolError, match="absolute"):
                async for _ in tool.run(args, ctx):
                    pass
        finally:
            set_telegram_bot(None)

    @pytest.mark.asyncio
    async def test_raises_for_nonexistent_file(self) -> None:
        from vibe.core.tools.builtins.telegram_reply import (
            TelegramReplyArgs,
            TelegramReplyTool,
            set_telegram_bot,
        )

        mock_bot = AsyncMock()
        set_telegram_bot(mock_bot)
        try:
            tool = TelegramReplyTool(
                config_getter=lambda: TelegramReplyTool._get_tool_config_class()(),
                state=TelegramReplyTool._get_tool_state_class()(),
            )
            args = TelegramReplyArgs(
                chat_id=123, text="hi", files=["/nonexistent/file.txt"]
            )
            ctx = InvokeContext(tool_call_id="test")

            with pytest.raises(ToolError, match="not found"):
                async for _ in tool.run(args, ctx):
                    pass
        finally:
            set_telegram_bot(None)

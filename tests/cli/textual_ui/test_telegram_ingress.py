from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTelegramIngressFromConfig:
    def test_returns_none_when_library_missing(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        with patch(
            "vibe.cli.textual_ui.ingress.telegram._check_telegram_available",
            return_value=False,
        ):
            result = TelegramIngress.from_config(
                queue, bot_token_env="TELEGRAM_BOT_TOKEN", allowed_user_ids=[123]
            )
        assert result is None

    def test_returns_none_when_token_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        queue: asyncio.Queue[str] = asyncio.Queue()
        with patch(
            "vibe.cli.textual_ui.ingress.telegram._check_telegram_available",
            return_value=True,
        ):
            result = TelegramIngress.from_config(
                queue, bot_token_env="TELEGRAM_BOT_TOKEN", allowed_user_ids=[123]
            )
        assert result is None

    def test_returns_none_when_no_allowed_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        queue: asyncio.Queue[str] = asyncio.Queue()
        with patch(
            "vibe.cli.textual_ui.ingress.telegram._check_telegram_available",
            return_value=True,
        ):
            result = TelegramIngress.from_config(
                queue, bot_token_env="TELEGRAM_BOT_TOKEN", allowed_user_ids=[]
            )
        assert result is None

    def test_returns_instance_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        queue: asyncio.Queue[str] = asyncio.Queue()
        with patch(
            "vibe.cli.textual_ui.ingress.telegram._check_telegram_available",
            return_value=True,
        ):
            result = TelegramIngress.from_config(
                queue, bot_token_env="TELEGRAM_BOT_TOKEN", allowed_user_ids=[123]
            )
        assert result is not None
        assert result._allowed_user_ids == {123}


class TestTelegramIngressMessageHandling:
    @pytest.mark.asyncio
    async def test_allowed_user_message_is_queued(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={42})

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.updater = None
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.add_handler = MagicMock()

        with patch("telegram.ext.Application") as mock_app_cls:
            builder = MagicMock()
            builder.token.return_value = builder
            builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = builder

            await transport.start()

        handler_call = mock_app.add_handler.call_args[0][0]
        callback = handler_call.callback

        update = MagicMock()
        update.effective_user.id = 42
        update.effective_chat.id = 100
        update.message.text = "hello"
        update.message.caption = None
        update.message.message_id = 7
        update.message.document = None
        update.message.photo = None

        await callback(update, None)

        assert not queue.empty()
        msg = queue.get_nowait()
        assert "[telegram:100:" in msg
        assert "hello" in msg

    @pytest.mark.asyncio
    async def test_disallowed_user_message_is_dropped(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={42})

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.updater = None
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.add_handler = MagicMock()

        with patch("telegram.ext.Application") as mock_app_cls:
            builder = MagicMock()
            builder.token.return_value = builder
            builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = builder

            await transport.start()

        handler_call = mock_app.add_handler.call_args[0][0]
        callback = handler_call.callback

        update = MagicMock()
        update.effective_user.id = 999
        update.message.text = "hacker"
        update.message.caption = None
        update.message.document = None
        update.message.photo = None

        await callback(update, None)

        assert queue.empty()


class TestTelegramIngressStop:
    @pytest.mark.asyncio
    async def test_stop_shuts_down_app(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={1})

        mock_app = MagicMock()
        mock_app.updater = MagicMock()
        mock_app.updater.stop = AsyncMock()
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()

        transport._app = mock_app

        await transport.stop()

        mock_app.updater.stop.assert_awaited_once()
        mock_app.stop.assert_awaited_once()
        mock_app.shutdown.assert_awaited_once()
        assert transport._app is None
        assert transport._bot is None


class TestTelegramIngressTypingIndicator:
    @pytest.mark.asyncio
    async def test_start_typing_sends_chat_action(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={1})

        mock_bot = AsyncMock()
        transport._bot = mock_bot

        transport.start_typing(123)
        await asyncio.sleep(0.05)

        mock_bot.send_chat_action.assert_awaited()
        call_args = mock_bot.send_chat_action.call_args
        assert call_args[0][0] == 123

        transport.stop_typing()

    @pytest.mark.asyncio
    async def test_stop_typing_cancels_task(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={1})

        mock_bot = AsyncMock()
        transport._bot = mock_bot

        transport.start_typing(456)
        assert transport._typing_task is not None
        task = transport._typing_task

        transport.stop_typing()
        assert transport._typing_task is None
        await asyncio.sleep(0)
        assert task.done()

    @pytest.mark.asyncio
    async def test_start_typing_noop_without_bot(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={1})

        transport.start_typing(789)
        assert transport._typing_task is None

    @pytest.mark.asyncio
    async def test_start_typing_replaces_previous(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={1})

        mock_bot = AsyncMock()
        transport._bot = mock_bot

        transport.start_typing(111)
        first_task = transport._typing_task

        transport.start_typing(222)
        assert first_task is not None
        await asyncio.sleep(0)
        assert first_task.done()
        assert transport._typing_task is not first_task

        transport.stop_typing()

    @pytest.mark.asyncio
    async def test_stop_cleans_up_typing_task(self) -> None:
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={1})

        mock_bot = AsyncMock()
        transport._bot = mock_bot

        mock_app = MagicMock()
        mock_app.updater = None
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()
        transport._app = mock_app

        transport.start_typing(999)
        assert transport._typing_task is not None

        await transport.stop()
        assert transport._typing_task is None


class TestTelegramIngressFileDownload:
    def _make_started_transport(self, queue: asyncio.Queue[str]) -> tuple[Any, Any]:
        """Return (transport, on_message callback) after mocking start()."""
        from vibe.cli.textual_ui.ingress.telegram import TelegramIngress

        transport = TelegramIngress(queue, bot_token="fake", allowed_user_ids={42})
        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.updater = None
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.add_handler = MagicMock()
        return transport, mock_app

    async def _start_and_get_callback(self, transport: Any, mock_app: Any) -> Any:
        with patch("telegram.ext.Application") as mock_app_cls:
            builder = MagicMock()
            builder.token.return_value = builder
            builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = builder
            await transport.start()
        handler_call = mock_app.add_handler.call_args[0][0]
        return handler_call.callback

    @pytest.mark.asyncio
    async def test_document_is_downloaded_to_inbox(self, tmp_path: object) -> None:
        from pathlib import Path

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport, mock_app = self._make_started_transport(queue)

        inbox_dir = Path.cwd() / "inbox"

        mock_file = AsyncMock()

        async def fake_download(custom_path: Path) -> None:
            custom_path.parent.mkdir(parents=True, exist_ok=True)
            custom_path.write_bytes(b"fake pdf")

        mock_file.download_to_drive = fake_download

        callback = await self._start_and_get_callback(transport, mock_app)

        update = MagicMock()
        update.effective_user.id = 42
        update.effective_chat.id = 100
        update.message.text = None
        update.message.caption = "here is a file"
        update.message.document.get_file = AsyncMock(return_value=mock_file)
        update.message.document.file_name = "report.pdf"
        update.message.document.file_unique_id = "abc123"
        update.message.photo = None

        await callback(update, None)

        assert not queue.empty()
        msg = queue.get_nowait()
        assert "[attached: inbox/report.pdf]" in msg
        assert "here is a file" in msg
        assert (inbox_dir / "report.pdf").exists()

        # cleanup
        (inbox_dir / "report.pdf").unlink(missing_ok=True)
        if inbox_dir.exists():
            inbox_dir.rmdir()

    @pytest.mark.asyncio
    async def test_photo_is_downloaded_to_inbox(self) -> None:
        from pathlib import Path

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport, mock_app = self._make_started_transport(queue)

        inbox_dir = Path.cwd() / "inbox"

        mock_file = AsyncMock()

        async def fake_download(custom_path: Path) -> None:
            custom_path.parent.mkdir(parents=True, exist_ok=True)
            custom_path.write_bytes(b"\x89PNG fake")

        mock_file.download_to_drive = fake_download

        callback = await self._start_and_get_callback(transport, mock_app)

        update = MagicMock()
        update.effective_user.id = 42
        update.effective_chat.id = 100
        update.message.text = "check this photo"
        update.message.caption = None
        update.message.document = None

        photo_size = MagicMock()
        photo_size.file_unique_id = "photo_xyz"
        photo_size.get_file = AsyncMock(return_value=mock_file)
        update.message.photo = [MagicMock(), photo_size]  # largest is last

        await callback(update, None)

        assert not queue.empty()
        msg = queue.get_nowait()
        assert "[attached: inbox/photo_photo_xyz.jpg]" in msg
        assert "check this photo" in msg
        assert (inbox_dir / "photo_photo_xyz.jpg").exists()

        # cleanup
        (inbox_dir / "photo_photo_xyz.jpg").unlink(missing_ok=True)
        if inbox_dir.exists():
            inbox_dir.rmdir()

    @pytest.mark.asyncio
    async def test_file_only_message_no_text_is_queued(self) -> None:
        from pathlib import Path

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport, mock_app = self._make_started_transport(queue)

        inbox_dir = Path.cwd() / "inbox"

        mock_file = AsyncMock()

        async def fake_download(custom_path: Path) -> None:
            custom_path.parent.mkdir(parents=True, exist_ok=True)
            custom_path.write_bytes(b"data")

        mock_file.download_to_drive = fake_download

        callback = await self._start_and_get_callback(transport, mock_app)

        update = MagicMock()
        update.effective_user.id = 42
        update.effective_chat.id = 100
        update.message.text = None
        update.message.caption = None
        update.message.document.get_file = AsyncMock(return_value=mock_file)
        update.message.document.file_name = "data.csv"
        update.message.document.file_unique_id = "csv1"
        update.message.photo = None

        await callback(update, None)

        assert not queue.empty()
        msg = queue.get_nowait()
        assert "[attached: inbox/data.csv]" in msg
        assert "[telegram:100:" in msg

        # cleanup
        (inbox_dir / "data.csv").unlink(missing_ok=True)
        if inbox_dir.exists():
            inbox_dir.rmdir()

    @pytest.mark.asyncio
    async def test_filename_collision_appends_suffix(self) -> None:
        from pathlib import Path

        queue: asyncio.Queue[str] = asyncio.Queue()
        transport, mock_app = self._make_started_transport(queue)

        inbox_dir = Path.cwd() / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        (inbox_dir / "dup.txt").write_text("existing")

        mock_file = AsyncMock()

        async def fake_download(custom_path: Path) -> None:
            custom_path.parent.mkdir(parents=True, exist_ok=True)
            custom_path.write_bytes(b"new")

        mock_file.download_to_drive = fake_download

        callback = await self._start_and_get_callback(transport, mock_app)

        update = MagicMock()
        update.effective_user.id = 42
        update.effective_chat.id = 100
        update.message.text = "dup file"
        update.message.caption = None
        update.message.document.get_file = AsyncMock(return_value=mock_file)
        update.message.document.file_name = "dup.txt"
        update.message.document.file_unique_id = "dup1"
        update.message.photo = None

        await callback(update, None)

        assert not queue.empty()
        msg = queue.get_nowait()
        assert "[attached: inbox/dup(1).txt]" in msg
        assert (inbox_dir / "dup(1).txt").exists()

        # cleanup
        (inbox_dir / "dup.txt").unlink(missing_ok=True)
        (inbox_dir / "dup(1).txt").unlink(missing_ok=True)
        if inbox_dir.exists():
            inbox_dir.rmdir()

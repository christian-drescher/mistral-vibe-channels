from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat

from vibe.core.logger import logger
from vibe.core.paths import VIBE_HOME

MAX_MESSAGE_BYTES = 64 * 1024
_RUN_DIR_NAME = "run"


def _default_socket_dir() -> Path:
    return VIBE_HOME.path / _RUN_DIR_NAME


class UnixSocketIngress:
    def __init__(
        self,
        queue: asyncio.Queue[str],
        *,
        session_id: str,
        socket_dir: Path | None = None,
    ) -> None:
        self._queue = queue
        self._session_id = session_id
        self._socket_dir = socket_dir or _default_socket_dir()
        self._socket_path: Path | None = None
        self._server: asyncio.AbstractServer | None = None

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    async def start(self) -> None:
        self._socket_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._socket_dir, stat.S_IRWXU)

        self._socket_path = self._socket_dir / f"{self._session_id}.sock"

        if self._socket_path.exists():
            self._socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        os.chmod(self._socket_path, stat.S_IRUSR | stat.S_IWUSR)
        logger.info("Ingress socket listening at %s", self._socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._socket_path is not None and self._socket_path.exists():
            self._socket_path.unlink(missing_ok=True)
            self._socket_path = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await reader.read(MAX_MESSAGE_BYTES)
            content = data.decode("utf-8", errors="replace").strip()
            if not content:
                writer.write(b"ERR:EMPTY\n")
            elif self._queue.full():
                writer.write(b"ERR:QUEUE_FULL\n")
            else:
                await self._queue.put(content)
                writer.write(b"ACK\n")
            await writer.drain()
        except Exception as exc:
            logger.warning("Ingress socket handler error: %s", exc)
        finally:
            writer.close()
            await writer.wait_closed()

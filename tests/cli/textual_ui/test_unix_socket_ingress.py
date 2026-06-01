from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat

import pytest

from vibe.cli.textual_ui.ingress.unix_socket import UnixSocketIngress


@pytest.fixture
def socket_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


@pytest.mark.asyncio
async def test_start_creates_socket_file(socket_dir: Path) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ingress = UnixSocketIngress(queue, session_id="test-sess", socket_dir=socket_dir)

    await ingress.start()
    try:
        assert ingress.socket_path is not None
        assert ingress.socket_path.exists()
        mode = os.stat(ingress.socket_path).st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)
    finally:
        await ingress.stop()


@pytest.mark.asyncio
async def test_stop_removes_socket_file(socket_dir: Path) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ingress = UnixSocketIngress(queue, session_id="test-sess", socket_dir=socket_dir)

    await ingress.start()
    sock_path = ingress.socket_path
    assert sock_path is not None
    await ingress.stop()
    assert not sock_path.exists()


@pytest.mark.asyncio
async def test_accepts_message_and_returns_ack(socket_dir: Path) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ingress = UnixSocketIngress(queue, session_id="test-sess", socket_dir=socket_dir)
    await ingress.start()

    try:
        reader, writer = await asyncio.open_unix_connection(str(ingress.socket_path))
        writer.write(b"hello world")
        writer.write_eof()
        response = await reader.read(1024)
        writer.close()
        await writer.wait_closed()

        assert response == b"ACK\n"
        assert queue.qsize() == 1
        assert queue.get_nowait() == "hello world"
    finally:
        await ingress.stop()


@pytest.mark.asyncio
async def test_empty_message_returns_error(socket_dir: Path) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ingress = UnixSocketIngress(queue, session_id="test-sess", socket_dir=socket_dir)
    await ingress.start()

    try:
        reader, writer = await asyncio.open_unix_connection(str(ingress.socket_path))
        writer.write(b"   \n")
        writer.write_eof()
        response = await reader.read(1024)
        writer.close()
        await writer.wait_closed()

        assert response == b"ERR:EMPTY\n"
        assert queue.empty()
    finally:
        await ingress.stop()


@pytest.mark.asyncio
async def test_queue_full_returns_error(socket_dir: Path) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
    ingress = UnixSocketIngress(queue, session_id="test-sess", socket_dir=socket_dir)
    await ingress.start()

    try:
        await queue.put("a")
        await queue.put("b")

        reader, writer = await asyncio.open_unix_connection(str(ingress.socket_path))
        writer.write(b"overflow")
        writer.write_eof()
        response = await reader.read(1024)
        writer.close()
        await writer.wait_closed()

        assert response == b"ERR:QUEUE_FULL\n"
    finally:
        await ingress.stop()


@pytest.mark.asyncio
async def test_multiple_messages_fifo(socket_dir: Path) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ingress = UnixSocketIngress(queue, session_id="test-sess", socket_dir=socket_dir)
    await ingress.start()

    try:
        for msg in ["first", "second", "third"]:
            reader, writer = await asyncio.open_unix_connection(
                str(ingress.socket_path)
            )
            writer.write(msg.encode())
            writer.write_eof()
            await reader.read(1024)
            writer.close()
            await writer.wait_closed()

        results = [queue.get_nowait() for _ in range(3)]
        assert results == ["first", "second", "third"]
    finally:
        await ingress.stop()


@pytest.mark.asyncio
async def test_replaces_stale_socket(socket_dir: Path) -> None:
    sock_path = socket_dir / "stale.sock"
    sock_path.touch()

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ingress = UnixSocketIngress(queue, session_id="stale", socket_dir=socket_dir)
    await ingress.start()

    try:
        assert ingress.socket_path is not None
        reader, writer = await asyncio.open_unix_connection(str(ingress.socket_path))
        writer.write(b"works")
        writer.write_eof()
        response = await reader.read(1024)
        writer.close()
        await writer.wait_closed()
        assert response == b"ACK\n"
    finally:
        await ingress.stop()

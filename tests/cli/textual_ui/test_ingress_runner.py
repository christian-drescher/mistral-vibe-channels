from __future__ import annotations

import asyncio

import pytest

from vibe.cli.textual_ui.ingress.runner import MAX_QUEUE_DEPTH, IngressRunner


@pytest.mark.asyncio
async def test_fires_message_when_idle() -> None:
    fired: list[str] = []

    async def fire(msg: str) -> None:
        fired.append(msg)

    runner = IngressRunner(can_fire=lambda: True, fire=fire)
    runner.start()
    await runner.queue.put("hello")
    await asyncio.sleep(0.05)
    await runner.stop()

    assert fired == ["hello"]


@pytest.mark.asyncio
async def test_waits_until_idle_to_fire() -> None:
    fired: list[str] = []
    idle = False

    async def fire(msg: str) -> None:
        fired.append(msg)

    runner = IngressRunner(can_fire=lambda: idle, fire=fire)
    runner.start()
    await runner.queue.put("deferred")

    await asyncio.sleep(0.25)
    assert fired == []

    idle = True
    await asyncio.sleep(0.25)
    await runner.stop()

    assert fired == ["deferred"]


@pytest.mark.asyncio
async def test_fifo_ordering() -> None:
    fired: list[str] = []

    async def fire(msg: str) -> None:
        fired.append(msg)

    runner = IngressRunner(can_fire=lambda: True, fire=fire)
    await runner.queue.put("first")
    await runner.queue.put("second")
    await runner.queue.put("third")
    runner.start()
    await asyncio.sleep(0.15)
    await runner.stop()

    assert fired == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    runner = IngressRunner(can_fire=lambda: True, fire=lambda _: asyncio.sleep(0))
    await runner.stop()
    await runner.stop()


@pytest.mark.asyncio
async def test_pending_reflects_queue_size() -> None:
    runner = IngressRunner(can_fire=lambda: False, fire=lambda _: asyncio.sleep(0))
    assert runner.pending == 0
    await runner.queue.put("a")
    await runner.queue.put("b")
    assert runner.pending == 2


@pytest.mark.asyncio
async def test_queue_respects_max_depth() -> None:
    runner = IngressRunner(can_fire=lambda: False, fire=lambda _: asyncio.sleep(0))
    for i in range(MAX_QUEUE_DEPTH):
        await runner.queue.put(f"msg-{i}")
    assert runner.queue.full()


@pytest.mark.asyncio
async def test_fire_exception_does_not_crash_runner() -> None:
    call_count = 0

    async def bad_fire(msg: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")

    runner = IngressRunner(can_fire=lambda: True, fire=bad_fire)
    await runner.queue.put("fail")
    await runner.queue.put("succeed")
    runner.start()
    await asyncio.sleep(0.15)
    await runner.stop()

    assert call_count == 2

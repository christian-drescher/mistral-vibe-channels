from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from vibe.core.logger import logger

MAX_QUEUE_DEPTH = 100


class IngressRunner:
    def __init__(
        self, *, can_fire: Callable[[], bool], fire: Callable[[str], Awaitable[None]]
    ) -> None:
        self._can_fire = can_fire
        self._fire = fire
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_DEPTH)
        self._task: asyncio.Task[None] | None = None

    @property
    def queue(self) -> asyncio.Queue[str]:
        return self._queue

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _poll(self) -> None:
        while True:
            try:
                msg = await self._queue.get()
            except asyncio.CancelledError:
                return
            while not self._can_fire():
                await asyncio.sleep(0.1)
            try:
                await self._fire(msg)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Ingress runner failed to fire message: %s", exc)

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
import re

from vibe.cli.textual_ui.ingress._cron import cron_matches
from vibe.core.logger import logger

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.DOTALL)
_SCHEDULE_RE = re.compile(r"^\s*schedule\s*:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)

_POLL_INTERVAL: float = 60.0


def _parse_frontmatter(raw: str, filename: str) -> tuple[str, str] | None:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        logger.warning("Scheduler: %s is missing YAML frontmatter — skipping", filename)
        return None
    yaml_block, body = match.group(1), match.group(2).strip()
    schedule_match = _SCHEDULE_RE.search(yaml_block)
    if not schedule_match:
        logger.warning(
            "Scheduler: %s frontmatter missing 'schedule' field — skipping", filename
        )
        return None
    return schedule_match.group(1), body


class SchedulerIngress:
    def __init__(self, queue: asyncio.Queue[str], *, jobs_dir: Path) -> None:
        self._queue = queue
        self._jobs_dir = jobs_dir
        self._task: asyncio.Task[None] | None = None
        self._last_sent_minute: dict[str, int] = {}

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("Scheduler ingress started (jobs_dir=%s)", self._jobs_dir)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Scheduler ingress stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Scheduler ingress error: %s", exc)
            await asyncio.sleep(_POLL_INTERVAL)

    async def _tick(self) -> None:
        if not self._jobs_dir.is_dir():
            return
        now = datetime.datetime.now()
        minute_stamp = int(now.timestamp()) // 60

        for path in sorted(self._jobs_dir.glob("*.md")):
            name = path.stem
            if self._last_sent_minute.get(name) == minute_stamp:
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Scheduler: failed to read %s: %s", path.name, exc)
                continue

            parsed = _parse_frontmatter(raw, path.name)
            if parsed is None:
                continue
            schedule, body = parsed

            try:
                if not cron_matches(schedule, now):
                    continue
            except ValueError as exc:
                logger.warning("Scheduler: %s has invalid cron: %s", path.name, exc)
                continue

            self._last_sent_minute[name] = minute_stamp
            timestamp = now.strftime("%Y-%m-%d %H:%M")
            message = f"[scheduler:{name}:{timestamp}]\n{body}"

            if self._queue.full():
                logger.warning("Scheduler ingress: queue full, dropping job %s", name)
                continue
            await self._queue.put(message)
            logger.debug("Scheduler: fired job %s", name)

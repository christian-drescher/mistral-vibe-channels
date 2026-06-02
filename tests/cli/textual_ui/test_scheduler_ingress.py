from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from vibe.cli.textual_ui.ingress._cron import cron_matches
from vibe.cli.textual_ui.ingress.scheduler import SchedulerIngress, _parse_frontmatter


class TestCronMatches:
    def test_wildcard_matches_any(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 30)
        assert cron_matches("* * * * *", dt)

    def test_exact_minute(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 30)
        assert cron_matches("30 * * * *", dt)
        assert not cron_matches("31 * * * *", dt)

    def test_exact_hour(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 0)
        assert cron_matches("0 14 * * *", dt)
        assert not cron_matches("0 15 * * *", dt)

    def test_step(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 15)
        assert cron_matches("*/15 * * * *", dt)
        assert not cron_matches("*/7 * * * *", dt)

    def test_range(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 30)
        assert cron_matches("25-35 * * * *", dt)
        assert not cron_matches("31-45 * * * *", dt)

    def test_comma_list(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 30)
        assert cron_matches("0,15,30,45 * * * *", dt)
        assert not cron_matches("0,15,45 * * * *", dt)

    def test_day_of_week_sunday_is_zero(self) -> None:
        # 2026-06-07 is a Sunday
        dt = datetime.datetime(2026, 6, 7, 0, 0)
        assert cron_matches("0 0 * * 0", dt)
        assert not cron_matches("0 0 * * 1", dt)

    def test_day_of_week_monday_is_one(self) -> None:
        # 2026-06-01 is a Monday
        dt = datetime.datetime(2026, 6, 1, 0, 0)
        assert cron_matches("0 0 * * 1", dt)

    def test_invalid_expression_raises(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 14, 30)
        with pytest.raises(ValueError, match="expected 5 fields"):
            cron_matches("* * *", dt)

    def test_month_field(self) -> None:
        dt = datetime.datetime(2026, 6, 2, 0, 0)
        assert cron_matches("0 0 * 6 *", dt)
        assert not cron_matches("0 0 * 7 *", dt)

    def test_day_of_month(self) -> None:
        dt = datetime.datetime(2026, 6, 15, 0, 0)
        assert cron_matches("0 0 15 * *", dt)
        assert not cron_matches("0 0 16 * *", dt)


class TestParseFrontmatter:
    def test_valid_frontmatter(self) -> None:
        raw = "---\nschedule: */5 * * * *\n---\nHello world"
        result = _parse_frontmatter(raw, "test.md")
        assert result == ("*/5 * * * *", "Hello world")

    def test_quoted_schedule(self) -> None:
        raw = '---\nschedule: "0 9 * * 1"\n---\nWeekly report'
        result = _parse_frontmatter(raw, "test.md")
        assert result is not None
        assert result[0] == "0 9 * * 1"
        assert result[1] == "Weekly report"

    def test_missing_frontmatter_returns_none(self) -> None:
        raw = "No frontmatter here\nJust text"
        result = _parse_frontmatter(raw, "test.md")
        assert result is None

    def test_missing_schedule_returns_none(self) -> None:
        raw = "---\ntitle: something\n---\nBody"
        result = _parse_frontmatter(raw, "test.md")
        assert result is None

    def test_multiline_body(self) -> None:
        raw = "---\nschedule: * * * * *\n---\nLine 1\nLine 2\nLine 3"
        result = _parse_frontmatter(raw, "test.md")
        assert result is not None
        assert result[1] == "Line 1\nLine 2\nLine 3"


class TestSchedulerIngress:
    @pytest.mark.asyncio
    async def test_fires_matching_job(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "reminder.md").write_text(
            "---\nschedule: * * * * *\n---\nDo the thing"
        )

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress._tick()

        assert not queue.empty()
        msg = queue.get_nowait()
        assert msg.startswith("[scheduler:reminder:")
        assert "Do the thing" in msg

    @pytest.mark.asyncio
    async def test_skips_non_matching_job(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "never.md").write_text(
            "---\nschedule: 0 0 31 2 *\n---\nImpossible"
        )

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress._tick()

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_deduplicates_within_same_minute(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "dedup.md").write_text(
            "---\nschedule: * * * * *\n---\nOnce per minute"
        )

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress._tick()
        await ingress._tick()

        assert queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_fires_again_next_minute(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "repeat.md").write_text(
            "---\nschedule: * * * * *\n---\nRepeat"
        )

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        now = datetime.datetime(2026, 6, 2, 10, 0, 0)
        with patch(
            "vibe.cli.textual_ui.ingress.scheduler.datetime"
        ) as mock_dt:
            mock_dt.datetime.now.return_value = now
            await ingress._tick()

        next_min = datetime.datetime(2026, 6, 2, 10, 1, 0)
        with patch(
            "vibe.cli.textual_ui.ingress.scheduler.datetime"
        ) as mock_dt:
            mock_dt.datetime.now.return_value = next_min
            await ingress._tick()

        assert queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_skips_malformed_frontmatter(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "bad.md").write_text("No frontmatter at all")

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress._tick()

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_skips_invalid_cron(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "invalid.md").write_text(
            "---\nschedule: not a cron\n---\nBody"
        )

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress._tick()

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_nonexistent_dir_is_noop(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "nonexistent"

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress._tick()

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress.start()
        assert ingress._task is not None
        assert not ingress._task.done()

        await ingress.stop()
        assert ingress._task is None

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        await ingress.stop()
        await ingress.stop()

    @pytest.mark.asyncio
    async def test_queue_full_drops_message(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "overflow.md").write_text(
            "---\nschedule: * * * * *\n---\nOverflow"
        )

        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        await queue.put("blocker")

        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)
        await ingress._tick()

        assert queue.qsize() == 1
        assert queue.get_nowait() == "blocker"

    @pytest.mark.asyncio
    async def test_message_format(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "daily-standup.md").write_text(
            "---\nschedule: * * * * *\n---\nWrite standup notes"
        )

        queue: asyncio.Queue[str] = asyncio.Queue()
        ingress = SchedulerIngress(queue, jobs_dir=jobs_dir)

        now = datetime.datetime(2026, 6, 2, 9, 0, 0)
        with patch(
            "vibe.cli.textual_ui.ingress.scheduler.datetime"
        ) as mock_dt:
            mock_dt.datetime.now.return_value = now
            await ingress._tick()

        msg = queue.get_nowait()
        assert msg == "[scheduler:daily-standup:2026-06-02 09:00]\nWrite standup notes"

from __future__ import annotations

import datetime

_CRON_FIELD_COUNT = 5


def _field_matches(field: str, value: int) -> bool:
    if "," in field:
        return any(_field_matches(part, value) for part in field.split(","))
    if field.startswith("*/"):
        step = int(field[2:])
        return value % step == 0
    if field == "*":
        return True
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return int(field) == value


def cron_matches(expr: str, dt: datetime.datetime) -> bool:
    parts = expr.strip().split()
    if len(parts) != _CRON_FIELD_COUNT:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {expr!r}")
    minute, hour, dom, month, dow = parts
    return (
        _field_matches(minute, dt.minute)
        and _field_matches(hour, dt.hour)
        and _field_matches(dom, dt.day)
        and _field_matches(month, dt.month)
        and _field_matches(dow, (dt.weekday() + 1) % 7)
    )

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

AGENT_TZ: ZoneInfo = ZoneInfo(os.environ.get("AGENT_TIMEZONE", "America/Argentina/Buenos_Aires"))


def today_arg() -> str:
    """Today's date in the agent timezone (YYYY-MM-DD)."""
    return datetime.now(AGENT_TZ).strftime("%Y-%m-%d")


def day_utc_bounds(date_str: str) -> tuple[str, str]:
    """Return (start_utc, end_utc) ISO strings for a YYYY-MM-DD date in AGENT_TZ.

    Use these as bounds in SQL: WHERE col >= ? AND col < ?
    This avoids relying on SQLite timezone arithmetic.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    start = datetime(d.year, d.month, d.day, tzinfo=AGENT_TZ).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()

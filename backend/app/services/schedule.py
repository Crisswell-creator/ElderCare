"""Pure, time-zone-aware schedule arithmetic (no database access), so it is easy to test.

Schedules are expressed in the elder's local wall-clock time. Each local time maps to one
UTC instant per day: a local time that does not exist on a DST spring-forward day resolves
to the equivalent instant after the gap, and an ambiguous fall-back time resolves to its
first occurrence. Either way exactly one dose is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

ALL_DAYS = 0b1111111


@dataclass(frozen=True)
class Slot:
    local_time: time
    days_mask: int = ALL_DAYS


@dataclass(frozen=True)
class Occurrence:
    scheduled_at: datetime  # UTC
    local_date: date
    local_time: time


def runs_on(day: date, days_mask: int) -> bool:
    return bool(days_mask & (1 << day.weekday()))


def occurrences(
    slots: list[Slot],
    tz_name: str,
    start_date: date,
    end_date: date | None,
    window_start: datetime,
    window_end: datetime,
) -> list[Occurrence]:
    """All dose instants in [window_start, window_end) for the given schedule."""
    tz = ZoneInfo(tz_name)
    first = max(window_start.astimezone(tz).date() - timedelta(days=1), start_date)
    last = window_end.astimezone(tz).date() + timedelta(days=1)
    if end_date is not None:
        last = min(last, end_date)
    out: list[Occurrence] = []
    day = first
    while day <= last:
        for slot in slots:
            if not runs_on(day, slot.days_mask):
                continue
            at = datetime.combine(day, slot.local_time, tzinfo=tz).astimezone(UTC)
            if window_start <= at < window_end:
                out.append(Occurrence(at, day, slot.local_time))
        day += timedelta(days=1)
    out.sort(key=lambda o: o.scheduled_at)
    return out


def daily_use(slots: list[Slot], dose_amount: Decimal) -> Decimal:
    """Average units consumed per day by the schedule (a weekly pattern averaged over 7)."""
    doses_per_week = sum((s.days_mask & ALL_DAYS).bit_count() for s in slots)
    return (dose_amount * doses_per_week / Decimal(7)).quantize(Decimal("0.0001"))


def stock_estimate(
    quantity: Decimal | None, per_day: Decimal, today: date
) -> tuple[Decimal | None, date | None]:
    """(days remaining, estimated run-out date). An estimate: it assumes doses are taken as
    scheduled from now on, which is why the UI always labels it as such."""
    if quantity is None or per_day <= 0:
        return None, None
    days = (quantity / per_day).quantize(Decimal("0.1"))
    return days, today + timedelta(days=int(days))

"""Adherence analytics computed from recorded dose events only.

Calculation rules (also shown in the app):
  * Counted doses: scheduled doses in the period, excluding cancelled ones and as-needed
    records (which have no schedule to adhere to).
  * Adherence % = taken / (taken + skipped + missed). Skipped counts as not taken.
  * Unconfirmed doses are reported separately and are NOT counted as missed: nobody knows
    whether they were taken. Upcoming doses are reported as pending.
  * An insight is shown only when each compared group has at least MIN_SAMPLE resolved
    doses and the difference is at least MIN_GAP percentage points.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DoseStatus
from app.models import DoseEvent, Medication

MIN_SAMPLE = 10
MIN_GAP = 15.0

BUCKETS = [
    ("morning", "Morning (5am-12pm)"),
    ("afternoon", "Afternoon (12-5pm)"),
    ("evening", "Evening (5-9pm)"),
    ("night", "Night (9pm-5am)"),
]


def bucket_of(t: time) -> str:
    h = t.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "evening"
    return "night"


@dataclass
class Counts:
    taken: int = 0
    skipped: int = 0
    missed: int = 0
    unconfirmed: int = 0
    pending: int = 0

    def add(self, status: str) -> None:
        if status == DoseStatus.SCHEDULED:
            self.pending += 1
        elif status in (
            DoseStatus.TAKEN,
            DoseStatus.SKIPPED,
            DoseStatus.MISSED,
            DoseStatus.UNCONFIRMED,
        ):
            setattr(self, status, getattr(self, status) + 1)

    @property
    def resolved(self) -> int:
        return self.taken + self.skipped + self.missed

    @property
    def scheduled(self) -> int:
        return self.resolved + self.unconfirmed + self.pending

    @property
    def adherence(self) -> float | None:
        return round(100 * self.taken / self.resolved, 1) if self.resolved else None

    @property
    def not_taken_rate(self) -> float | None:
        return (
            round(100 * (self.skipped + self.missed) / self.resolved, 1) if self.resolved else None
        )

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "scheduled": self.scheduled,
            "taken": self.taken,
            "skipped": self.skipped,
            "missed": self.missed,
            "unconfirmed": self.unconfirmed,
            "pending": self.pending,
            "resolved": self.resolved,
            "adherence_pct": self.adherence,
        }


@dataclass
class Report:
    start: date
    end: date
    granularity: str
    totals: Counts = field(default_factory=Counts)
    series: dict[date, Counts] = field(default_factory=lambda: defaultdict(Counts))
    by_medication: dict[int, Counts] = field(default_factory=lambda: defaultdict(Counts))
    by_time_of_day: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    medication_names: dict[int, str] = field(default_factory=dict)


def period_key(d: date, granularity: str) -> date:
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    return d


def build(
    db: Session,
    patient_id: int,
    start: date,
    end: date,
    granularity: str,
    medication_id: int | None = None,
) -> Report:
    stmt = (
        select(
            DoseEvent.medication_id,
            DoseEvent.local_date,
            DoseEvent.local_time,
            DoseEvent.status,
            Medication.name,
        )
        .join(Medication, Medication.id == DoseEvent.medication_id)
        .where(
            DoseEvent.patient_id == patient_id,
            DoseEvent.local_date >= start,
            DoseEvent.local_date <= end,
            DoseEvent.as_needed.is_(False),
            DoseEvent.status != DoseStatus.CANCELLED,
        )
    )
    if medication_id is not None:
        stmt = stmt.where(DoseEvent.medication_id == medication_id)
    report = Report(start=start, end=end, granularity=granularity)
    for med_id, local_date, local_time, status, name in db.execute(stmt):
        report.totals.add(status)
        report.series[period_key(local_date, granularity)].add(status)
        report.by_medication[med_id].add(status)
        report.by_time_of_day[bucket_of(local_time)].add(status)
        report.medication_names[med_id] = name
    return report


def insights(report: Report) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    period = f"{report.start:%d %b} - {report.end:%d %b %Y}"

    buckets = {k: c for k, c in report.by_time_of_day.items() if c.resolved >= MIN_SAMPLE}
    if len(buckets) >= 2:
        worst = max(buckets, key=lambda k: buckets[k].not_taken_rate or 0)
        best = min(buckets, key=lambda k: buckets[k].not_taken_rate or 0)
        w, b = buckets[worst].not_taken_rate or 0, buckets[best].not_taken_rate or 0
        if w - b >= MIN_GAP:
            label = dict(BUCKETS)
            out.append(
                {
                    "kind": "time_of_day",
                    "text": f"{label[worst].split(' (')[0]} doses have a higher recorded "
                    f"missed or skipped rate ({w:.0f}%) than "
                    f"{label[best].split(' (')[0].lower()} doses ({b:.0f}%).",
                    "basis": f"Based on {buckets[worst].resolved} {worst} and "
                    f"{buckets[best].resolved} {best} doses recorded, {period}.",
                }
            )

    meds = {k: c for k, c in report.by_medication.items() if c.resolved >= MIN_SAMPLE}
    if len(meds) >= 2:
        low = min(meds, key=lambda k: meds[k].adherence or 0)
        high = max(meds, key=lambda k: meds[k].adherence or 0)
        lo, hi = meds[low].adherence or 0, meds[high].adherence or 0
        if hi - lo >= MIN_GAP:
            out.append(
                {
                    "kind": "medication",
                    "text": f"{report.medication_names[low]} has a lower recorded confirmation "
                    f"rate ({lo:.0f}%) than {report.medication_names[high]} ({hi:.0f}%).",
                    "basis": f"Based on {meds[low].resolved} and {meds[high].resolved} doses "
                    f"recorded, {period}.",
                }
            )

    t = report.totals
    known = t.resolved + t.unconfirmed
    if t.unconfirmed >= 5 and known and t.unconfirmed / known >= 0.2:
        out.append(
            {
                "kind": "unconfirmed",
                "text": f"{t.unconfirmed} of {known} past doses were never confirmed. Recording "
                "doses as they happen gives a more accurate picture.",
                "basis": f"Unconfirmed doses are not counted as missed. {period}.",
            }
        )
    return out

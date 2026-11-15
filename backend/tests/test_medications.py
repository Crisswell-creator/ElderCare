"""Medication CRUD, schedule changes, inventory ledger and dose confirmation."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select

from app.models import DoseEvent
from app.services.schedule import Slot, daily_use, occurrences, stock_estimate
from tests.conftest import add_med

T0 = datetime(2026, 3, 10, 7, 30, tzinfo=UTC)  # London is on GMT (UTC+0) on this date


def test_create_validates_and_generates_doses(clock, circle):
    clock.set(T0)
    pid = circle.pid
    bad = circle.elder.post(
        f"/api/patients/{pid}/medications",
        {"name": "X", "dose_amount": 0, "start_date": "2026-03-10", "times": []},
    )
    assert bad.status_code == 422
    dup = circle.elder.post(
        f"/api/patients/{pid}/medications",
        {
            "name": "X",
            "dose_amount": 1,
            "start_date": "2026-03-10",
            "times": [{"local_time": "08:00"}, {"local_time": "08:00"}],
        },
    )
    assert dup.status_code == 422
    med = add_med(circle.elder, pid, ["08:00", "20:00"], initial_quantity=30)
    assert med["times"] == [
        {"local_time": "08:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        {"local_time": "20:00", "days": [0, 1, 2, 3, 4, 5, 6]},
    ]
    assert med["daily_use"] == 2 and med["quantity_on_hand"] == 30
    assert med["days_remaining"] == 15 and med["estimated_run_out"] == "2026-03-25"
    today = circle.elder.get(f"/api/patients/{pid}/doses").json()
    assert [d["local_time"] for d in today] == ["08:00", "20:00"]
    assert all(d["status"] == "scheduled" for d in today)


def test_doses_before_creation_are_never_generated(clock, circle):
    clock.set(datetime(2026, 3, 10, 12, 0, tzinfo=UTC))
    add_med(circle.elder, circle.pid, ["08:00", "20:00"])
    times = [d["local_time"] for d in circle.elder.get(f"/api/patients/{circle.pid}/doses").json()]
    assert times == ["20:00"]  # the 08:00 dose predates the medicine being added


def test_family_without_manage_permission_cannot_edit(circle):
    pid = circle.pid
    med = add_med(circle.elder, pid, ["08:00"])
    assert circle.family.get(f"/api/patients/{pid}/medications").status_code == 200
    body = {
        "name": "Changed",
        "dose_amount": 1,
        "start_date": "2026-01-01",
        "times": [{"local_time": "09:00"}],
    }
    assert (
        circle.family.put(f"/api/patients/{pid}/medications/{med['id']}", body).status_code == 403
    )
    assert circle.family.post(f"/api/patients/{pid}/medications", body).status_code == 403
    assert circle.carer.delete(f"/api/patients/{pid}/medications/{med['id']}").status_code == 403


def test_schedule_change_cancels_future_doses_and_regenerates(clock, circle, db):
    clock.set(T0)
    pid = circle.pid
    med = add_med(circle.elder, pid, ["08:00", "20:00"])
    res = circle.elder.put(
        f"/api/patients/{pid}/medications/{med['id']}",
        {
            "name": "Metformin",
            "strength": "500 mg",
            "dose_amount": 1,
            "start_date": "2020-01-01",
            "times": [{"local_time": "09:00"}, {"local_time": "20:00"}],
        },
    )
    assert res.status_code == 200
    rows = db.scalars(
        select(DoseEvent).where(
            DoseEvent.medication_id == med["id"], DoseEvent.local_date == date(2026, 3, 10)
        )
    ).all()
    by_time = {r.local_time.strftime("%H:%M"): r for r in rows}
    assert by_time["08:00"].status == "cancelled"
    assert by_time["08:00"].cancelled_reason == "schedule_changed"
    assert by_time["09:00"].status == "scheduled"
    assert by_time["20:00"].status == "scheduled"  # revived, not duplicated
    log = circle.elder.get(f"/api/patients/{pid}/activity").json()["items"]
    assert log[0]["action"] == "medication.schedule_changed"


def test_pause_resume_discontinue_and_remove_keep_history(clock, circle):
    clock.set(T0)
    pid = circle.pid
    med = add_med(circle.elder, pid, ["08:00"])
    circle.elder.post(
        f"/api/patients/{pid}/doses/"
        f"{circle.elder.get(f'/api/patients/{pid}/doses').json()[0]['id']}/take"
    )
    paused = circle.elder.post(
        f"/api/patients/{pid}/medications/{med['id']}/status",
        {"status": "paused", "reason": "Doctor advised a break"},
    )
    assert paused.json()["status"] == "paused" and paused.json()["daily_use"] == 0
    clock.advance(days=1)
    assert circle.elder.get(f"/api/patients/{pid}/doses").json() == []  # nothing while paused
    circle.elder.post(f"/api/patients/{pid}/medications/{med['id']}/status", {"status": "active"})
    assert len(circle.elder.get(f"/api/patients/{pid}/doses").json()) in (0, 1)
    assert circle.elder.delete(f"/api/patients/{pid}/medications/{med['id']}").status_code == 204
    assert circle.elder.get(f"/api/patients/{pid}/medications?include_inactive=true").json() == []
    # the taken dose from day one is still on record
    history = circle.elder.get(f"/api/patients/{pid}/doses?start=2026-03-10&end=2026-03-10")
    assert [d["status"] for d in history.json()] == ["taken"]


def test_take_skip_undo_and_who_confirmed(clock, circle):
    clock.set(T0)
    pid = circle.pid
    add_med(circle.elder, pid, ["08:00", "20:00"], initial_quantity=10)
    am, pm = circle.elder.get(f"/api/patients/{pid}/doses").json()
    # family has no confirm permission
    assert circle.family.post(f"/api/patients/{pid}/doses/{am['id']}/take").status_code == 403
    taken = circle.carer.post(f"/api/patients/{pid}/doses/{am['id']}/take").json()
    assert taken["status"] == "taken" and taken["confirmed_by"] == "Priya Shah"
    assert taken["confirmation_source"] == "caregiver"
    meds = circle.elder.get(f"/api/patients/{pid}/medications").json()
    assert meds[0]["quantity_on_hand"] == 9
    assert circle.elder.post(f"/api/patients/{pid}/doses/{am['id']}/take").status_code == 409
    # too early: 20:00 dose cannot be confirmed at 07:30
    assert circle.elder.post(f"/api/patients/{pid}/doses/{pm['id']}/take").status_code == 400
    clock.set(datetime(2026, 3, 10, 19, 0, tzinfo=UTC))
    skipped = circle.elder.post(
        f"/api/patients/{pid}/doses/{pm['id']}/skip", {"reason": "Felt unwell, will ask doctor"}
    ).json()
    assert skipped["status"] == "skipped" and skipped["confirmation_source"] == "elder"
    # the elder can undo another person's record; stock is restored
    undone = circle.elder.post(f"/api/patients/{pid}/doses/{am['id']}/undo").json()
    assert undone["status"] in ("missed", "unconfirmed") and undone["confirmed_by"] is None
    assert circle.elder.get(f"/api/patients/{pid}/medications").json()[0]["quantity_on_hand"] == 10
    actions = [
        e["action"] for e in circle.elder.get(f"/api/patients/{pid}/activity").json()["items"]
    ]
    assert {"dose.taken", "dose.skipped", "dose.undone"} <= set(actions)


def test_snooze_rules(clock, circle):
    clock.set(datetime(2026, 3, 10, 8, 0, tzinfo=UTC))
    pid = circle.pid
    clock.set(datetime(2026, 3, 10, 7, 55, tzinfo=UTC))
    add_med(circle.elder, pid, ["08:00"])
    clock.set(datetime(2026, 3, 10, 8, 1, tzinfo=UTC))
    dose = circle.elder.get(f"/api/patients/{pid}/doses").json()[0]
    assert (
        circle.elder.post(
            f"/api/patients/{pid}/doses/{dose['id']}/snooze", {"minutes": 7}
        ).status_code
        == 422
    )
    for _ in range(3):
        assert (
            circle.elder.post(
                f"/api/patients/{pid}/doses/{dose['id']}/snooze", {"minutes": 15}
            ).status_code
            == 200
        )
    assert (
        circle.elder.post(
            f"/api/patients/{pid}/doses/{dose['id']}/snooze", {"minutes": 15}
        ).status_code
        == 400
    )
    # snoozing never changes the dose's status
    assert circle.elder.get(f"/api/patients/{pid}/doses").json()[0]["status"] == "scheduled"


def test_inventory_refill_correction_and_negative_prevention(clock, circle):
    clock.set(T0)
    pid = circle.pid
    med = add_med(circle.elder, pid, ["08:00"], initial_quantity=1, dose_amount=2)
    url = f"/api/patients/{pid}/medications/{med['id']}/inventory"
    assert circle.elder.post(url, {"kind": "refill", "quantity": 0}).status_code == 400
    assert circle.elder.post(url, {"kind": "correction", "quantity": -1}).status_code == 422
    assert circle.family.post(url, {"kind": "refill", "quantity": 10}).status_code == 403
    # a caregiver who confirms doses may record a refill but not correct the count
    refill = circle.carer.post(url, {"kind": "refill", "quantity": 28, "note": "Pharmacy"})
    assert refill.status_code == 200
    assert refill.json()["medication"]["quantity_on_hand"] == 29
    assert circle.carer.post(url, {"kind": "correction", "quantity": 5}).status_code == 403
    fixed = circle.elder.post(url, {"kind": "correction", "quantity": 1, "note": "Counted"})
    assert fixed.json()["medication"]["quantity_on_hand"] == 1
    # taking a 2-tablet dose with 1 recorded clamps at zero and flags a recount
    dose = circle.elder.get(f"/api/patients/{pid}/doses").json()[0]
    circle.elder.post(f"/api/patients/{pid}/doses/{dose['id']}/take")
    detail = circle.elder.get(f"/api/patients/{pid}/medications/{med['id']}").json()
    assert detail["medication"]["quantity_on_hand"] == 0
    assert "recount" in detail["inventory"][0]["note"]
    assert [e["kind"] for e in detail["inventory"]] == [
        "dose_taken",
        "correction",
        "refill",
        "initial",
    ]
    assert detail["medication"]["low_stock"] is True


def test_as_needed_records(clock, circle):
    clock.set(T0)
    pid = circle.pid
    prn = add_med(
        circle.elder, pid, [], name="Paracetamol", schedule_type="as_needed", initial_quantity=16
    )
    assert prn["times"] == [] and prn["days_remaining"] is None  # no schedule, no estimate
    rec = circle.carer.post(f"/api/patients/{pid}/medications/{prn['id']}/as-needed", {})
    assert rec.status_code == 201 and rec.json()["as_needed"] is True
    sched = add_med(circle.elder, pid, ["08:00"], name="Fixed")
    assert (
        circle.elder.post(
            f"/api/patients/{pid}/medications/{sched['id']}/as-needed", {}
        ).status_code
        == 400
    )


def test_schedule_math_handles_dst_and_weekdays():
    # London springs forward at 01:00 UTC on 2026-03-29: 01:30 local does not exist.
    occ = occurrences(
        [Slot(time(1, 30))],
        "Europe/London",
        date(2026, 3, 28),
        None,
        datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
        datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert [o.local_date.isoformat() for o in occ] == ["2026-03-28", "2026-03-29", "2026-03-30"]
    assert len({o.scheduled_at for o in occ}) == 3  # one dose per day, none lost or doubled
    # Falls back on 2026-10-25: 01:30 happens twice locally, still exactly one dose.
    autumn = occurrences(
        [Slot(time(1, 30))],
        "Europe/London",
        date(2026, 10, 24),
        None,
        datetime(2026, 10, 24, tzinfo=UTC),
        datetime(2026, 10, 27, tzinfo=UTC),
    )
    assert len(autumn) == 3
    weekdays = occurrences(
        [Slot(time(9, 0), days_mask=0b0011111)],
        "UTC",
        date(2026, 3, 1),
        None,
        datetime(2026, 3, 9, tzinfo=UTC),
        datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert len(weekdays) == 5  # Monday to Friday only
    assert daily_use([Slot(time(9, 0), days_mask=0b0011111)], Decimal(2)) == Decimal("1.4286")
    assert stock_estimate(Decimal(10), Decimal(2), date(2026, 3, 1)) == (
        Decimal("5.0"),
        date(2026, 3, 6),
    )
    assert stock_estimate(None, Decimal(2), date(2026, 3, 1)) == (None, None)

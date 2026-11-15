"""Reminder engine: dose reminders, escalation, missed classification, dedupe, retries,
appointment and low-stock reminders, and the job endpoint's authentication."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Notification
from app.services.email import memory_outbox
from app.services.engine import tick
from tests.conftest import Api, add_med

T0 = datetime(2026, 3, 10, 7, 50, tzinfo=UTC)  # London = UTC on this date


def _notes(db, kind: str | None = None) -> list[Notification]:
    db.expire_all()
    stmt = select(Notification).order_by(Notification.id)
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    return list(db.scalars(stmt))


def _emails_to(email: str) -> list[str]:
    return [m.subject for m in memory_outbox.messages if m.to == email]


def test_full_reminder_then_escalation_flow(clock, circle, db):
    clock.set(T0)
    add_med(circle.elder, circle.pid, ["08:00"])
    add_med(circle.elder, circle.pid, ["08:00"], name="Lisinopril", strength="10 mg")
    memory_outbox.messages.clear()

    clock.set(datetime(2026, 3, 10, 8, 2, tzinfo=UTC))
    tick(db, clock.now)
    reminders = _notes(db, "dose_reminder")
    # one reminder for the 08:00 slot (two medicines), only to the elder by default
    assert [n.recipient.email for n in reminders] == ["margaret.ellis@example.com"]
    assert "2 scheduled doses" in reminders[0].body
    assert reminders[0].status == "sent"
    assert "Metformin" not in reminders[0].subject + reminders[0].body  # privacy: no med names

    tick(db, clock.advance(minutes=5))
    assert len(_notes(db, "dose_reminder")) == 1  # dedupe across ticks
    assert _notes(db, "dose_escalation") == []

    clock.set(datetime(2026, 3, 10, 9, 1, tzinfo=UTC))  # 60-minute grace period has passed
    report = tick(db, clock.now)
    assert report.became_unconfirmed == 2
    escalations = _notes(db, "dose_escalation")
    assert sorted(n.recipient.email for n in escalations) == [
        "daniel.ellis@example.com",
        "priya.shah@example.com",
    ]
    body = escalations[0].body
    assert "not an emergency" in body and "Margaret" in body
    assert (
        _emails_to("margaret.ellis@example.com").count("A scheduled dose has not been confirmed")
        == 0
    )  # elder is not escalated to
    tick(db, clock.advance(minutes=5))
    assert len(_notes(db, "dose_escalation")) == 2  # still no duplicates

    doses = circle.elder.get(f"/api/patients/{circle.pid}/doses").json()
    assert {d["status"] for d in doses} == {"unconfirmed"}  # not assumed missed

    clock.set(datetime(2026, 3, 10, 12, 1, tzinfo=UTC))  # 240-minute missed window closed
    assert tick(db, clock.now).became_missed == 2
    assert {d["status"] for d in circle.elder.get(f"/api/patients/{circle.pid}/doses").json()} == {
        "missed"
    }


def test_escalation_respects_permissions_and_preferences(clock, circle, db):
    clock.set(T0)
    add_med(circle.elder, circle.pid, ["08:00"])
    # The family member opts out of escalation emails
    circle.family.put(
        f"/api/patients/{circle.pid}/members/me/preferences",
        {
            "notify_dose_reminders": False,
            "notify_escalations": False,
            "notify_appointments": True,
            "notify_low_stock": True,
        },
    )
    # The caregiver loses medicine visibility
    members = circle.elder.get(f"/api/patients/{circle.pid}/members").json()
    carer = next(m["id"] for m in members if m["role"] == "caregiver")
    circle.elder.patch(
        f"/api/patients/{circle.pid}/members/{carer}", {"permissions": ["view_appointments"]}
    )
    clock.set(datetime(2026, 3, 10, 9, 5, tzinfo=UTC))
    tick(db, clock.now)
    assert tick(db, clock.now).became_unconfirmed == 0
    assert _notes(db, "dose_escalation") == []


def test_confirmation_stops_escalation_and_withdraws_queued_alerts(clock, circle, db):
    clock.set(T0)
    add_med(circle.elder, circle.pid, ["08:00"])
    clock.set(datetime(2026, 3, 10, 8, 3, tzinfo=UTC))
    memory_outbox.fail_next = 1  # the reminder's first delivery attempt fails
    tick(db, clock.now)
    queued = _notes(db, "dose_reminder")[0]
    assert queued.status == "pending" and queued.attempts == 1
    dose = circle.elder.get(f"/api/patients/{circle.pid}/doses").json()[0]
    circle.elder.post(f"/api/patients/{circle.pid}/doses/{dose['id']}/take")
    assert _notes(db, "dose_reminder")[0].status == "suppressed"  # not sent after the fact
    clock.set(datetime(2026, 3, 10, 9, 30, tzinfo=UTC))
    tick(db, clock.now)
    assert _notes(db, "dose_escalation") == []


def test_delivery_retries_with_backoff_then_fails_permanently(clock, circle, db):
    clock.set(T0)
    add_med(circle.elder, circle.pid, ["08:00"])
    clock.set(datetime(2026, 3, 10, 8, 1, tzinfo=UTC))
    memory_outbox.fail_next = 2
    tick(db, clock.now)
    note = _notes(db, "dose_reminder")[0]
    assert note.status == "pending" and note.attempts == 1 and note.last_error
    tick(db, clock.advance(minutes=1))  # backoff (2 min) not over: no attempt
    assert _notes(db, "dose_reminder")[0].attempts == 1
    tick(db, clock.advance(minutes=2))
    assert _notes(db, "dose_reminder")[0].attempts == 2
    tick(db, clock.advance(minutes=5))
    note = _notes(db, "dose_reminder")[0]
    assert note.status == "sent" and note.attempts == 3 and note.last_error == ""

    memory_outbox.fail_next = 99
    clock.set(datetime(2026, 3, 11, 8, 1, tzinfo=UTC))
    tick(db, clock.now)  # day two's reminder: first attempt fails
    for _ in range(8):  # backoff is 2, 4, 8, 16 minutes: 8 ticks cover all retries
        tick(db, clock.advance(minutes=5))
    failed = [n for n in _notes(db, "dose_reminder") if n.status == "failed"]
    assert failed and failed[0].attempts == 5  # EMAIL_MAX_ATTEMPTS


def test_unverified_recipients_get_in_app_only(clock, db):
    from tests.conftest import create_elder, register

    clock.set(T0)
    elder = register("Una Verified", verify=False)
    pid = create_elder(elder, "Una Verified")
    add_med(elder, pid, ["08:00"])
    clock.set(datetime(2026, 3, 10, 8, 1, tzinfo=UTC))
    tick(db, clock.now)
    note = _notes(db, "dose_reminder")[0]
    assert note.status == "suppressed"
    assert not _emails_to("una.verified@example.com")[1:]  # only the verification email
    assert elder.get("/api/notifications").json()["unread"] == 1  # still visible in-app


def test_snooze_produces_a_new_reminder_after_the_snooze(clock, circle, db):
    clock.set(T0)
    add_med(circle.elder, circle.pid, ["08:00"])
    clock.set(datetime(2026, 3, 10, 8, 1, tzinfo=UTC))
    tick(db, clock.now)
    dose = circle.elder.get(f"/api/patients/{circle.pid}/doses").json()[0]
    circle.elder.post(f"/api/patients/{circle.pid}/doses/{dose['id']}/snooze", {"minutes": 15})
    tick(db, clock.advance(minutes=10))
    assert len(_notes(db, "dose_reminder")) == 1
    tick(db, clock.advance(minutes=6))
    assert len(_notes(db, "dose_reminder")) == 2


def test_appointment_reminders_send_only_the_nearest_due_offset(clock, circle, db):
    clock.set(datetime(2026, 3, 10, 9, 0, tzinfo=UTC))
    res = circle.family.post(
        f"/api/patients/{circle.pid}/appointments",
        {
            "doctor_name": "Dr Okafor",
            "date": "2026-03-10",
            "time": "10:30",
            "reminder_offsets": [1440, 120],
        },
    )
    assert res.status_code == 201
    tick(db, clock.now)
    notes = _notes(db, "appointment_reminder")
    # 24h reminder time has passed and the 2h one too: only one (the 2h) is sent
    assert len({n.recipient_user_id for n in notes}) == len(notes) == 3
    assert all(":120:" in n.dedupe_key for n in notes)
    tick(db, clock.advance(minutes=30))
    assert len(_notes(db, "appointment_reminder")) == 3
    # rescheduling re-arms reminders for the new time
    circle.family.put(
        f"/api/patients/{circle.pid}/appointments/{res.json()['id']}",
        {
            "doctor_name": "Dr Okafor",
            "date": "2026-03-11",
            "time": "10:30",
            "reminder_offsets": [1440, 120],
        },
    )
    tick(db, clock.advance(hours=2))
    assert len(_notes(db, "appointment_reminder")) == 6


def test_low_stock_warning_once_per_week(clock, circle, db):
    clock.set(T0)
    add_med(
        circle.elder, circle.pid, ["08:00", "20:00"], initial_quantity=10, refill_threshold_days=7
    )  # 5 days left
    tick(db, clock.now)
    low = _notes(db, "low_stock")
    # elder (manage) and caregiver (confirms doses); family can only view -> not notified
    assert sorted(n.recipient.email for n in low) == [
        "margaret.ellis@example.com",
        "priya.shah@example.com",
    ]
    assert "estimate" in low[0].body.lower()
    tick(db, clock.advance(hours=3))
    assert len(_notes(db, "low_stock")) == 2


def test_engine_is_quiet_with_no_data(clock, db):
    # negative control: nothing scheduled -> nothing generated, nothing sent
    report = tick(db, clock.now)
    assert report.doses_created == 0 and dict(report.queued) == {}
    assert report.delivery == {"sent": 0, "retrying": 0, "failed": 0}


def test_job_endpoint_requires_authentication():
    api = Api()
    assert api.client.post("/internal/jobs/tick").status_code == 401
    assert (
        api.client.post("/internal/jobs/tick", headers={"X-Job-Token": "wrong"}).status_code == 401
    )
    ok = api.client.post("/internal/jobs/tick", headers={"X-Job-Token": "test-job-token"})
    assert ok.status_code == 200 and "delivery" in ok.json()

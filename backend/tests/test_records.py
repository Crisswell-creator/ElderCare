"""Adherence analytics, appointments, documents, the visit-summary PDF, the audit log and
platform endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import DoseEvent
from app.services import adherence, visit_pdf
from tests.conftest import Api, add_med

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _seed(db, pid: int, med_id: int, start: date, statuses: list[tuple[str, str]]) -> None:
    """Insert dose rows directly: one per (HH:MM, status), one day apart."""
    for i, (hhmm, status) in enumerate(statuses):
        d = start + timedelta(days=i)
        t = time.fromisoformat(hhmm)
        db.add(
            DoseEvent(
                patient_id=pid,
                medication_id=med_id,
                local_date=d,
                local_time=t,
                scheduled_at=datetime.combine(d, t, tzinfo=UTC),
                dose_amount=1,
                status=status,
            )
        )
    db.commit()


# ---- adherence -------------------------------------------------------------------------


def test_adherence_rules_exclude_unconfirmed_and_cancelled(clock, circle, db):
    # 10:00 on 10 March: the 08:00 dose that day is past its grace period but inside the
    # missed window, so it is legitimately "unconfirmed".
    clock.set(datetime(2026, 3, 10, 10, 0, tzinfo=UTC))
    med = add_med(circle.elder, circle.pid, ["08:00"], start_date="2026-03-01")
    db.query(DoseEvent).delete()
    db.commit()
    _seed(
        db,
        circle.pid,
        med["id"],
        date(2026, 3, 1),
        [("08:00", "taken")] * 6
        + [
            ("08:00", "skipped"),
            ("08:00", "missed"),
            ("08:00", "cancelled"),
            ("08:00", "unconfirmed"),
        ],
    )
    rep = circle.family.get(
        f"/api/patients/{circle.pid}/adherence?start=2026-03-01&end=2026-03-10"
    ).json()
    t = rep["totals"]
    assert (t["taken"], t["skipped"], t["missed"], t["unconfirmed"]) == (6, 1, 1, 1)
    assert t["scheduled"] == 9  # cancelled excluded
    assert t["adherence_pct"] == 75.0  # 6 / (6 + 1 + 1): unconfirmed not counted as missed
    assert rep["rules"] and rep["insights"] == []  # far too little data for any insight
    weekly = circle.family.get(
        f"/api/patients/{circle.pid}/adherence?start=2026-03-01&end=2026-03-10&granularity=week"
    ).json()
    assert sum(p["scheduled"] for p in weekly["series"]) == 9
    assert weekly["series"][0]["period"] == "2026-02-23"  # ISO week starting Monday
    assert circle.carer.get(f"/api/patients/{circle.pid}/adherence").status_code == 403


def test_insights_need_enough_data_and_a_real_gap(db, circle, clock):
    clock.set(datetime(2026, 3, 1, 6, 0, tzinfo=UTC))
    morning = add_med(circle.elder, circle.pid, ["08:00"], name="Morning Med")
    evening = add_med(circle.elder, circle.pid, ["19:00"], name="Evening Med")
    db.query(DoseEvent).delete()
    db.commit()
    start = date(2026, 1, 1)
    _seed(db, circle.pid, morning["id"], start, [("08:00", "taken")] * 12)
    _seed(
        db, circle.pid, evening["id"], start, [("19:00", "taken")] * 6 + [("19:00", "missed")] * 6
    )
    rep = adherence.build(db, circle.pid, start, start + timedelta(days=40), "day")
    kinds = {i["kind"]: i for i in adherence.insights(rep)}
    assert (
        "Evening doses have a higher recorded missed or skipped rate (50%)"
        in kinds["time_of_day"]["text"]
    )
    assert "Based on 12 evening and 12 morning doses" in kinds["time_of_day"]["basis"]
    assert "Evening Med has a lower recorded confirmation rate" in kinds["medication"]["text"]

    # Negative control: same volume, no gap -> exactly no insights.
    db.query(DoseEvent).delete()
    db.commit()
    _seed(db, circle.pid, morning["id"], start, [("08:00", "taken")] * 12)
    _seed(db, circle.pid, evening["id"], start, [("19:00", "taken")] * 12)
    assert (
        adherence.insights(
            adherence.build(db, circle.pid, start, start + timedelta(days=40), "day")
        )
        == []
    )


# ---- appointments ----------------------------------------------------------------------


def test_appointment_lifecycle_and_visibility(clock, circle):
    clock.set(datetime(2026, 3, 10, 9, 0, tzinfo=UTC))
    pid = circle.pid
    body = {
        "doctor_name": "Dr Amara Okafor",
        "specialty": "Cardiology",
        "date": "2026-03-20",
        "time": "14:15",
        "location": "St Mary's, Clinic 4",
        "purpose": "Blood pressure review",
    }
    assert circle.carer.post(f"/api/patients/{pid}/appointments", body).status_code == 403
    past = circle.family.post(f"/api/patients/{pid}/appointments", {**body, "date": "2026-03-01"})
    assert past.status_code == 400
    bad = circle.family.post(f"/api/patients/{pid}/appointments", {**body, "reminder_offsets": [7]})
    assert bad.status_code == 422
    created = circle.family.post(f"/api/patients/{pid}/appointments", body)
    assert created.status_code == 201
    appt = created.json()
    assert appt["local_time"] == "14:15" and appt["starts_at"].startswith("2026-03-20T14:15")
    # the elder sees it; the caregiver (view permission) sees it too
    assert [a["id"] for a in circle.elder.get(f"/api/patients/{pid}/appointments").json()] == [
        appt["id"]
    ]
    assert circle.carer.get(f"/api/patients/{pid}/appointments").status_code == 200
    moved = circle.family.put(
        f"/api/patients/{pid}/appointments/{appt['id']}", {**body, "time": "15:00"}
    )
    assert moved.json()["local_time"] == "15:00"
    ics = circle.elder.get(f"/api/patients/{pid}/appointments/{appt['id']}/calendar.ics")
    assert ics.headers["content-type"].startswith("text/calendar")
    assert "DTSTART:20260320T150000Z" in ics.text and "St Mary's\\, Clinic 4" in ics.text
    cancelled = circle.family.post(
        f"/api/patients/{pid}/appointments/{appt['id']}/cancel", {"reason": "Clinic rescheduled"}
    )
    assert cancelled.json()["status"] == "cancelled"
    assert circle.elder.get(f"/api/patients/{pid}/appointments").json() == []
    assert (
        circle.elder.get(f"/api/patients/{pid}/appointments?scope=past").json()[0]["status"]
        == "cancelled"
    )
    actions = [
        e["action"] for e in circle.elder.get(f"/api/patients/{pid}/activity").json()["items"]
    ]
    assert {"appointment.created", "appointment.rescheduled", "appointment.cancelled"} <= set(
        actions
    )


def test_questions_for_the_doctor(circle):
    pid = circle.pid
    q = circle.family.post(
        f"/api/patients/{pid}/questions", {"text": "Should the evening dose move earlier?"}
    ).json()
    mine = circle.elder.post(f"/api/patients/{pid}/questions", {"text": "Dizzy in mornings"})
    assert mine.status_code == 201
    assert circle.carer.post(f"/api/patients/{pid}/questions/{q['id']}/resolve").status_code == 403
    assert circle.elder.post(f"/api/patients/{pid}/questions/{q['id']}/resolve").json()["resolved"]
    texts = [x["text"] for x in circle.carer.get(f"/api/patients/{pid}/questions").json()]
    assert texts[0] == "Dizzy in mornings"  # unresolved first


# ---- documents -------------------------------------------------------------------------


def test_document_upload_validation_and_access(circle):
    pid = circle.pid
    files = {"file": ("lab result.pdf", PDF_BYTES, "application/pdf")}
    data = {"title": "Blood test March", "category": "lab_result"}
    assert (
        circle.family.client.post(
            f"/api/patients/{pid}/documents",
            data=data,
            files=files,
            headers=circle.family._headers(),
        ).status_code
        == 403
    )
    up = circle.elder.client.post(
        f"/api/patients/{pid}/documents", data=data, files=files, headers=circle.elder._headers()
    )
    assert up.status_code == 201, up.text
    doc = up.json()
    assert doc["content_type"] == "application/pdf" and doc["filename"] == "lab result.pdf"
    # spoofed type: an executable renamed .pdf with a PDF content-type is refused
    fake = circle.elder.client.post(
        f"/api/patients/{pid}/documents",
        data=data,
        files={"file": ("x.pdf", b"MZ\x90\x00binary", "application/pdf")},
        headers=circle.elder._headers(),
    )
    assert fake.status_code == 400
    big = circle.elder.client.post(
        f"/api/patients/{pid}/documents",
        data=data,
        files={"file": ("big.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024), "application/pdf")},
        headers=circle.elder._headers(),
    )
    assert big.status_code == 400 and "10 MB" in big.json()["error"]["message"]
    # viewing needs view_documents: the caregiver was not given it
    assert (
        circle.carer.get(f"/api/patients/{pid}/documents/{doc['id']}/download").status_code == 403
    )
    dl = circle.elder.get(f"/api/patients/{pid}/documents/{doc['id']}/download")
    assert dl.content == PDF_BYTES and "attachment" in dl.headers["content-disposition"]
    assert dl.headers["cache-control"] == "private, no-store"
    stranger = Api()
    assert stranger.get(f"/api/patients/{pid}/documents/{doc['id']}/download").status_code == 401
    assert circle.elder.delete(f"/api/patients/{pid}/documents/{doc['id']}").status_code == 204
    assert circle.elder.get(f"/api/patients/{pid}/documents").json() == []


# ---- visit summary ---------------------------------------------------------------------


def test_visit_summary_pdf_from_real_records(clock, circle):
    clock.set(datetime(2026, 3, 10, 7, 0, tzinfo=UTC))
    pid = circle.pid
    circle.elder.post(
        f"/api/patients/{pid}/allergies",
        {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"},
    )
    add_med(circle.elder, pid, ["08:00", "20:00"])
    res = circle.family.get(f"/api/patients/{pid}/visit-summary.pdf")
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF") and res.content.count(b"/Type /Page\n") <= 1
    assert circle.carer.get(f"/api/patients/{pid}/visit-summary.pdf").status_code == 200
    actions = [
        e["action"] for e in circle.elder.get(f"/api/patients/{pid}/activity").json()["items"]
    ]
    assert "visit_summary.generated" in actions


def test_visit_summary_fits_one_page_with_maximum_content():
    long = "W" * 400
    data = visit_pdf.VisitData(
        patient_name=long,
        date_of_birth=date(1941, 5, 2),
        phone="+44 20 7946 0000",
        primary_doctor=long,
        allergies=[long] * 20,
        history=[long] * 20,
        medications=[visit_pdf.MedLine(long, long, long, long, long)] * 20,
        adherence_line=long,
        adherence_basis=long,
        appointments=[long] * 10,
        questions=[long] * 20,
        generated_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
        generated_by=long,
    )
    pdf = visit_pdf.render(data)
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") == 1, "summary overflowed"


# ---- audit log & platform ----------------------------------------------------------------


def test_audit_log_is_append_only_at_database_level(circle, db):
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_events SET summary = 'tampered'"))
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_events"))
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM audit_events")).scalar() > 0


def test_activity_pagination_and_permission(circle):
    pid = circle.pid
    for i in range(5):
        circle.elder.post(f"/api/patients/{pid}/allergies", {"substance": f"Item {i}"})
    page1 = circle.elder.get(f"/api/patients/{pid}/activity?limit=3").json()
    assert len(page1["items"]) == 3 and page1["next_before"]
    page2 = circle.elder.get(
        f"/api/patients/{pid}/activity?limit=3&before={page1['next_before']}"
    ).json()
    assert {e["id"] for e in page1["items"]}.isdisjoint({e["id"] for e in page2["items"]})
    assert circle.carer.get(f"/api/patients/{pid}/activity").status_code == 403
    assert circle.family.get(f"/api/patients/{pid}/activity").status_code == 200


def test_health_profile_crud_and_overview_trimmed_by_permission(circle):
    pid = circle.pid
    c = circle.elder.post(
        f"/api/patients/{pid}/contacts",
        {"name": "Ruth Ellis", "phone": "+44 7700 900123", "is_primary": True},
    )
    assert c.status_code == 201
    assert (
        circle.elder.post(
            f"/api/patients/{pid}/contacts", {"name": "X", "phone": "call me"}
        ).status_code
        == 422
    )
    assert (
        circle.family.post(
            f"/api/patients/{pid}/history", {"kind": "condition", "title": "Type 2 diabetes"}
        ).status_code
        == 403
    )
    h = circle.elder.post(
        f"/api/patients/{pid}/history", {"kind": "condition", "title": "Type 2 diabetes"}
    ).json()
    circle.elder.put(
        f"/api/patients/{pid}/history/{h['id']}",
        {"kind": "condition", "title": "Type 2 diabetes", "status": "managed"},
    )
    profile = circle.family.get(f"/api/patients/{pid}").json()
    assert profile["history"][0]["status"] == "managed"
    assert profile["contacts"][0]["name"] == "Ruth Ellis"
    carer_view = circle.carer.get(f"/api/patients/{pid}/overview").json()
    assert carer_view["adherence_30d"] is None and carer_view["recent_activity"] is None
    assert carer_view["today_doses"] == [] and carer_view["emergency_contacts"][0]["phone"]
    upd = circle.elder.patch(f"/api/patients/{pid}", {"date_of_birth": "2999-01-01"})
    assert upd.status_code == 422
    rules = circle.elder.put(
        f"/api/patients/{pid}/reminder-rules",
        {"dose_grace_minutes": 90, "missed_after_minutes": 60},
    )
    assert rules.status_code == 422


def test_me_overview_groups_all_circles(circle):
    res = circle.carer.get("/api/me/overview").json()
    assert len(res) == 1 and res[0]["role"] == "caregiver"
    assert res[0]["doses_today"] == {
        "scheduled": 0,
        "taken": 0,
        "skipped": 0,
        "missed": 0,
        "unconfirmed": 0,
    }


def test_health_endpoints_and_security_headers():
    api = Api()
    live = api.get("/healthz")
    assert live.json() == {"status": "ok"}
    assert api.get("/readyz").json() == {"status": "ok"}
    for header in (
        "content-security-policy",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
    ):
        assert header in live.headers
    err = api.get("/api/patients/1")
    assert err.status_code == 401 and err.json()["error"]["code"] == "unauthorized"
    assert err.headers["cache-control"] == "no-store"


def test_unhandled_errors_return_generic_message(monkeypatch):
    from app.api import notifications

    def boom(*_args, **_kwargs):
        raise RuntimeError("secret internal detail")

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/healthz")
    client.post(
        "/api/auth/register",
        json={"email": "z@example.com", "password": "z pass phrase 1", "full_name": "Z"},
        headers={"X-CSRF-Token": client.cookies.get("ec_csrf") or ""},
    )
    monkeypatch.setattr(notifications, "select", boom)
    res = client.get("/api/notifications")
    assert res.status_code == 500 and "secret" not in res.text

"""Opt-in demo data for local review and judging: `uv run python -m app.seed_demo`.

Everything created here is fictional and labelled as such in the profile itself. It is
refused in production unless ALLOW_DEMO_SEED=true is set explicitly, and it never runs
automatically.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.domain import SUGGESTED, DoseStatus, InventoryKind, Permission, Role
from app.models import (
    Allergy,
    Appointment,
    Doctor,
    DoseEvent,
    EmergencyContact,
    HistoryEntry,
    Medication,
    MedicationTime,
    Membership,
    Patient,
    User,
    VisitQuestion,
)
from app.security import hash_password
from app.services import audit, inventory

PASSWORD = os.environ.get("DEMO_PASSWORD", "demo pass phrase")
TZ = "Europe/London"


def _user(db: Session, email: str, name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=name,
            password_hash=hash_password(PASSWORD),
            timezone=TZ,
            email_verified_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()
    return user


def main() -> None:
    if get_settings().is_production and os.environ.get("ALLOW_DEMO_SEED") != "true":
        sys.exit("Refusing to seed demo data in production (set ALLOW_DEMO_SEED=true to override).")
    rng = random.Random(7)  # noqa: S311 - deterministic demo data, not security
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == "demo.elder@example.com")):
            print("Demo data already present.")
            return
        elder = _user(db, "demo.elder@example.com", "Margaret Ellis")
        family = _user(db, "demo.family@example.com", "Daniel Ellis")
        carer = _user(db, "demo.carer@example.com", "Priya Shah")
        now = datetime.now(UTC)
        start_day = (now - timedelta(days=21)).astimezone(ZoneInfo(TZ)).date()

        patient = Patient(
            full_name="Margaret Ellis",
            preferred_name="Margaret",
            date_of_birth=date(1944, 6, 12),
            timezone=TZ,
            phone="+44 20 7946 0811",
            address="14 Willow Road, London",
            notes="Fictional demo profile. Uses reading glasses; prefers large text.",
            created_by_user_id=elder.id,
        )
        db.add(patient)
        db.flush()
        db.add_all(
            [
                Membership(
                    patient_id=patient.id,
                    user_id=elder.id,
                    role=Role.ELDER,
                    relationship_label="Self",
                    permissions=[p.value for p in Permission],
                    notify_dose_reminders=True,
                    granted_by_user_id=elder.id,
                ),
                Membership(
                    patient_id=patient.id,
                    user_id=family.id,
                    role=Role.FAMILY,
                    relationship_label="Son",
                    granted_by_user_id=elder.id,
                    permissions=[p.value for p in SUGGESTED[Role.FAMILY]]
                    + ["view_activity", "manage_appointments", "view_documents"],
                ),
                Membership(
                    patient_id=patient.id,
                    user_id=carer.id,
                    role=Role.CAREGIVER,
                    relationship_label="Home carer",
                    granted_by_user_id=elder.id,
                    permissions=[p.value for p in SUGGESTED[Role.CAREGIVER]],
                ),
            ]
        )
        db.add_all(
            [
                Allergy(
                    patient_id=patient.id,
                    substance="Penicillin",
                    reaction="Hives",
                    severity="moderate",
                ),
                HistoryEntry(
                    patient_id=patient.id,
                    kind="condition",
                    title="Type 2 diabetes",
                    status="managed",
                    occurred_on=date(2015, 3, 1),
                ),
                HistoryEntry(
                    patient_id=patient.id,
                    kind="condition",
                    title="High blood pressure",
                    status="managed",
                    occurred_on=date(2012, 9, 1),
                ),
                HistoryEntry(
                    patient_id=patient.id,
                    kind="procedure",
                    title="Right hip replacement",
                    status="historical",
                    occurred_on=date(2019, 11, 1),
                ),
                EmergencyContact(
                    patient_id=patient.id,
                    name="Daniel Ellis",
                    relationship_label="Son",
                    phone="+44 7700 900461",
                    is_primary=True,
                ),
                EmergencyContact(
                    patient_id=patient.id,
                    name="Ruth Clarke",
                    relationship_label="Neighbour",
                    phone="+44 7700 900982",
                ),
                Doctor(
                    patient_id=patient.id,
                    name="Dr Amara Okafor",
                    specialty="General practice",
                    clinic="Willow Road Surgery",
                    phone="+44 20 7946 0123",
                    is_primary=True,
                ),
            ]
        )
        meds = [
            (
                "Metformin",
                "500 mg",
                "Take with breakfast and evening meal",
                [time(8), time(18)],
                1,
                34,
            ),
            ("Lisinopril", "10 mg", "Take in the morning", [time(8)], 1, 12),
            ("Atorvastatin", "20 mg", "Take at bedtime", [time(21)], 1, 40),
        ]
        created: list[Medication] = []
        for name, strength, instr, times, amount, qty in meds:
            med = Medication(
                patient_id=patient.id,
                name=name,
                strength=strength,
                dose_amount=Decimal(amount),
                dose_unit="tablet",
                instructions=instr,
                start_date=start_day - timedelta(days=200),
                prescriber="Dr Amara Okafor",
                created_by_user_id=elder.id,
                schedule_anchor_at=now - timedelta(days=21, hours=1),
            )
            med.times = [MedicationTime(local_time=t) for t in times]
            db.add(med)
            db.flush()
            inventory.apply(
                db,
                med,
                InventoryKind.INITIAL,
                absolute=Decimal(qty),
                actor=elder,
                note="Starting count (demo)",
            )
            created.append(med)
        prn = Medication(
            patient_id=patient.id,
            name="Paracetamol",
            strength="500 mg",
            dose_amount=Decimal(2),
            dose_unit="tablet",
            schedule_type="as_needed",
            instructions="Up to 4 times a day if needed for pain",
            start_date=start_day,
            created_by_user_id=elder.id,
        )
        db.add(prn)
        audit.record(
            db,
            patient_id=patient.id,
            actor=elder,
            action="profile.created",
            entity_type="patient",
            entity_id=patient.id,
            summary="Margaret Ellis created her own profile (demo data)",
        )

        # Three weeks of history: evening doses are recorded less reliably than morning ones,
        # so the insight engine has a genuine pattern to find in this fictional record.
        tz = ZoneInfo(TZ)
        for offset in range(21, 0, -1):
            day = (now - timedelta(days=offset)).astimezone(tz).date()
            for med in created:
                for t in med.times:
                    at = datetime.combine(day, t.local_time, tzinfo=tz).astimezone(UTC)
                    evening = t.local_time.hour >= 17
                    roll = rng.random()
                    status = (
                        DoseStatus.TAKEN
                        if roll < (0.68 if evening else 0.95)
                        else DoseStatus.MISSED
                        if roll < (0.9 if evening else 0.98)
                        else DoseStatus.SKIPPED
                    )
                    who = elder if rng.random() < 0.8 else carer
                    db.add(
                        DoseEvent(
                            patient_id=patient.id,
                            medication_id=med.id,
                            scheduled_at=at,
                            local_date=day,
                            local_time=t.local_time,
                            dose_amount=med.dose_amount,
                            status=status,
                            confirmed_at=at + timedelta(minutes=rng.randint(2, 40))
                            if status != DoseStatus.MISSED
                            else None,
                            confirmed_by_user_id=who.id if status != DoseStatus.MISSED else None,
                            confirmation_source=("elder" if who is elder else "caregiver")
                            if status != DoseStatus.MISSED
                            else "",
                            skip_reason="Felt nauseous" if status == DoseStatus.SKIPPED else "",
                            status_changed_at=at + timedelta(hours=1),
                        )
                    )
        local_today = now.astimezone(tz).date()
        db.add_all(
            [
                Appointment(
                    patient_id=patient.id,
                    doctor_name="Dr Amara Okafor",
                    specialty="General practice",
                    duration_minutes=20,
                    starts_at=datetime.combine(
                        local_today + timedelta(days=3), time(10, 30), tzinfo=tz
                    ).astimezone(UTC),
                    location="Willow Road Surgery, Room 2",
                    purpose="Diabetes review",
                    created_by_user_id=family.id,
                ),
                Appointment(
                    patient_id=patient.id,
                    doctor_name="Mr James Patel",
                    specialty="Ophthalmology",
                    duration_minutes=45,
                    starts_at=datetime.combine(
                        local_today + timedelta(days=17), time(14, 0), tzinfo=tz
                    ).astimezone(UTC),
                    location="St Mary's Eye Clinic",
                    purpose="Annual eye screening",
                    created_by_user_id=family.id,
                ),
                VisitQuestion(
                    patient_id=patient.id,
                    author_user_id=elder.id,
                    text="Can the evening Metformin be taken earlier? I often forget it.",
                ),
                VisitQuestion(
                    patient_id=patient.id,
                    author_user_id=family.id,
                    text="Should Mum's blood pressure be checked at home?",
                ),
            ]
        )
        db.commit()
        print("Demo data created (fictional). Sign in with:")
        for u in (elder, family, carer):
            print(f"  {u.email}")
        print("Password: the DEMO_PASSWORD environment variable, or the default in this script.")


if __name__ == "__main__":
    main()

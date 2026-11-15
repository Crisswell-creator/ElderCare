"""SQLAlchemy ORM models. One patient (elder) profile is the unit of data isolation:
every patient-scoped table carries `patient_id`, and every API query filters on it."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, now_default

Qty = Numeric(10, 2)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    text_scale: Mapped[str] = mapped_column(String(16), default="standard")
    # Accessibility preferences: contrast, reduce_motion, simplified_nav, read_aloud.
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    user_agent: Mapped[str] = mapped_column(String(255), default="")

    user: Mapped[User] = relationship(lazy="joined")


class AuthToken(Base):
    """Single-use email tokens (verification, password reset). Only the hash is stored."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)


class AuthAttempt(Base):
    """Persisted attempt log used for throttling login and invitation-code guessing."""

    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_key_created", "key", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(300))
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    preferred_name: Mapped[str] = mapped_column(String(60), default="")
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    phone: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # Reminder rules. A dose becomes "unconfirmed" after the grace period and "missed"
    # once the missed window closes; both are configurable per elder.
    dose_grace_minutes: Mapped[int] = mapped_column(Integer, default=60)
    missed_after_minutes: Mapped[int] = mapped_column(Integer, default=240)
    # Trusted-representative onboarding: set when someone created the profile on the
    # elder's behalf. The attestation is kept verbatim and the elder can claim the
    # profile later, which clears the flag.
    managed_by_representative: Mapped[bool] = mapped_column(Boolean, default=False)
    representative_attestation: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=now_default, onupdate=now_default
    )

    @property
    def first_name(self) -> str:
        """How the elder is addressed in messages: preferred name, else first given name."""
        return self.preferred_name or self.full_name.split(" ")[0]


class Membership(Base):
    """A user's place in one elder's care circle, with explicit permissions."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("patient_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    relationship_label: Mapped[str] = mapped_column(String(60), default="")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_representative: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    notify_dose_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_escalations: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_appointments: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_low_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    patient: Mapped[Patient] = relationship(lazy="joined")


class Invitation(Base):
    """An expiring, single-use code that lets someone *request* access. Redeeming it never
    grants access by itself; it creates an AccessRequest the elder must approve."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(16), default="join")  # join | claim
    intended_role: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    redeemed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    redeemed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    invitation_id: Mapped[int | None] = mapped_column(
        ForeignKey("invitations.id", ondelete="SET NULL")
    )
    requested_role: Mapped[str] = mapped_column(String(16))
    relationship_label: Mapped[str] = mapped_column(String(60), default="")
    message: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    requester: Mapped[User] = relationship(foreign_keys=[requester_user_id], lazy="joined")


class Allergy(Base):
    __tablename__ = "allergies"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    substance: Mapped[str] = mapped_column(String(120))
    reaction: Mapped[str] = mapped_column(String(200), default="")
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)


class HistoryEntry(Base):
    """Medical history: conditions, procedures, hospital stays, immunisations."""

    __tablename__ = "history_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24), default="condition")
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="active")
    occurred_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    relationship_label: Mapped[str] = mapped_column(String(60), default="")
    phone: Mapped[str] = mapped_column(String(40))
    email: Mapped[str] = mapped_column(String(254), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)  # 1 = call first


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(80), default="")
    clinic: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class Medication(Base):
    __tablename__ = "medications"
    __table_args__ = (Index("ix_medications_patient_status", "patient_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    strength: Mapped[str] = mapped_column(String(60), default="")
    form: Mapped[str] = mapped_column(String(24), default="tablet")
    dose_amount: Mapped[Decimal] = mapped_column(Qty, default=Decimal(1))
    dose_unit: Mapped[str] = mapped_column(String(24), default="tablet")
    instructions: Mapped[str] = mapped_column(Text, default="")
    schedule_type: Mapped[str] = mapped_column(String(16), default="scheduled")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    status_reason: Mapped[str] = mapped_column(String(200), default="")
    prescriber: Mapped[str] = mapped_column(String(120), default="")
    quantity_on_hand: Mapped[Decimal | None] = mapped_column(Qty)
    refill_threshold_days: Mapped[int] = mapped_column(Integer, default=7)
    # Doses are generated only from this instant on: set at creation, resume and schedule
    # edits, so changing a schedule never back-fills doses nobody was asked to take.
    schedule_anchor_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=now_default, onupdate=now_default
    )

    times: Mapped[list[MedicationTime]] = relationship(
        cascade="all, delete-orphan", order_by="MedicationTime.local_time", lazy="selectin"
    )


class MedicationTime(Base):
    __tablename__ = "medication_times"
    __table_args__ = (UniqueConstraint("medication_id", "local_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"))
    local_time: Mapped[time] = mapped_column(Time)
    days_mask: Mapped[int] = mapped_column(Integer, default=127)  # bit 0 = Monday


class InventoryEvent(Base):
    """Append-only stock ledger. `Medication.quantity_on_hand` is its running total."""

    __tablename__ = "inventory_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(
        ForeignKey("medications.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    quantity_delta: Mapped[Decimal] = mapped_column(Qty)
    quantity_after: Mapped[Decimal] = mapped_column(Qty)
    note: Mapped[str] = mapped_column(String(300), default="")
    dose_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("dose_events.id", ondelete="SET NULL")
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)

    actor: Mapped[User | None] = relationship(lazy="joined")


class DoseEvent(Base):
    """One scheduled (or as-needed) dose. Generated ahead of time by the reminder engine;
    the unique key makes generation idempotent across retries and parallel runs."""

    __tablename__ = "dose_events"
    __table_args__ = (
        UniqueConstraint("medication_id", "scheduled_at"),
        Index("ix_dose_events_patient_scheduled", "patient_id", "scheduled_at"),
        Index("ix_dose_events_status_scheduled", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime())
    local_date: Mapped[date] = mapped_column(Date)
    local_time: Mapped[time] = mapped_column(Time)
    dose_amount: Mapped[Decimal] = mapped_column(Qty)
    as_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmation_source: Mapped[str] = mapped_column(String(16), default="")
    skip_reason: Mapped[str] = mapped_column(String(200), default="")
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    snooze_count: Mapped[int] = mapped_column(Integer, default=0)
    status_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_reason: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)

    medication: Mapped[Medication] = relationship(lazy="joined")
    confirmed_by: Mapped[User | None] = relationship(lazy="joined")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_patient_starts", "patient_id", "starts_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    doctor_name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(80), default="")
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    location: Mapped[str] = mapped_column(String(300), default="")
    purpose: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    reminder_offsets: Mapped[list[int]] = mapped_column(JSON, default=lambda: [1440, 120])
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=now_default, onupdate=now_default
    )


class VisitQuestion(Base):
    """Questions or notes the elder or family want to raise at a doctor visit."""

    __tablename__ = "visit_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)

    author: Mapped[User | None] = relationship(lazy="joined")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(32), default="other")
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    uploaded_by: Mapped[User | None] = relationship(lazy="joined")


class Notification(Base):
    """Outbox row: every notification is visible in-app; email delivery is tracked here with
    attempts and backoff. `dedupe_key` is unique so the same alert is never queued twice."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_status_next", "status", "next_attempt_at"),
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
        # Unread count for the notification bell, polled by every signed-in screen.
        Index("ix_notifications_recipient_unread", "recipient_user_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    link_path: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)

    recipient: Mapped[User] = relationship(lazy="joined")


class AuditEvent(Base):
    """Append-only activity history. Database triggers (see the initial migration) reject
    UPDATE and DELETE, so no application code path can rewrite it."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_patient_created", "patient_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)

    actor: Mapped[User | None] = relationship(lazy="joined")


class CareTask(Base):
    """A coordination task in one care circle, optionally assigned to a member."""

    __tablename__ = "care_tasks"
    __table_args__ = (
        Index("ix_care_tasks_patient_status_due", "patient_id", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # low | normal | high
    status: Mapped[str] = mapped_column(
        String(16), default="open"
    )  # open | in_progress | done | cancelled
    due_date: Mapped[date | None] = mapped_column(Date)
    assignee_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    completion_note: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=now_default, onupdate=now_default
    )

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_user_id], lazy="joined")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id], lazy="joined")


class CareNote(Base):
    """Shared notes: general notes, care instructions, appointment preparation, updates."""

    __tablename__ = "care_notes"
    __table_args__ = (Index("ix_care_notes_patient_created", "patient_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24), default="note")
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=now_default, onupdate=now_default
    )

    author: Mapped[User | None] = relationship(lazy="joined")


class DocumentBlob(Base):
    """Document bytes for STORAGE_BACKEND=db. Read only through the authorised download API."""

    __tablename__ = "document_blobs"

    storage_key: Mapped[str] = mapped_column(String(300), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now_default)

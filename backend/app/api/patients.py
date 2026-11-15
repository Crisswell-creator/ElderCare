"""Elder healthcare profiles: creation (self or trusted representative), viewing, editing,
and the structured health record (allergies, history, emergency contacts, doctors)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import TimeZone
from app.db import Base, get_db
from app.deps import PatientAccess, get_current_user, patient_access, requires
from app.domain import SUGGESTED, Permission, Role
from app.errors import Conflict, NotFound
from app.models import Allergy, Doctor, EmergencyContact, HistoryEntry, Membership, Patient, User
from app.services import audit

router = APIRouter(prefix="/api/patients", tags=["patients"])

Short = Annotated[str, Field(max_length=120)]


class PatientFields(BaseModel):
    full_name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    preferred_name: Annotated[str, Field(max_length=60)] = ""
    date_of_birth: date | None = None
    timezone: TimeZone = "UTC"
    phone: Annotated[str, Field(max_length=40)] = ""
    address: Annotated[str, Field(max_length=300)] = ""
    notes: Annotated[str, Field(max_length=4000)] = ""

    @model_validator(mode="after")
    def _dob_in_past(self) -> PatientFields:
        _check_dob(self.date_of_birth)
        return self


def _check_dob(dob: date | None) -> None:
    if dob and not date(1900, 1, 1) <= dob <= datetime.now(UTC).date():
        raise ValueError("Date of birth must be a real past date")


class PatientCreate(PatientFields):
    mode: Literal["self", "representative"]
    # Only for mode=representative
    representative_role: Literal["family", "caregiver"] = "family"
    relationship_label: Annotated[str, Field(max_length=60)] = ""
    attestation: Annotated[str, Field(max_length=1000)] = ""

    @model_validator(mode="after")
    def _attestation_required(self) -> PatientCreate:
        if self.mode == "representative" and len(self.attestation.strip()) < 20:
            raise ValueError(
                "Explain the authority or permission you have to manage this person's care"
            )
        return self


class PatientUpdate(BaseModel):
    full_name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")] | None = None
    preferred_name: Annotated[str, Field(max_length=60)] | None = None
    date_of_birth: date | None = None
    timezone: TimeZone | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None
    address: Annotated[str, Field(max_length=300)] | None = None
    notes: Annotated[str, Field(max_length=4000)] | None = None

    @model_validator(mode="after")
    def _dob_in_past(self) -> PatientUpdate:
        _check_dob(self.date_of_birth)
        return self


class ReminderRules(BaseModel):
    dose_grace_minutes: int = Field(ge=15, le=240)
    missed_after_minutes: int = Field(ge=30, le=720)

    @model_validator(mode="after")
    def _ordered(self) -> ReminderRules:
        if self.missed_after_minutes <= self.dose_grace_minutes:
            raise ValueError("The missed window must be longer than the grace period")
        return self


class AllergyIn(BaseModel):
    substance: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    reaction: Annotated[str, Field(max_length=200)] = ""
    severity: Literal["mild", "moderate", "severe", "unknown"] = "unknown"


class HistoryIn(BaseModel):
    kind: Literal["condition", "procedure", "hospitalization", "immunization", "other"]
    title: Annotated[str, Field(min_length=1, max_length=160, pattern=r"\S")]
    status: Literal["active", "resolved", "managed", "historical"] = "active"
    occurred_on: date | None = None
    notes: Annotated[str, Field(max_length=2000)] = ""


class ContactIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    relationship_label: Annotated[str, Field(max_length=60)] = ""
    phone: Annotated[str, Field(min_length=3, max_length=40, pattern=r"^[0-9+()\-.\s]+$")]
    email: Annotated[str, Field(max_length=254)] = ""
    is_primary: bool = False
    priority: int = Field(default=1, ge=1, le=9)


class DoctorIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    specialty: Annotated[str, Field(max_length=80)] = ""
    clinic: Annotated[str, Field(max_length=160)] = ""
    phone: Annotated[str, Field(max_length=40)] = ""
    is_primary: bool = False


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AllergyOut(_Out, AllergyIn):
    pass


class HistoryOut(_Out, HistoryIn):
    pass


class ContactOut(_Out, ContactIn):
    pass


class DoctorOut(_Out, DoctorIn):
    pass


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    preferred_name: str
    date_of_birth: date | None
    timezone: str
    phone: str
    address: str
    notes: str
    dose_grace_minutes: int
    missed_after_minutes: int
    managed_by_representative: bool


class ProfileOut(BaseModel):
    patient: PatientOut
    allergies: list[AllergyOut]
    history: list[HistoryOut]
    contacts: list[ContactOut]
    doctors: list[DoctorOut]
    my_role: str
    my_permissions: list[str]
    can_decide_access: bool


def _profile(db: Session, access: PatientAccess) -> ProfileOut:
    pid = access.patient.id

    def rows(model: type[Any], order: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.patient_id == pid).order_by(order)))

    return ProfileOut(
        patient=PatientOut.model_validate(access.patient),
        allergies=[AllergyOut.model_validate(r) for r in rows(Allergy, Allergy.substance)],
        history=[
            HistoryOut.model_validate(r)
            for r in rows(HistoryEntry, HistoryEntry.occurred_on.desc())
        ],
        contacts=[
            ContactOut.model_validate(r) for r in rows(EmergencyContact, EmergencyContact.priority)
        ],
        doctors=[DoctorOut.model_validate(r) for r in rows(Doctor, Doctor.is_primary.desc())],
        my_role=access.membership.role,
        my_permissions=sorted(access.permissions),
        can_decide_access=access.can_decide_access,
    )


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    body: PatientCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    if body.mode == "self":
        existing = db.scalar(
            select(Membership.id).where(
                Membership.user_id == user.id,
                Membership.role == Role.ELDER,
                Membership.status == "active",
            )
        )
        if existing:
            raise Conflict("You already have your own ElderCare profile.")
    fields = body.model_dump(include=set(PatientFields.model_fields))
    patient = Patient(
        **fields,
        created_by_user_id=user.id,
        managed_by_representative=body.mode == "representative",
        representative_attestation=body.attestation.strip(),
    )
    db.add(patient)
    db.flush()
    if body.mode == "self":
        membership = Membership(
            patient_id=patient.id,
            user_id=user.id,
            role=Role.ELDER,
            relationship_label="Self",
            permissions=[p.value for p in SUGGESTED[Role.ELDER]],
            notify_dose_reminders=True,
            granted_by_user_id=user.id,
        )
        summary = f"{user.full_name} created their own profile"
    else:
        membership = Membership(
            patient_id=patient.id,
            user_id=user.id,
            role=body.representative_role,
            relationship_label=body.relationship_label.strip(),
            permissions=[p.value for p in Permission],
            is_representative=True,
            granted_by_user_id=user.id,
        )
        summary = f"{user.full_name} created this profile as a trusted representative"
    db.add(membership)
    db.flush()
    audit.record(
        db,
        patient_id=patient.id,
        actor=user,
        action="profile.created",
        entity_type="patient",
        entity_id=patient.id,
        summary=summary,
        details={"mode": body.mode, "attestation": body.attestation.strip()},
    )
    db.commit()
    return _profile(db, PatientAccess(user=user, patient=patient, membership=membership))


@router.get("/{patient_id}", response_model=ProfileOut)
def get_patient(
    access: PatientAccess = Depends(requires(Permission.VIEW_PROFILE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    return _profile(db, access)


@router.patch("/{patient_id}", response_model=ProfileOut)
def update_patient(
    body: PatientUpdate,
    access: PatientAccess = Depends(requires(Permission.EDIT_PROFILE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    patient = access.patient
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(patient, k) for k in changes}
    for key, value in changes.items():
        setattr(patient, key, value.strip() if isinstance(value, str) else value)
    delta = audit.diff(before, {k: getattr(patient, k) for k in changes})
    if delta:
        audit.record(
            db,
            patient_id=patient.id,
            actor=access.user,
            action="profile.updated",
            entity_type="patient",
            entity_id=patient.id,
            summary=f"{access.user.full_name} updated profile details ({', '.join(sorted(delta))})",
            details={"changes": delta},
        )
    db.commit()
    return _profile(db, access)


@router.put("/{patient_id}/reminder-rules", response_model=PatientOut)
def set_reminder_rules(
    body: ReminderRules,
    access: PatientAccess = Depends(requires(Permission.MANAGE_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> PatientOut:
    patient = access.patient
    before = {
        "dose_grace_minutes": patient.dose_grace_minutes,
        "missed_after_minutes": patient.missed_after_minutes,
    }
    patient.dose_grace_minutes = body.dose_grace_minutes
    patient.missed_after_minutes = body.missed_after_minutes
    audit.record(
        db,
        patient_id=patient.id,
        actor=access.user,
        action="reminder_rules.updated",
        entity_type="patient",
        entity_id=patient.id,
        summary=f"{access.user.full_name} changed reminder timing",
        details={"changes": audit.diff(before, body.model_dump())},
    )
    db.commit()
    return PatientOut.model_validate(patient)


def _crud(
    path: str,
    model: type[Base],
    schema_in: type[BaseModel],
    schema_out: type[BaseModel],
    label_field: str,
    noun: str,
) -> None:
    """Create/update/delete for a simple patient-scoped health-record table. Reads come
    through the profile endpoint, so a page renders from one request."""

    def _get(db: Session, access: PatientAccess, item_id: int) -> Any:
        item = db.get(model, item_id)
        if item is None or item.patient_id != access.patient.id:  # type: ignore[attr-defined]
            raise NotFound(f"That {noun} was not found.")
        return item

    def _log(db: Session, access: PatientAccess, verb: str, item: Any) -> None:
        audit.record(
            db,
            patient_id=access.patient.id,
            actor=access.user,
            action=f"{path}.{verb}",
            entity_type=path,
            entity_id=item.id,
            summary=f"{access.user.full_name} {verb} {noun} “{getattr(item, label_field)}”",
        )

    def create(
        body: BaseModel,
        access: PatientAccess = Depends(requires(Permission.EDIT_PROFILE)),
        db: Session = Depends(get_db),
    ) -> Any:
        item = model(patient_id=access.patient.id, **body.model_dump())
        db.add(item)
        db.flush()
        _log(db, access, "added", item)
        db.commit()
        return item

    def update(
        item_id: int,
        body: BaseModel,
        access: PatientAccess = Depends(requires(Permission.EDIT_PROFILE)),
        db: Session = Depends(get_db),
    ) -> Any:
        item = _get(db, access, item_id)
        for key, value in body.model_dump().items():
            setattr(item, key, value)
        _log(db, access, "updated", item)
        db.commit()
        return item

    def remove(
        item_id: int,
        access: PatientAccess = Depends(requires(Permission.EDIT_PROFILE)),
        db: Session = Depends(get_db),
    ) -> None:
        item = _get(db, access, item_id)
        _log(db, access, "removed", item)
        db.delete(item)
        db.commit()

    # The body model differs per table; with postponed annotations FastAPI would look the
    # name up in module globals, so bind the concrete class before registering the route.
    for fn in (create, update):
        fn.__annotations__["body"] = schema_in
    router.post(
        f"/{{patient_id}}/{path}",
        response_model=schema_out,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{path}",
    )(create)
    router.put(
        f"/{{patient_id}}/{path}/{{item_id}}", response_model=schema_out, name=f"update_{path}"
    )(update)
    router.delete(
        f"/{{patient_id}}/{path}/{{item_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{path}",
    )(remove)


_crud("allergies", Allergy, AllergyIn, AllergyOut, "substance", "allergy")
_crud("history", HistoryEntry, HistoryIn, HistoryOut, "title", "history entry")
_crud("contacts", EmergencyContact, ContactIn, ContactOut, "name", "emergency contact")
_crud("doctors", Doctor, DoctorIn, DoctorOut, "name", "doctor")


class EmergencyOut(BaseModel):
    contacts: list[ContactOut]
    primary_doctor: DoctorOut | None


@router.get("/{patient_id}/emergency", response_model=EmergencyOut)
def emergency_info(
    access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> EmergencyOut:
    """Emergency contacts are available to every active member of the care circle."""
    pid = access.patient.id
    contacts = db.scalars(
        select(EmergencyContact)
        .where(EmergencyContact.patient_id == pid)
        .order_by(EmergencyContact.priority)
    ).all()
    doctor = db.scalar(
        select(Doctor).where(Doctor.patient_id == pid).order_by(Doctor.is_primary.desc()).limit(1)
    )
    return EmergencyOut(
        contacts=[ContactOut.model_validate(c) for c in contacts],
        primary_doctor=DoctorOut.model_validate(doctor) if doctor else None,
    )

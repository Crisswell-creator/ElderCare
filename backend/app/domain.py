"""Domain vocabulary shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ELDER = "elder"
    FAMILY = "family"
    CAREGIVER = "caregiver"


class Permission(StrEnum):
    VIEW_PROFILE = "view_profile"
    EDIT_PROFILE = "edit_profile"
    VIEW_MEDICATIONS = "view_medications"
    MANAGE_MEDICATIONS = "manage_medications"
    CONFIRM_DOSES = "confirm_doses"
    VIEW_APPOINTMENTS = "view_appointments"
    MANAGE_APPOINTMENTS = "manage_appointments"
    VIEW_DOCUMENTS = "view_documents"
    UPLOAD_DOCUMENTS = "upload_documents"
    VIEW_ADHERENCE = "view_adherence"
    VIEW_ACTIVITY = "view_activity"
    MANAGE_CARE_TEAM = "manage_care_team"
    MANAGE_TASKS = "manage_tasks"
    USE_ASSISTANT = "use_assistant"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# Permissions that only make sense together: managing implies viewing.
IMPLIED: dict[Permission, Permission] = {
    Permission.EDIT_PROFILE: Permission.VIEW_PROFILE,
    Permission.MANAGE_MEDICATIONS: Permission.VIEW_MEDICATIONS,
    Permission.CONFIRM_DOSES: Permission.VIEW_MEDICATIONS,
    Permission.MANAGE_APPOINTMENTS: Permission.VIEW_APPOINTMENTS,
    Permission.UPLOAD_DOCUMENTS: Permission.VIEW_DOCUMENTS,
}

# Suggestions shown to the elder when approving a request. They are a starting point the
# elder edits, never a grant: nothing is given until the elder submits a decision.
SUGGESTED: dict[Role, list[Permission]] = {
    Role.FAMILY: [
        Permission.VIEW_PROFILE,
        Permission.VIEW_MEDICATIONS,
        Permission.VIEW_APPOINTMENTS,
        Permission.VIEW_ADHERENCE,
    ],
    Role.CAREGIVER: [
        Permission.VIEW_PROFILE,
        Permission.VIEW_MEDICATIONS,
        Permission.CONFIRM_DOSES,
        Permission.VIEW_APPOINTMENTS,
    ],
    Role.ELDER: sorted(ALL_PERMISSIONS),
}


def normalize_permissions(perms: list[Permission] | set[Permission]) -> list[Permission]:
    """Adds implied view permissions and returns a stable, de-duplicated order."""
    out = set(perms)
    for perm in list(out):
        implied = IMPLIED.get(perm)
        if implied:
            out.add(implied)
    return sorted(out)


class Severity(StrEnum):
    INFO = "info"
    REMINDER = "reminder"
    WARNING = "warning"
    CRITICAL = "critical"


SEVERITY_BY_KIND: dict[str, Severity] = {
    "dose_reminder": Severity.REMINDER,
    "appointment_reminder": Severity.REMINDER,
    "dose_escalation": Severity.WARNING,
    "low_stock": Severity.WARNING,
    "access_request": Severity.INFO,
    "access_decision": Severity.INFO,
    "task_assigned": Severity.INFO,
    "help_request": Severity.CRITICAL,
    "security": Severity.WARNING,
}


class MedicationStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISCONTINUED = "discontinued"


class ScheduleType(StrEnum):
    SCHEDULED = "scheduled"
    AS_NEEDED = "as_needed"


class DoseStatus(StrEnum):
    SCHEDULED = "scheduled"
    TAKEN = "taken"
    SKIPPED = "skipped"
    MISSED = "missed"
    UNCONFIRMED = "unconfirmed"
    CANCELLED = "cancelled"


class InventoryKind(StrEnum):
    INITIAL = "initial"
    REFILL = "refill"
    CORRECTION = "correction"
    DOSE_TAKEN = "dose_taken"
    DOSE_REVERTED = "dose_reverted"


class AppointmentStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NotificationKind(StrEnum):
    DOSE_REMINDER = "dose_reminder"
    DOSE_ESCALATION = "dose_escalation"
    APPOINTMENT_REMINDER = "appointment_reminder"
    LOW_STOCK = "low_stock"
    ACCESS_REQUEST = "access_request"
    ACCESS_DECISION = "access_decision"
    SECURITY = "security"
    TASK_ASSIGNED = "task_assigned"
    HELP_REQUEST = "help_request"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"  # accepted by the mail server; delivery to the inbox is not observable
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # recipient opted out of email; still visible in-app


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

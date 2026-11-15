"""Medical documents: validated uploads, authorised downloads, soft deletion."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.deps import PatientAccess, get_owned, requires
from app.domain import Permission
from app.errors import AppError, Forbidden, NotFound
from app.models import Document
from app.services import audit
from app.services.storage import get_storage

router = APIRouter(prefix="/api/patients/{patient_id}/documents", tags=["documents"])

Category = Literal[
    "lab_result", "prescription", "discharge_summary", "imaging", "insurance", "letter", "other"
]

# The type is decided from the file's own bytes, never from the client's claimed type.
SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
]


class DocumentOut(BaseModel):
    id: int
    title: str
    category: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: str | None
    created_at: datetime
    can_delete: bool


def _out(d: Document, access: PatientAccess) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        title=d.title,
        category=d.category,
        filename=d.filename,
        content_type=d.content_type,
        size_bytes=d.size_bytes,
        uploaded_by=d.uploaded_by.full_name if d.uploaded_by else None,
        created_at=d.created_at,
        can_delete=access.is_elder or d.uploaded_by_user_id == access.user.id,
    )


def _sniff(data: bytes) -> tuple[str, str]:
    for magic, mime, ext in SIGNATURES:
        if data.startswith(magic):
            return mime, ext
    raise AppError("Upload a PDF, PNG or JPEG file.", fields={"file": "Unsupported file type"})


def _safe_filename(name: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", name.rsplit(".", 1)[0]).strip(" ._") or "document"
    return stem[:80] + ext


@router.get("", response_model=list[DocumentOut])
def list_documents(
    access: PatientAccess = Depends(requires(Permission.VIEW_DOCUMENTS)),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    rows = db.scalars(
        select(Document)
        .where(Document.patient_id == access.patient.id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    return [_out(d, access) for d in rows]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: Annotated[str, Form(min_length=1, max_length=160)],
    category: Annotated[Category, Form()],
    file: Annotated[UploadFile, File()],
    access: PatientAccess = Depends(requires(Permission.UPLOAD_DOCUMENTS)),
    db: Session = Depends(get_db),
) -> DocumentOut:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)  # read at most one byte past the limit
    if len(data) > limit:
        raise AppError(
            f"Files must be {limit // (1024 * 1024)} MB or smaller.",
            fields={"file": "File too large"},
        )
    if not data:
        raise AppError("The file is empty.", fields={"file": "Empty file"})
    mime, ext = _sniff(data)
    key = f"patients/{access.patient.id}/{uuid.uuid4().hex}{ext}"
    get_storage().save(key, data, mime)
    doc = Document(
        patient_id=access.patient.id,
        title=title.strip(),
        category=category,
        filename=_safe_filename(file.filename or "document", ext),
        content_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        uploaded_by_user_id=access.user.id,
    )
    db.add(doc)
    db.flush()
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="document.uploaded",
        entity_type="document",
        entity_id=doc.id,
        summary=f"{access.user.full_name} uploaded “{doc.title}”",
    )
    db.commit()
    return _out(doc, access)


def _get(db: Session, access: PatientAccess, doc_id: int) -> Document:
    doc = get_owned(db, Document, doc_id, access, "document")
    if doc.deleted_at is not None:
        raise NotFound("That document was not found.")
    return doc


@router.get("/{doc_id}/download")
def download_document(
    doc_id: int,
    access: PatientAccess = Depends(requires(Permission.VIEW_DOCUMENTS)),
    db: Session = Depends(get_db),
) -> Response:
    doc = _get(db, access, doc_id)
    data = get_storage().load(doc.storage_key)
    return Response(
        data,
        media_type=doc.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: int,
    access: PatientAccess = Depends(requires(Permission.VIEW_DOCUMENTS)),
    db: Session = Depends(get_db),
) -> None:
    """Hides the document from the care circle. The stored file is retained for the record;
    permanent erasure follows the retention procedure in SECURITY.md."""
    doc = _get(db, access, doc_id)
    if not (access.is_elder or doc.uploaded_by_user_id == access.user.id):
        raise Forbidden("Only the person who uploaded this document, or the elder, can remove it.")
    doc.deleted_at = utcnow()
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="document.removed",
        entity_type="document",
        entity_id=doc.id,
        summary=f"{access.user.full_name} removed “{doc.title}”",
    )
    db.commit()

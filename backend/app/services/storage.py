"""Private document storage. Files are never served from a public URL: every download goes
through an authorised API endpoint. `local` is for development; `gcs` stores objects in a
private Google Cloud Storage bucket using the Cloud Run service account (no keys)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...
    def load(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):  # keys are server-generated; belt and braces
            raise ValueError("invalid storage key")
        return path

    def save(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002 - Storage protocol
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class GcsStorage:
    def __init__(self, bucket: str) -> None:
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)

    def save(self, key: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(key).upload_from_string(data, content_type=content_type)

    def load(self, key: str) -> bytes:
        return bytes(self.bucket.blob(key).download_as_bytes())


class DbStorage:
    """Stores bytes in PostgreSQL (document_blobs). Files are capped at MAX_UPLOAD_BYTES."""

    def save(self, key: str, data: bytes, content_type: str) -> None:
        from app.db import SessionLocal
        from app.models import DocumentBlob

        with SessionLocal() as db:
            db.add(DocumentBlob(storage_key=key, content_type=content_type, data=data))
            db.commit()

    def load(self, key: str) -> bytes:
        from app.db import SessionLocal
        from app.models import DocumentBlob

        with SessionLocal() as db:
            blob = db.get(DocumentBlob, key)
            if blob is None:
                raise FileNotFoundError(key)
            return bytes(blob.data)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "gcs":
            _storage = GcsStorage(settings.gcs_bucket)
        elif settings.storage_backend == "db":
            _storage = DbStorage()
        else:
            _storage = LocalStorage(settings.local_storage_dir)
    return _storage

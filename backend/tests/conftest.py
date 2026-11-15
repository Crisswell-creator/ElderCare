"""Test harness.

Each test gets its own SQLite database copied from a template migrated with Alembic, so
the real schema (including the audit-log triggers) is under test and no state leaks
between tests. Time is controlled with the `clock` fixture instead of sleeping.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="eldercare-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{(_TMP / 'boot.db').as_posix()}",
        "EMAIL_TRANSPORT": "memory",
        "JOB_TRIGGER_TOKEN": "test-job-token",
        "LOCAL_STORAGE_DIR": str(_TMP / "docs"),
        "FRONTEND_DIST_DIR": str(_TMP / "no-frontend"),
        "APP_BASE_URL": "http://testserver",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-123456",
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import db as app_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.email import memory_outbox  # noqa: E402

TEMPLATE = _TMP / "template.db"


def _migrate_template() -> None:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    cfg.attributes["database_url"] = f"sqlite:///{TEMPLATE.as_posix()}"
    command.upgrade(cfg, "head")


_migrate_template()


@pytest.fixture(autouse=True)
def database(tmp_path: Path) -> Iterator[None]:
    path = tmp_path / "test.db"
    shutil.copy(TEMPLATE, path)
    engine = app_db.make_engine(f"sqlite:///{path.as_posix()}")
    app_db.SessionLocal.configure(bind=engine)
    memory_outbox.messages.clear()
    memory_outbox.fail_next = 0
    yield
    engine.dispose()


@pytest.fixture
def db() -> Iterator[Session]:
    session = app_db.SessionLocal()
    yield session
    session.close()


class Clock:
    """Replaces `utcnow` in every app module so endpoints and the engine share one time."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)
        original = app_db.utcnow
        for name, module in list(sys.modules.items()):
            if name.startswith("app") and getattr(module, "utcnow", None) is original:
                monkeypatch.setattr(module, "utcnow", self)

    def __call__(self) -> datetime:
        return self.now

    def set(self, value: datetime) -> None:
        self.now = value

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return Clock(monkeypatch)


class Api:
    """A browser-like client: keeps cookies and echoes the CSRF cookie in a header."""

    def __init__(self) -> None:
        self.client = TestClient(app)
        self.client.get("/healthz")  # receive the CSRF cookie
        self.user: dict[str, Any] = {}

    def _headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.client.cookies.get("ec_csrf") or ""}

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get(url, **kw)

    def post(self, url: str, json: Any = None, **kw: Any) -> Any:
        return self.client.post(url, json=json, headers=self._headers(), **kw)

    def put(self, url: str, json: Any = None) -> Any:
        return self.client.put(url, json=json, headers=self._headers())

    def patch(self, url: str, json: Any = None) -> Any:
        return self.client.patch(url, json=json, headers=self._headers())

    def delete(self, url: str) -> Any:
        return self.client.delete(url, headers=self._headers())


def register(
    name: str,
    email: str | None = None,
    password: str = "correct horse battery",
    verify: bool = True,
    timezone: str = "Europe/London",
) -> Api:
    api = Api()
    email = email or f"{name.lower().replace(' ', '.')}@example.com"
    res = api.post(
        "/api/auth/register",
        {"email": email, "password": password, "full_name": name, "timezone": timezone},
    )
    assert res.status_code == 201, res.text
    api.user = res.json()["user"]
    if verify:
        token = latest_token(email, "verify-email")
        assert api.post("/api/auth/verify-email", {"token": token}).status_code == 200
    return api


def latest_token(email: str, path: str) -> str:
    for msg in reversed(memory_outbox.messages):
        if msg.to == email and f"/{path}?token=" in msg.text:
            match = re.search(rf"/{path}\?token=([\w-]+)", msg.text)
            assert match
            return match.group(1)
    raise AssertionError(f"no {path} email for {email}")


def create_elder(api: Api, name: str = "Margaret Ellis", tz: str = "Europe/London") -> int:
    res = api.post(
        "/api/patients",
        {"mode": "self", "full_name": name, "preferred_name": name.split()[0], "timezone": tz},
    )
    assert res.status_code == 201, res.text
    return int(res.json()["patient"]["id"])


def join(elder: Api, pid: int, member: Api, role: str, permissions: list[str]) -> int:
    """Full consent flow: invitation -> redemption -> elder approval. Returns membership id."""
    inv = elder.post(f"/api/patients/{pid}/invitations", {"intended_role": role})
    assert inv.status_code == 201, inv.text
    req = member.post(
        "/api/invitations/redeem", {"code": inv.json()["code"], "relationship_label": "Family"}
    )
    assert req.status_code == 201, req.text
    dec = elder.post(
        f"/api/patients/{pid}/access-requests/{req.json()['id']}/decision",
        {"decision": "approve", "permissions": permissions},
    )
    assert dec.status_code == 200, dec.text
    members = elder.get(f"/api/patients/{pid}/members").json()
    return next(m["id"] for m in members if m["user_id"] == member.user["id"])


@dataclass
class Circle:
    pid: int
    elder: Api
    family: Api
    carer: Api


@pytest.fixture
def circle() -> Circle:
    elder = register("Margaret Ellis")
    pid = create_elder(elder)
    family = register("Daniel Ellis")
    carer = register("Priya Shah")
    join(
        elder,
        pid,
        family,
        "family",
        [
            "view_profile",
            "view_medications",
            "view_appointments",
            "manage_appointments",
            "view_adherence",
            "view_activity",
        ],
    )
    join(
        elder,
        pid,
        carer,
        "caregiver",
        ["view_profile", "view_medications", "confirm_doses", "view_appointments"],
    )
    return Circle(pid, elder, family, carer)


def add_med(api: Api, pid: int, times: list[str], **extra: Any) -> dict[str, Any]:
    body = {
        "name": "Metformin",
        "strength": "500 mg",
        "dose_amount": 1,
        "dose_unit": "tablet",
        "instructions": "Take with food",
        "start_date": "2020-01-01",
        "times": [{"local_time": t} for t in times],
        **extra,
    }
    res = api.post(f"/api/patients/{pid}/medications", body)
    assert res.status_code == 201, res.text
    return dict(res.json())

from __future__ import annotations

from sqlalchemy import select

from app.models import User
from app.services.email import memory_outbox
from tests.conftest import Api, latest_token, register


def test_register_sets_httponly_session_and_hashes_password(db):
    api = Api()
    res = api.post(
        "/api/auth/register",
        {"email": "Ann@Example.com", "password": "a long pass phrase", "full_name": "Ann"},
    )
    assert res.status_code == 201
    assert res.json()["user"]["email"] == "ann@example.com"
    cookie = res.headers["set-cookie"]
    assert "ec_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    user = db.scalar(select(User).where(User.email == "ann@example.com"))
    assert user.password_hash.startswith("$argon2id$")
    assert "a long pass phrase" not in user.password_hash
    assert api.get("/api/auth/session").json()["user"]["full_name"] == "Ann"


def test_registration_validation_and_duplicates():
    api = Api()
    weak = api.post(
        "/api/auth/register", {"email": "b@example.com", "password": "short", "full_name": "B"}
    )
    assert weak.status_code == 422 and "password" in weak.json()["error"]["fields"]
    common = api.post(
        "/api/auth/register",
        {"email": "b@example.com", "password": "password123", "full_name": "B"},
    )
    assert common.status_code == 422
    bad_tz = api.post(
        "/api/auth/register",
        {
            "email": "b@example.com",
            "password": "fine pass phrase",
            "full_name": "B",
            "timezone": "Mars/Base",
        },
    )
    assert bad_tz.status_code == 422
    register("Bea", email="bea@example.com")
    dup = Api().post(
        "/api/auth/register",
        {"email": "BEA@example.com", "password": "another pass phrase", "full_name": "Bea 2"},
    )
    assert dup.status_code == 409


def test_login_logout_and_generic_error():
    register("Carl", email="carl@example.com", password="carl pass phrase")
    api = Api()
    wrong = api.post("/api/auth/login", {"email": "carl@example.com", "password": "nope nope 1"})
    unknown = api.post("/api/auth/login", {"email": "nobody@example.com", "password": "x" * 10})
    # Same status and message whether or not the account exists (no account discovery).
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    ok = api.post("/api/auth/login", {"email": "carl@example.com", "password": "carl pass phrase"})
    assert ok.status_code == 200
    assert api.get("/api/auth/memberships").status_code == 200
    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/auth/memberships").status_code == 401


def test_login_throttling_blocks_after_limit_but_allows_within_it():
    register("Dee", email="dee@example.com", password="dee pass phrase")
    api = Api()
    for _ in range(4):
        assert (
            api.post(
                "/api/auth/login", {"email": "dee@example.com", "password": "bad guess 12"}
            ).status_code
            == 401
        )
    # 4 failures: still allowed, and a correct login succeeds and clears the streak
    assert (
        api.post(
            "/api/auth/login", {"email": "dee@example.com", "password": "dee pass phrase"}
        ).status_code
        == 200
    )
    for _ in range(5):
        api.post("/api/auth/login", {"email": "dee@example.com", "password": "bad guess 12"})
    blocked = api.post(
        "/api/auth/login", {"email": "dee@example.com", "password": "dee pass phrase"}
    )
    assert blocked.status_code == 429  # even the right password is refused while locked


def test_csrf_header_required_for_state_changes():
    api = register("Eve")
    no_header = api.client.patch("/api/auth/me", json={"full_name": "Mallory"})
    assert no_header.status_code == 403
    assert no_header.json()["error"]["code"] == "csrf_failed"
    with_header = api.patch("/api/auth/me", {"full_name": "Eve Adams"})
    assert with_header.status_code == 200 and with_header.json()["full_name"] == "Eve Adams"


def test_email_verification_token_is_single_use():
    api = register("Finn", email="finn@example.com", verify=False)
    assert api.user["email_verified"] is False
    token = latest_token("finn@example.com", "verify-email")
    assert api.post("/api/auth/verify-email", {"token": token}).json()["email_verified"] is True
    assert api.post("/api/auth/verify-email", {"token": token}).status_code == 400


def test_password_reset_flow_revokes_sessions_and_is_not_enumerable():
    old = register("Gail", email="gail@example.com", password="gail pass phrase")
    anon = Api()
    a = anon.post("/api/auth/forgot-password", {"email": "gail@example.com"})
    b = anon.post("/api/auth/forgot-password", {"email": "ghost@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert not any(m.to == "ghost@example.com" for m in memory_outbox.messages)
    token = latest_token("gail@example.com", "reset-password")
    assert (
        anon.post(
            "/api/auth/reset-password", {"token": token, "password": "brand new phrase"}
        ).status_code
        == 204
    )
    # the old session was revoked; the old password no longer works; the token is spent
    assert old.get("/api/auth/memberships").status_code == 401
    assert (
        anon.post(
            "/api/auth/login", {"email": "gail@example.com", "password": "gail pass phrase"}
        ).status_code
        == 401
    )
    assert (
        anon.post(
            "/api/auth/login", {"email": "gail@example.com", "password": "brand new phrase"}
        ).status_code
        == 200
    )
    assert (
        anon.post(
            "/api/auth/reset-password", {"token": token, "password": "another phrase 9"}
        ).status_code
        == 400
    )
    assert any("password was changed" in m.subject for m in memory_outbox.messages)


def test_change_password_requires_current_and_keeps_this_session():
    api = register("Hal", email="hal@example.com", password="hal pass phrase")
    other = Api()
    other.post("/api/auth/login", {"email": "hal@example.com", "password": "hal pass phrase"})
    bad = api.post(
        "/api/auth/change-password",
        {"current_password": "wrong one", "new_password": "new hal phrase"},
    )
    assert bad.status_code == 400
    ok = api.post(
        "/api/auth/change-password",
        {"current_password": "hal pass phrase", "new_password": "new hal phrase"},
    )
    assert ok.status_code == 204
    assert api.get("/api/auth/memberships").status_code == 200
    assert other.get("/api/auth/memberships").status_code == 401


def test_session_endpoint_never_401s_and_profile_updates_validate():
    assert Api().get("/api/auth/session").json() == {"user": None}
    api = register("Ida")
    assert api.patch("/api/auth/me", {"text_scale": "huge"}).status_code == 422
    assert api.patch("/api/auth/me", {"text_scale": "xlarge"}).json()["text_scale"] == "xlarge"


def test_sign_in_hint_cookie_is_set_on_login_and_cleared_on_logout():
    register("Hint User", email="hint@example.com", password="hint pass phrase")
    api = Api()
    res = api.post("/api/auth/login", {"email": "hint@example.com", "password": "hint pass phrase"})
    hint = [c for c in res.headers.get_list("set-cookie") if c.startswith("ec_hint=")]
    assert hint and "HttpOnly" not in hint[0]  # readable by the SPA, holds no secret
    out = api.post("/api/auth/logout")
    assert any(
        c.startswith("ec_hint=") and "Max-Age=0" in c for c in out.headers.get_list("set-cookie")
    )
    # the hint alone grants nothing
    stranger = Api()
    stranger.client.cookies.set("ec_hint", "1")
    assert stranger.get("/api/auth/memberships").status_code == 401

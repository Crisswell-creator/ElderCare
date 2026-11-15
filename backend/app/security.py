"""Password hashing and token primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()  # argon2id with the library's OWASP-aligned defaults

# A real hash of a random string: verifying against it when the email is unknown keeps
# login timing the same for existing and non-existing accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

# Unambiguous alphabet (no 0/O, 1/I/L) so codes can be read aloud over the phone.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Keyed hash for storing bearer secrets (session tokens, invitation codes)."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def new_invitation_code() -> str:
    """10 characters from a 31-symbol alphabet (~49 bits), shown as XXXXX-XXXXX."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def normalize_invitation_code(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{raw[:5]}-{raw[5:]}" if len(raw) == 10 else raw


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

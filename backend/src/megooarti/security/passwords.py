"""Password hashing (Argon2id) and password rules.

hash_password and verify_password are CPU-bound: call them with asyncio.to_thread.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 8
MAX_LENGTH = 256

_hasher = PasswordHasher()
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Check a password. A missing hash costs the same time as a wrong password,
    so response time does not reveal whether an account exists."""
    global _dummy_hash
    if password_hash is None:
        if _dummy_hash is None:
            _dummy_hash = _hasher.hash("megooarti-no-such-account")
        candidate = _dummy_hash
    else:
        candidate = password_hash
    try:
        matched = _hasher.verify(candidate, password)
    except (VerificationError, InvalidHashError):
        return False
    return matched and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str, username: str) -> str | None:
    """Why this password is not acceptable, or None if it is."""
    if len(password) < MIN_LENGTH:
        return f"The password must be at least {MIN_LENGTH} characters long."
    if len(password) > MAX_LENGTH:
        return f"The password must be at most {MAX_LENGTH} characters long."
    if password.lower() == username.lower():
        return "The password must not be the same as the username."
    return None

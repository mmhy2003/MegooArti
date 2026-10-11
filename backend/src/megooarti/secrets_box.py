"""Sealing of secrets MegooArti must be able to read back, such as remote passwords.

The key is MEGOOARTI_SECRET_KEY when set. Otherwise one is generated into the data
directory on first use. Losing the key makes sealed secrets unreadable.
"""

import base64
import hashlib
import os
import uuid
from contextlib import suppress
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from megooarti.config import Settings

_MARK = "enc:v1:"
_KEY_FILE = "secret.key"


class Sealed(str):
    """Text produced by `seal`. Code that stores a secret accepts only this type."""


class SecretUnreadable(Exception):
    """The stored value was not sealed with the current key."""


def _generated_key(path: Path) -> bytes:
    """The key in the data directory, created on first use.

    It is written to a temporary file and then linked into place, which either creates
    the complete file or fails because another container got there first. The key file
    is therefore never seen half-written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(Fernet.generate_key())
            with suppress(FileExistsError):
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    key = path.read_bytes().strip()
    try:
        Fernet(key)
    except ValueError:
        raise SecretUnreadable(
            f"{path} is empty or damaged. Restore it from a backup, or delete it and "
            "enter the stored secrets again."
        ) from None
    return key


@lru_cache(maxsize=8)
def _fernet(secret_key: str | None, data_dir: str) -> Fernet:
    if secret_key:
        # Any text is accepted as the key; hashing gives it the length Fernet needs.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))
    return Fernet(_generated_key(Path(data_dir) / _KEY_FILE))


def _box(settings: Settings) -> Fernet:
    return _fernet(settings.secret_key, str(settings.data_dir))


def seal(settings: Settings, plaintext: str) -> Sealed:
    return Sealed(_MARK + _box(settings).encrypt(plaintext.encode()).decode())


def unseal(settings: Settings, stored: str) -> str:
    if not stored.startswith(_MARK):
        raise SecretUnreadable
    try:
        return _box(settings).decrypt(stored.removeprefix(_MARK).encode()).decode()
    except InvalidToken:
        raise SecretUnreadable from None


def seal_at(settings: Settings, plaintext: str, now: datetime) -> str:
    """Seal text together with the time, for `unseal_within`. Not for stored secrets."""
    return _box(settings).encrypt_at_time(plaintext.encode(), int(now.timestamp())).decode()


def unseal_within(settings: Settings, sealed: str, seconds: int, now: datetime) -> str | None:
    """What `seal_at` sealed, if that was no more than `seconds` ago. Otherwise None."""
    try:
        opened = _box(settings).decrypt_at_time(sealed.encode(), seconds, int(now.timestamp()))
    except (InvalidToken, ValueError):  # altered, sealed with another key, or not text
        return None
    return opened.decode()


def forget_keys() -> None:
    """Drop cached keys, so the next use reads them again. For tests."""
    _fernet.cache_clear()

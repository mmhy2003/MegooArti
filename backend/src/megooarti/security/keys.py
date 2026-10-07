"""Random secrets for sessions and API tokens, and the hash they are stored as.

These secrets carry 256 bits of randomness, so a fast hash is the right choice;
slow hashing is for passwords, which people choose.
"""

import hashlib
import secrets

TOKEN_PREFIX = "mga_"


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def new_api_token() -> str:
    return TOKEN_PREFIX + new_secret()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

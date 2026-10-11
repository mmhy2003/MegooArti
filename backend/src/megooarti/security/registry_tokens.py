"""Registry tokens: what a container client is given at sign-in and sends with requests.

A registry token is not stored anywhere. It is a sealed statement of who signed in and
how, valid for a few minutes. Reading one back gives that statement and nothing more:
the caller loads the user, the roles and the API token again on every request, so a
disabled user or a revoked token is refused at once.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from megooarti import secrets_box
from megooarti.config import Settings

PREFIX = "mgr_"
LIFETIME_SECONDS = 300
# What the sealed text says it is, so that nothing else sealed with the same key can be
# taken for a registry token.
_PURPOSE = "registry"
_METHODS = ("password", "token", "anonymous")


@dataclass(frozen=True)
class Claims:
    """Who signed in. `user_id` is None when nobody did: the anonymous user is meant."""

    user_id: uuid.UUID | None
    method: str
    token_id: uuid.UUID | None = None  # the API token that was presented, if one was


def issue(settings: Settings, claims: Claims, now: datetime) -> str:
    stated = {
        "for": _PURPOSE,
        "user": None if claims.user_id is None else str(claims.user_id),
        "method": claims.method,
        "token": None if claims.token_id is None else str(claims.token_id),
    }
    return PREFIX + secrets_box.seal_at(settings, json.dumps(stated), now)


def read(settings: Settings, value: str, now: datetime) -> Claims | None:
    """What a registry token states, or None if it is not one, was altered or has expired."""
    if not value.startswith(PREFIX):
        return None
    sealed = value.removeprefix(PREFIX)
    text = secrets_box.unseal_within(settings, sealed, LIFETIME_SECONDS, now)
    if text is None:
        return None
    try:
        stated = json.loads(text)
        if stated["for"] != _PURPOSE or stated["method"] not in _METHODS:
            return None
        user, token = stated["user"], stated["token"]
        return Claims(
            user_id=None if user is None else uuid.UUID(user),
            method=stated["method"],
            token_id=None if token is None else uuid.UUID(token),
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return None

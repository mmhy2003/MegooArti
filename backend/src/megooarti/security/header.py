"""Trusted header sources (spec 8, SEC-17): a proxy in front, that signs people in itself
(an SSO gateway), says who they are in a header. Taken only from a trusted proxy (see
`megooarti.proxies`); from anywhere else, a request with the header is refused.
"""

import re
from typing import Any

from megooarti.security import sources
from megooarti.security.sources import Identity, Tested, invalid

KIND = "header"
DEFAULTS = {"user_header": "X-Forwarded-User", "groups_header": None}
# A header's name as HTTP has it (a token), and not one the server reads for itself.
_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}")
_RESERVED = {"authorization", "cookie", "host", "x-forwarded-for", "x-forwarded-proto"}
# At most this many groups are read from the groups header.
_GROUP_LIMIT = 200


def _header(value: Any, field: str, *, required: bool) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise invalid(field, "A header's name is required, as X-Forwarded-User.")
        return None
    if not _NAME.fullmatch(text) or text.lower() in _RESERVED:
        raise invalid(
            field, "A header's name, as X-Forwarded-User, and not one HTTP gives meaning."
        )
    return text


class HeaderKind(sources.Kind):
    name = KIND

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        user_header = _header(
            settings.get("user_header") or DEFAULTS["user_header"],
            "settings.user_header",
            required=True,
        )
        groups_header = _header(
            settings.get("groups_header"), "settings.groups_header", required=False
        )
        if groups_header is not None and groups_header.lower() == user_header.lower():
            raise invalid("settings.groups_header", "The groups come in a header of their own.")
        return {"user_header": user_header, "groups_header": groups_header}

    async def test(self, outbound, settings, name, password) -> Tested:
        groups = settings.get("groups_header")
        said = f"{settings['user_header']} names who is signed in"
        said += f", {groups} their groups (separated by commas)." if groups else "."
        return Tested(True, f"{said} Taken only from a trusted proxy.")


def identity(settings: dict[str, Any], headers: Any) -> Identity | None:
    """Who the headers say someone is, or None when they name nobody."""
    name = (headers.get(settings["user_header"]) or "").strip()
    if not name or len(name) > 256 or any(ord(character) < 32 for character in name):
        return None
    groups: list[str] = []
    if settings.get("groups_header"):
        said = headers.get(settings["groups_header"]) or ""
        groups = [group.strip() for group in said.split(",") if group.strip()][:_GROUP_LIMIT]
    return Identity(external_id=name, username=name, display_name=name, groups=frozenset(groups))


sources.register(HeaderKind())

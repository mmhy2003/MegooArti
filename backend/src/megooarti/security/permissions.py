"""Permission patterns.

A route requires a permission such as `admin:users:write`. A role grants patterns such
as `admin:users:*`. A pattern grants a permission when each of its segments is `*` or
equals the permission's segment at the same position; a pattern shorter than the
permission grants everything beneath it, and a longer one grants nothing.
"""

import re
from collections.abc import Iterable

FULL_ACCESS = "*"
_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")


def is_valid_pattern(pattern: str) -> bool:
    return all(part == "*" or _SEGMENT.fullmatch(part) for part in pattern.split(":"))


def is_valid_permission(permission: str) -> bool:
    return all(_SEGMENT.fullmatch(part) for part in permission.split(":"))


def grants(pattern: str, permission: str) -> bool:
    granted = pattern.split(":")
    required = permission.split(":")
    if len(granted) > len(required):
        return False
    return all(have in ("*", need) for have, need in zip(granted, required, strict=False))


def any_grants(patterns: Iterable[str], permission: str) -> bool:
    return any(grants(pattern, permission) for pattern in patterns)

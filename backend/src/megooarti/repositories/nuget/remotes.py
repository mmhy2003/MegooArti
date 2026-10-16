"""What a V3 proxy reads of its remote: the remote's service index, and its documents
with the remote's addresses made the proxy's own.

Pure functions.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# The kinds of each resource a proxy uses, the one it prefers first. A registration of
# SemVer 2.0.0 is preferred: the others leave out the versions only it can list.
_PACKAGES = ("PackageBaseAddress/3.0.0",)
_REGISTRATIONS = (
    "RegistrationsBaseUrl/3.6.0",
    "RegistrationsBaseUrl/Versioned",
    "RegistrationsBaseUrl/3.4.0",
    "RegistrationsBaseUrl/3.0.0-rc",
    "RegistrationsBaseUrl/3.0.0-beta",
    "RegistrationsBaseUrl",
)
_SEARCH = (
    "SearchQueryService/3.5.0",
    "SearchQueryService/3.0.0-rc",
    "SearchQueryService/3.0.0-beta",
    "SearchQueryService",
)
_AUTOCOMPLETE = (
    "SearchAutocompleteService/3.5.0",
    "SearchAutocompleteService/3.0.0-rc",
    "SearchAutocompleteService/3.0.0-beta",
    "SearchAutocompleteService",
)


class InvalidIndex(Exception):
    """A remote's service index that a proxy cannot use. The message says why."""


@dataclass(frozen=True)
class Resources:
    """Where a remote serves what a proxy passes on. Each address ends in a slash but
    search's and autocomplete's, which are "" where the remote has none."""

    packages: str
    registration: str
    # Every registration the remote has, of whatever kind: a search names any of them.
    registrations: tuple[str, ...]
    search: str = ""
    autocomplete: str = ""


def _slashed(address: str) -> str:
    return address if address.endswith("/") else f"{address}/"


def _first(found: dict[str, str], kinds: Sequence[str]) -> str:
    return next((found[kind] for kind in kinds if kind in found), "")


def read_index(data: bytes) -> Resources:
    """What a remote's `index.json` says. Raises InvalidIndex."""
    try:
        listed = json.loads(data)["resources"]
    except (ValueError, KeyError, TypeError):
        raise InvalidIndex("its service index is not one NuGet's clients read") from None
    found: dict[str, str] = {}
    registrations: list[str] = []
    for resource in listed if isinstance(listed, list) else []:
        if not isinstance(resource, dict):
            continue
        kind, address = resource.get("@type"), resource.get("@id")
        if not isinstance(kind, str) or not isinstance(address, str):
            continue
        found.setdefault(kind, address)
        if kind.startswith("RegistrationsBaseUrl"):
            registrations.append(_slashed(address))
    packages, registration = _first(found, _PACKAGES), _first(found, _REGISTRATIONS)
    if not packages:
        raise InvalidIndex("its service index names no PackageBaseAddress/3.0.0")
    if not registration:
        raise InvalidIndex("its service index names no RegistrationsBaseUrl")
    return Resources(
        packages=_slashed(packages),
        registration=_slashed(registration),
        registrations=tuple(dict.fromkeys(registrations)),
        search=_first(found, _SEARCH),
        autocomplete=_first(found, _AUTOCOMPLETE),
    )


def rewrite(document: Any, replacements: Sequence[tuple[str, str]]) -> Any:
    """A document with each text that begins with one of the remote's addresses begun
    with the proxy's instead: the first replacement that fits."""
    if isinstance(document, str):
        for remote, own in replacements:
            if document.startswith(remote):
                return own + document[len(remote) :]
        return document
    if isinstance(document, list):
        return [rewrite(item, replacements) for item in document]
    if isinstance(document, dict):
        return {key: rewrite(value, replacements) for key, value in document.items()}
    return document

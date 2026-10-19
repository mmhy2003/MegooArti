"""OIDC sign-in sources (spec 5): people sign in at an identity provider (Keycloak, Entra
ID, Okta, Google), which sends them back with a code; the code is traded for an ID token,
which says who they are.

Here are the kind, its settings, and the provider's side of it: its metadata and keys,
kept for an hour.
"""

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog

from megooarti.security import sources
from megooarti.security.sources import Outbound, SourceUnavailable, Tested, invalid

log = structlog.get_logger(__name__)

KIND = "oidc"
# How long a provider's metadata and keys are kept before they are asked for again.
KEPT_SECONDS = 3600
# How far a provider's clock may be from ours (spec 5).
SKEW_SECONDS = 300
# What an ID token may be signed with: never `none`, nor a secret shared with us (HS*).
ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)
DEFAULT_SCOPES = ["openid", "profile", "email"]
CLAIMS = {
    "username_claim": "preferred_username",
    "name_claim": "name",
    "email_claim": "email",
    "groups_claim": "groups",
}
# A scope as RFC 6749 3.3 has it; a claim's name as JSON keys go, without anything odd.
_SCOPE = re.compile(r"[\x21\x23-\x5b\x5d-\x7e]{1,128}")
_CLAIM = re.compile(r"[A-Za-z0-9_.:/-]{1,128}")


@dataclass(frozen=True)
class Provider:
    """What a provider's metadata says, as far as sign-in needs it."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    algorithms: frozenset[str]
    auth_methods: frozenset[str]


# url -> (when it was fetched, what it was): metadata and keys alike.
_kept: dict[str, tuple[float, Any]] = {}


def forget() -> None:
    """Forget every provider's metadata and keys (for the tests)."""
    _kept.clear()


def _url(value: Any, field: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise invalid(field, "Must be an http or https address.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise invalid(field, "Must have no user name, password, query or fragment.")
    return text


class OidcKind(sources.Kind):
    name = KIND
    secrets = ("client_secret",)
    # The secret is sent to the issuer's token endpoint: to another issuer, it is asked again.
    bound = ("issuer", "client_id")
    in_browser = True

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        client_id = str(settings.get("client_id") or "").strip()
        if not 1 <= len(client_id) <= 255:
            raise invalid("settings.client_id", "The client ID the provider gave is required.")
        scopes = settings.get("scopes", DEFAULT_SCOPES)
        if isinstance(scopes, str):
            scopes = scopes.split()
        if not isinstance(scopes, list) or not all(
            isinstance(scope, str) and _SCOPE.fullmatch(scope) for scope in scopes
        ):
            raise invalid("settings.scopes", "Scopes are words without spaces or quotes.")
        values: dict[str, Any] = {
            "issuer": _url(settings.get("issuer"), "settings.issuer"),
            "client_id": client_id,
            "client_secret": settings.get("client_secret") or None,
            # openid first, as every provider wants it, and each once.
            "scopes": list(dict.fromkeys(["openid", *scopes])),
            "require_verified_email": bool(settings.get("require_verified_email", False)),
        }
        for name, default in CLAIMS.items():
            claim = str(settings.get(name) or default).strip()
            if not _CLAIM.fullmatch(claim):
                raise invalid(f"settings.{name}", "A claim's name is letters, digits and . _ : / -")
            values[name] = claim
        return values

    async def test(self, outbound, settings, name, password) -> Tested:
        provider = await discover(outbound, settings["issuer"], fresh=True)
        keys = await _keys(outbound, provider, fresh=True)
        signs = ", ".join(sorted(provider.algorithms & ALGORITHMS)) or "nothing this server takes"
        found = len(keys.get("keys", []))
        return Tested(True, f"{provider.issuer} answered. It signs with {signs}; {found} keys.")

    def callback_path(self, source_id: uuid.UUID) -> str:
        return f"/api/v1/auth/oidc/{source_id}/callback"


# --- The provider -----------------------------------------------------------------------


async def _get_json(outbound: Outbound, url: str, fresh: bool) -> Any:
    kept = _kept.get(url)
    if kept is not None and not fresh and time.monotonic() - kept[0] < KEPT_SECONDS:
        return kept[1]
    try:
        response = await outbound.http.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        raise SourceUnavailable(f"{url} could not be reached: {type(error).__name__}.") from None
    if response.status_code != 200:
        raise SourceUnavailable(f"{url} answered {response.status_code}.")
    try:
        value = response.json()
    except ValueError:
        raise SourceUnavailable(f"{url} did not answer JSON.") from None
    if not isinstance(value, dict):
        raise SourceUnavailable(f"{url} did not answer a JSON object.")
    _kept[url] = (time.monotonic(), value)
    return value


async def discover(outbound: Outbound, issuer: str, *, fresh: bool = False) -> Provider:
    """The provider's metadata, from `<issuer>/.well-known/openid-configuration`."""
    said = await _get_json(outbound, f"{issuer}/.well-known/openid-configuration", fresh)
    # The metadata must name the very issuer it was asked of (OpenID Discovery 4.3).
    if said.get("issuer") != issuer:
        raise SourceUnavailable(f"The provider calls itself {said.get('issuer')!r}, not {issuer}.")
    endpoints = {}
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = said.get(name)
        if not isinstance(value, str) or urlsplit(value).scheme not in ("http", "https"):
            raise SourceUnavailable(f"The provider's metadata has no {name}.")
        endpoints[name] = value
    return Provider(
        issuer=issuer,
        **endpoints,
        algorithms=frozenset(said.get("id_token_signing_alg_values_supported") or ["RS256"]),
        auth_methods=frozenset(
            said.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        ),
    )


async def _keys(outbound: Outbound, provider: Provider, *, fresh: bool = False) -> dict:
    keys = await _get_json(outbound, provider.jwks_uri, fresh)
    if not isinstance(keys.get("keys"), list):
        raise SourceUnavailable("The provider's keys are not a JSON Web Key Set.")
    return keys


sources.register(OidcKind())

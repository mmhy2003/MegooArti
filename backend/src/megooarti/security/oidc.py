"""OIDC sign-in sources (spec 5): people sign in at an identity provider (Keycloak, Entra
ID, Okta, Google), which sends them back with a code; the code is traded for an ID token,
which says who they are.

Here are the kind, its settings, and the provider's side of it: its metadata and keys,
kept for an hour, the token request, and the checks of an ID token. The routes a browser
goes through are in `security/api/oidc.py`.
"""

import base64
import hashlib
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
import jwt
import structlog

from megooarti.security import sources
from megooarti.security.sources import Identity, Outbound, SourceUnavailable, Tested, invalid

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
# How long the provider is given: a person is waiting on the other side.
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# A scope as RFC 6749 3.3 has it; a claim's name as JSON keys go, without anything odd.
_SCOPE = re.compile(r"[\x21\x23-\x5b\x5d-\x7e]{1,128}")
_CLAIM = re.compile(r"[A-Za-z0-9_.:/-]{1,128}")


class NotChecked(Exception):
    """What a provider answered does not check: said on the sign-in screen, and logged."""


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
    # Kept as it is given: an issuer is compared with what the provider calls itself.
    text = str(value or "").strip()
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
        response = await outbound.http.get(
            url, headers={"Accept": "application/json"}, timeout=TIMEOUT
        )
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
    address = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    said = await _get_json(outbound, address, fresh)
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
        algorithms=_names(said, "id_token_signing_alg_values_supported", "RS256"),
        auth_methods=_names(said, "token_endpoint_auth_methods_supported", "client_secret_basic"),
    )


def _names(said: dict, name: str, otherwise: str) -> frozenset[str]:
    """A list of names in the metadata, or what it means when there is none."""
    value = said.get(name)
    if value is None:
        return frozenset({otherwise})
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SourceUnavailable(f"The provider's metadata gives {name} as no list of names.")
    return frozenset(value)


async def _keys(outbound: Outbound, provider: Provider, *, fresh: bool = False) -> dict:
    keys = await _get_json(outbound, provider.jwks_uri, fresh)
    if not isinstance(keys.get("keys"), list):
        raise SourceUnavailable("The provider's keys are not a JSON Web Key Set.")
    return keys


# --- One sign-in --------------------------------------------------------------------------


@dataclass(frozen=True)
class Started:
    """What one sign-in keeps until the provider sends the person back."""

    state: str
    nonce: str
    verifier: str

    @classmethod
    def new(cls) -> "Started":
        return cls(secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48))

    @property
    def challenge(self) -> str:
        digest = hashlib.sha256(self.verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorization_address(
    provider: Provider, settings: dict[str, Any], started: Started, redirect_uri: str
) -> str:
    """Where the browser is sent to sign in: the code flow, with PKCE (S256)."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings["client_id"],
            "redirect_uri": redirect_uri,
            "scope": " ".join(settings["scopes"]),
            "state": started.state,
            "nonce": started.nonce,
            "code_challenge": started.challenge,
            "code_challenge_method": "S256",
        }
    )
    joiner = "&" if "?" in provider.authorization_endpoint else "?"
    return f"{provider.authorization_endpoint}{joiner}{query}"


async def exchange(
    outbound: Outbound,
    provider: Provider,
    settings: dict[str, Any],
    code: str,
    verifier: str,
    redirect_uri: str,
) -> str:
    """Trade the code for tokens at the token endpoint; the ID token."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    auth = None
    secret = settings.get("client_secret")
    if secret and "client_secret_basic" in provider.auth_methods:
        # Each form-encoded first (RFC 6749 2.3.1): a secret may hold a colon.
        auth = httpx.BasicAuth(quote(settings["client_id"], safe=""), quote(secret, safe=""))
    elif secret:
        form |= {"client_id": settings["client_id"], "client_secret": secret}
    else:
        form["client_id"] = settings["client_id"]  # a public client: PKCE alone
    try:
        response = await outbound.http.post(
            provider.token_endpoint, data=form, auth=auth, timeout=TIMEOUT
        )
    except httpx.HTTPError as error:
        raise SourceUnavailable(
            f"The token endpoint could not be reached: {type(error).__name__}."
        ) from None
    try:
        said = response.json()
    except ValueError:
        said = {}
    if response.status_code != 200:
        error = said.get("error") if isinstance(said, dict) else None
        raise NotChecked(f"The token endpoint answered {response.status_code} ({error}).")
    token = said.get("id_token") if isinstance(said, dict) else None
    if not isinstance(token, str):
        raise NotChecked("The token endpoint gave no ID token.")
    return token


def _key(keys: dict, kid: str | None, algorithm: str) -> jwt.PyJWK | None:
    usable = [
        key
        for key in keys.get("keys", [])
        if isinstance(key, dict)
        and key.get("use", "sig") == "sig"
        and (kid is None or key.get("kid") == kid)
    ]
    if len(usable) != 1:
        return None
    try:
        return jwt.PyJWK(usable[0], algorithm=algorithm)
    except jwt.PyJWTError:
        return None


async def verify(
    outbound: Outbound,
    provider: Provider,
    settings: dict[str, Any],
    token: str,
    nonce: str,
) -> dict[str, Any]:
    """The claims of an ID token, if it checks: signed by the provider's keys, for this
    client, from this issuer, not expired, and of this sign-in (its nonce). Else NotChecked."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise NotChecked("The ID token is not a JWT.") from None
    algorithm, kid = header.get("alg"), header.get("kid")
    if algorithm not in ALGORITHMS or algorithm not in provider.algorithms:
        raise NotChecked(f"The ID token is signed with {algorithm!r}, which is not taken.")
    key = _key(await _keys(outbound, provider), kid, algorithm)
    if key is None:  # a key the provider has since rolled over to
        key = _key(await _keys(outbound, provider, fresh=True), kid, algorithm)
    if key is None:
        raise NotChecked(f"No key of the provider's signs this ID token (kid {kid!r}).")
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=settings["client_id"],
            issuer=provider.issuer,
            leeway=SKEW_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise NotChecked(f"The ID token does not check: {error}.") from None
    if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(
        claims["nonce"].encode(), nonce.encode()
    ):
        raise NotChecked("The ID token is not of this sign-in (its nonce).")
    audience = claims["aud"]
    if (
        isinstance(audience, list)
        and len(audience) > 1
        and claims.get("azp") != settings["client_id"]
    ):
        raise NotChecked("The ID token was given to another client (azp).")
    return claims


class Refused(Exception):
    """The provider signed someone in whom this source does not let in."""


def identity(claims: dict[str, Any], settings: dict[str, Any]) -> Identity:
    """Who an ID token says someone is, by the claims the source names."""

    def text(name: str) -> str | None:
        value = claims.get(settings[name])
        return value.strip() if isinstance(value, str) and value.strip() else None

    subject = str(claims["sub"])
    email = text("email_claim")
    if settings["require_verified_email"] and (
        email is None or claims.get("email_verified") is not True
    ):
        raise Refused("The provider has not verified this person's email.")
    username = text("username_claim") or email or subject
    groups = claims.get(settings["groups_claim"])
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(groups, list):
        groups = []
    return Identity(
        external_id=subject,
        username=username,
        display_name=text("name_claim") or username,
        email=email,
        groups=frozenset(group for group in groups if isinstance(group, str) and group),
    )


sources.register(OidcKind())

"""Who is making this request, and are they allowed to do this?"""

import asyncio
import base64
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlsplit

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.security import (
    header,
    oauth,
    registry_tokens,
    sessions,
    sources,
    throttle,
    tokens,
    users,
)
from megooarti.security.keys import TOKEN_PREFIX
from megooarti.security.models import ApiToken, User, UserSession
from megooarti.security.passwords import hash_password, needs_rehash, verify_password
from megooarti.security.permissions import any_grants, is_valid_permission
from megooarti.system import audit
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

SESSION_COOKIE = "megooarti_session"
CSRF_HEADER = "X-CSRF-Token"
# Where NuGet's clients send an API key: taken as an API token, by the content route only.
API_KEY_HEADER = "X-NuGet-ApiKey"
INVALID_CREDENTIALS = "Invalid credentials."
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# "header": a trusted proxy said who it is (spec 8), as a session does for a browser.
Method = Literal["session", "password", "token", "anonymous", "header"]
Scheme = Literal["Bearer", "Basic"]


@dataclass(frozen=True)
class Principal:
    """The identity a request acts as."""

    user: User
    method: Method
    patterns: frozenset[str]
    scopes: frozenset[str] | None = None
    session: UserSession | None = None
    # What anyone may do without credentials: the anonymous user's patterns while
    # anonymous access is on. Only ever applied to repository permissions.
    public: frozenset[str] = frozenset()
    # The API token the caller presented, if any: what a registry token is issued for.
    token_id: uuid.UUID | None = None
    # The OAuth approval the caller's access token stands for, if it held one (MCP 7).
    grant_id: uuid.UUID | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.method == "anonymous"

    @property
    def is_interactive(self) -> bool:
        """Signed in as a person (cookie, password, or a trusted proxy's header), not
        with an API token."""
        return self.method in ("session", "password", "header")

    def allows(self, permission: str) -> bool:
        if not is_valid_permission(permission):
            return False  # fail closed on anything that could shift segments
        if permission.startswith("repository:") and any_grants(self.public, permission):
            return True  # public content is public to everyone, whatever a token's scopes
        if self.is_anonymous:
            return False  # whatever roles anonymous holds, nobody administers anonymously
        if not any_grants(self.patterns, permission):
            return False
        return self.scopes is None or any_grants(self.scopes, permission)


def unauthorized(
    message: str = "Authentication is required.", *, scheme: Scheme = "Bearer"
) -> ApiError:
    challenge = {"WWW-Authenticate": f'{scheme} realm="MegooArti"'}
    return ApiError(401, "unauthorized", message, headers=challenge)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _anonymous_access(db: AsyncSession) -> tuple[User, frozenset[str]] | None:
    """The anonymous user and its patterns while anonymous access is on, else None."""
    if not (await get_setting(db, "anonymous_access"))["enabled"]:
        return None
    anonymous = await users.get_user_by_username(db, "anonymous")
    if anonymous is None or anonymous.status != "active":
        return None
    return anonymous, await users.user_patterns(db, anonymous)


async def build_principal(
    db: AsyncSession,
    user: User,
    method: Method,
    *,
    token: ApiToken | None = None,
    session: UserSession | None = None,
) -> Principal:
    """The principal for an identified user."""
    anonymous = await _anonymous_access(db)
    public = frozenset() if anonymous is None else anonymous[1]
    scopes = None if token is None or token.scopes is None else frozenset(token.scopes)
    return Principal(
        user,
        method,
        await users.signed_in_patterns(db, user),
        scopes,
        session,
        public,
        None if token is None else token.id,
    )


async def _checked[T](
    db: AsyncSession,
    request: Request,
    username: str | None,
    attempt: Callable[[], Awaitable[T | None]],
) -> T:
    """Run one credential check under the failed-sign-in limits."""
    settings = request.app.state.settings
    now = utcnow()
    subjects = throttle.subjects(username, client_ip(request))
    standing = await throttle.standing(
        db,
        subjects,
        now=now,
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_failure_window_seconds,
    )
    if standing.blocked_for:
        audit.record(db, "sign_in.throttled", None if username is None else ("user", username))
        await db.commit()  # the record must outlive this refused request
        log.warning("login_throttled", username=username, ip=client_ip(request))
        raise ApiError(
            429,
            "too_many_attempts",
            "Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(standing.blocked_for)},
        )

    result = await attempt()
    if result is None:
        await throttle.record_failure(
            db, subjects, now=now, window_seconds=settings.login_failure_window_seconds
        )
        audit.record(db, "sign_in.failed", None if username is None else ("user", username))
        await db.commit()  # the count, and the record, must outlive this failed request
        log.info("login_failed", username=username, ip=client_ip(request))
        raise unauthorized(INVALID_CREDENTIALS)
    if standing.has_failures:
        await throttle.clear(db, subjects)
    return result


async def _no_match() -> None:
    """A credential check that has already failed."""
    return None


async def authenticate_password(
    db: AsyncSession, request: Request, username: str, password: str
) -> User:
    """The active user with this username and password, or a 401 / 429 error."""
    username = users.normalise_username(username)
    if "\x00" in username:
        # PostgreSQL cannot store or compare this character, so it is never an account.
        return await _checked(db, request, None, _no_match)
    if users.looks_like_token(username):
        # A token where the name belongs. It is nobody's name, and it is a secret: the
        # failure is counted against the address only, and the name is not logged.
        return await _checked(db, request, None, _no_match)

    async def attempt() -> User | None:
        user = await users.get_user_by_username(db, username)
        if user is None or users.is_external(user):
            # A name nobody has here, or a user of a source: the sources decide (E3).
            found = await sources.password_sign_in(
                db,
                request.app.state.settings,
                sources.outbound(request.app),
                username,
                password,
                user,
            )
            if found is None and user is None:
                # As long as a wrong password of somebody's takes.
                await asyncio.to_thread(verify_password, None, password)
            return found if found is not None and await users.can_act(db, found) else None
        matched = await asyncio.to_thread(verify_password, user.password_hash, password)
        if not matched or not await users.can_act(db, user):
            return None
        if user.password_hash is not None and needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)
        return user

    return await _checked(db, request, username, attempt)


async def _authenticate_token(
    db: AsyncSession, request: Request, value: str, username: str | None = None
) -> tuple[User, ApiToken]:
    async def attempt() -> tuple[User, ApiToken] | None:
        now = utcnow()
        token = await tokens.find_token(db, value, now)
        if token is None:
            return None
        user = await users.get_user(db, token.user_id)
        if user is None or not await users.can_act(db, user):
            return None
        if username is not None and user.username != users.normalise_username(username):
            return None
        tokens.touch(token, now)
        return user, token

    # A valid token is accepted even from a blocked address. These secrets carry 256 bits
    # of randomness, so limiting guesses protects nothing, while refusing valid ones
    # would let anyone at a shared address stop every pipeline behind it.
    found = await attempt()
    if found is not None:
        return found
    # Count the failure against the address (never a username) and raise 401 or 429.
    return await _checked(db, request, None, _no_match)


async def authenticate_secret(
    db: AsyncSession, request: Request, username: str, secret: str
) -> tuple[User, ApiToken | None]:
    """The user with this name whose password, or one of whose API tokens, is `secret`.

    Returns the token too when the secret was one. Raises 401 or 429. HTTP Basic
    credentials are checked here, and so is anything else that takes a name and a
    secret, so that the limits on failed attempts are the same everywhere.

    The name `__token__` is nobody's, and nor is no name at all: with either, the token
    alone says who is asking.
    """
    # No name says the same, as dotnet-symbol and Azure DevOps's clients send a token.
    if users.normalise_username(username) in ("", users.TOKEN_USERNAME):
        if secret.startswith(TOKEN_PREFIX):
            return await _authenticate_token(db, request, secret)
        # Not a token at all. A failed attempt, counted against the address.
        return await _checked(db, request, None, _no_match)
    if secret.startswith(TOKEN_PREFIX):
        return await _authenticate_token(db, request, secret, username)
    return await authenticate_password(db, request, username, secret), None


def _decode_basic(credentials: str) -> tuple[str, str]:
    try:
        decoded = base64.b64decode(credentials.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise unauthorized("The Authorization header is malformed.") from None
    username, separator, secret = decoded.partition(":")
    if not separator:
        raise unauthorized("The Authorization header is malformed.")
    return username, secret


async def _from_header(
    db: AsyncSession, request: Request, header: str, *, registry: bool = False
) -> Principal:
    scheme, _, credentials = header.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer" and credentials.strip().startswith(registry_tokens.PREFIX):
        if not registry:
            # It stands for a password for five minutes. Anywhere else it could be used
            # to outlast them: to make an API token, or to change the password.
            raise unauthorized("A registry token is taken by the registry API only.")
        return await _from_registry_token(db, request, credentials.strip())
    if scheme == "bearer":
        user, token = await _authenticate_token(db, request, credentials.strip())
        return await build_principal(db, user, "token", token=token)
    if scheme == "basic":
        username, secret = _decode_basic(credentials)
        user, token = await authenticate_secret(db, request, username, secret)
        method = "password" if token is None else "token"
        return await build_principal(db, user, method, token=token)
    raise unauthorized("The Authorization scheme is not supported.")


async def _from_registry_token(db: AsyncSession, request: Request, value: str) -> Principal:
    """Who a registry token stands for, as things are now.

    The token only says who signed in. The user, the roles and the API token are read
    again here, so one that was disabled or revoked since is refused. A token that
    has expired is not a failed attempt: clients fetch a new one as a matter of course.
    """
    now = utcnow()
    refused = unauthorized("The registry token is not valid or has expired.")
    claims = registry_tokens.read(request.app.state.settings, value, now)
    if claims is None:
        raise refused
    if claims.user_id is None:
        anonymous = await _anonymous_access(db)
        if anonymous is None:
            raise refused
        user, patterns = anonymous
        return Principal(user, "anonymous", patterns, public=patterns)
    user = await users.get_user(db, claims.user_id)
    if user is None or not await users.can_act(db, user) or claims.method == "anonymous":
        raise refused
    if (claims.method == "token") != (claims.token_id is not None):
        raise refused
    token = None
    if claims.token_id is not None:
        token = await tokens.get_token(db, claims.token_id, now)
        if token is None or token.user_id != user.id:
            raise refused
        tokens.touch(token, now)
    return await build_principal(db, user, claims.method, token=token)


async def issue_registry_token(
    request: Request, db: AsyncSession, principal: Principal | None
) -> str:
    """A registry token for whoever is calling: a container client's sign-in.

    `principal` is who the request's credentials identify, or None if it carries
    none. Then the token is the anonymous user's, and is given only while anonymous
    access is on. A registry token is not a credential here: a client that could trade
    one for the next would never have to present its password or API token again.
    """
    scheme, _, presented = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and presented.strip().startswith(registry_tokens.PREFIX):
        raise unauthorized("Sign in with a password or an API token.", scheme="Basic")
    if principal is None or principal.is_anonymous:
        if await _anonymous_access(db) is None:
            raise unauthorized(scheme="Basic")
        claims = registry_tokens.Claims(None, "anonymous")
    else:
        method = "token" if principal.token_id is not None else "password"
        claims = registry_tokens.Claims(principal.user.id, method, principal.token_id)
    return registry_tokens.issue(request.app.state.settings, claims, utcnow())


async def _from_trusted_header(request: Request, db: AsyncSession) -> Principal | None:
    """The user a trusted proxy's header names (spec 8), or None without one. The header of
    an enabled header source is refused (401) unless a trusted proxy passed the request on:
    anyone else could write it."""
    for source in await sources.in_order(db):
        if not source.enabled or source.kind != header.KIND:
            continue
        if source.settings["user_header"] not in request.headers:
            continue
        if not getattr(request.state, "proxied", False):
            audit.record(
                db,
                "sign_in.refused",
                ("source", source.name),
                audit.diff(None, {"why": "not through a trusted proxy"}),
            )
            await db.commit()  # the record must outlive this refused request
            log.warning("trusted_header_refused", source=source.name, ip=client_ip(request))
            raise unauthorized(
                f"{source.settings['user_header']} is taken from a trusted proxy only."
            )
        said = header.identity(source.settings, request.headers)
        if said is None:
            raise unauthorized(
                f"{source.settings['user_header']} must name one person, and be sent once."
            )
        user = await sources.provision(db, source, said)
        if not await users.can_act(db, user):
            raise unauthorized()
        return await build_principal(db, user, "header")
    return None


async def resolve_principal(
    request: Request, db: AsyncSession, *, registry: bool = False, api_key: bool = False
) -> Principal | None:
    """The principal for this request, or None when there are no credentials.

    Invalid credentials in an Authorization header are an error, never a fall-through
    to the cookie or to anonymous access. `registry` says that the request is to the
    container registry API, where a registry token is a credential. `api_key` says
    that an API token in `X-NuGet-ApiKey` is one, where there is no Authorization
    header: a NuGet client sends it so, and nothing else with it.
    """
    proxied = await _from_trusted_header(request, db)
    if proxied is not None:
        return proxied
    authorization = request.headers.get("Authorization")
    if authorization:
        return await _from_header(db, request, authorization, registry=registry)
    key = request.headers.get(API_KEY_HEADER, "").strip() if api_key else ""
    if key:
        user, token = await _authenticate_token(db, request, key)
        return await build_principal(db, user, "token", token=token)

    settings = request.app.state.settings
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        now = utcnow()
        record = await sessions.find_session(
            db, cookie, now=now, idle_seconds=settings.session_idle_seconds
        )
        if record is not None:
            user = await users.get_user(db, record.user_id)
            if user is not None and await users.can_act(db, user):
                sessions.touch(record, now)
                return await build_principal(db, user, "session", session=record)

    anonymous = await _anonymous_access(db)
    if anonymous is not None:
        user, patterns = anonymous
        return Principal(user, "anonymous", patterns, public=patterns)
    return None


async def _refuse_cross_site(request: Request, db: AsyncSession) -> None:
    """Refuse a request from a browser on another site that would change something.

    Browsers remember HTTP Basic credentials after the challenge on /repository and
    attach them to a form posted from any site. Browsers also say where a request came
    from: `Sec-Fetch-Site` on HTTPS and localhost, and `Origin` everywhere. Package
    clients send neither, so they are unaffected.
    """
    if request.method not in _UNSAFE_METHODS:
        return
    refusal = ApiError(
        403,
        "cross_site_request",
        "Requests that change something are not accepted from other sites.",
    )
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        if site == "cross-site":
            raise refusal
        return
    origin = request.headers.get("Origin")
    if origin is None:
        return
    # Without fetch metadata (plain HTTP), compare the origin with where we are served:
    # the Host header, and the public base URL when a reverse proxy rewrites Host.
    ours = {request.headers.get("Host", "").lower()}
    base_url = await get_setting(db, "base_url")
    if base_url:
        ours.add(urlsplit(base_url).netloc.lower())
    if urlsplit(origin).netloc.lower() not in ours:
        raise refusal


async def _require_same_origin(request: Request, db: AsyncSession) -> None:
    """Refuse a change that does not say it comes from this server's own pages: with
    `Sec-Fetch-Site: same-origin` (or `none`, typed by the person), or an `Origin` of
    ours. Stricter than `_refuse_cross_site`, which lets a request that says nothing
    through: a trusted header's request has no token to show instead."""
    refusal = ApiError(
        403,
        "cross_site_request",
        "Requests that change something are accepted from this server's own pages only.",
    )
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        if site not in ("same-origin", "none"):
            raise refusal
        return
    origin = request.headers.get("Origin")
    if origin is None:
        raise refusal
    ours = {request.headers.get("Host", "").lower()}
    base_url = await get_setting(db, "base_url")
    if base_url:
        ours.add(urlsplit(base_url).netloc.lower())
    if urlsplit(origin).netloc.lower() not in ours:
        raise refusal


async def refuse_cross_site(request: Request, db: AsyncSession = Depends(get_session)) -> None:
    """For a route that identifies nobody and still changes something: signing in.

    A page on another site could otherwise sign its visitor in to an account of its
    own choosing, and what the visitor then did would be done as that account.
    """
    await _refuse_cross_site(request, db)


async def _identify(
    request: Request,
    db: AsyncSession,
    scheme: Scheme,
    *,
    registry: bool = False,
    api_key: bool = False,
) -> Principal | None:
    """Check what the request presents. Raises 401 with a challenge, 403 or 429."""
    try:
        principal = await resolve_principal(request, db, registry=registry, api_key=api_key)
    except ApiError as error:
        if error.status_code != 401:
            raise
        raise unauthorized(error.message, scheme=scheme) from None
    await db.commit()  # last-seen times, cleared failure counts, upgraded password hashes
    audit.identified(principal)
    if principal is not None and principal.method == "header" and request.method in _UNSAFE_METHODS:
        # No CSRF token without a session: a change must come from this server's own pages.
        await _require_same_origin(request, db)
    if (
        principal is not None
        and principal.session is not None
        and request.method in _UNSAFE_METHODS
    ):
        sent = request.headers.get(CSRF_HEADER, "")
        expected = principal.session.csrf_token
        if not secrets.compare_digest(sent.encode(), expected.encode()):
            raise ApiError(403, "csrf_failed", "The CSRF token is missing or wrong.")
    return principal


def _principal_dependency(scheme: Scheme) -> Callable[..., Awaitable[Principal | None]]:
    async def dependency(
        request: Request, db: AsyncSession = Depends(get_session)
    ) -> Principal | None:
        await _refuse_cross_site(request, db)
        return await _identify(request, db, scheme)

    return dependency


class Credentials:
    """What a request presents to say who is calling, not yet looked at.

    The content route gets this instead of a principal, because of one request: a
    format's sign-in, which carries its credentials in its body. For that request
    nothing in a header or a cookie is looked at, so a client's revoked token is not a
    failed attempt and cannot lock its user out. For every other request the route
    calls `principal()`, which is the check every other route gets.
    """

    def __init__(
        self,
        request: Request,
        db: AsyncSession,
        scheme: Scheme,
        *,
        registry: bool = False,
        api_key: bool = False,
    ) -> None:
        self._request, self._db, self._scheme = request, db, scheme
        self._registry, self._api_key = registry, api_key

    async def principal(self) -> Principal | None:
        """Who is calling, if anyone. Raises 401 with a challenge, 403 or 429."""
        return await _identify(
            self._request, self._db, self._scheme, registry=self._registry, api_key=self._api_key
        )


async def client_credentials(
    request: Request, db: AsyncSession = Depends(get_session)
) -> Credentials:
    """For the content route: refuse a cross-site write now, identify the caller later.

    A NuGet client's API key counts there (`X-NuGet-ApiKey`).
    """
    await _refuse_cross_site(request, db)
    return Credentials(request, db, "Basic", api_key=True)


async def registry_credentials(
    request: Request, db: AsyncSession = Depends(get_session)
) -> Credentials:
    """For the container registry API: as `client_credentials`, and a registry token counts."""
    await _refuse_cross_site(request, db)
    return Credentials(request, db, "Basic", registry=True)


# Who is calling, if anyone. Both enforce CSRF for cookie requests; they differ only in
# the challenge a 401 carries.
async def _resource_metadata(request: Request, db: AsyncSession) -> str:
    base = (await get_setting(db, "base_url") or str(request.base_url)).rstrip("/")
    return f"{base}/.well-known/oauth-protected-resource/mcp"


async def _agent(request: Request, db: AsyncSession, value: str) -> Principal:
    if value.startswith(TOKEN_PREFIX):
        user, token = await _authenticate_token(db, request, value)
        return await build_principal(db, user, "token", token=token)
    grant = await oauth.find_access(db, value, utcnow())
    user = None if grant is None else await users.get_user(db, grant.user_id)
    if grant is None or user is None or not await users.can_act(db, user):
        # Counted against the address, as a token that is not one is.
        return await _checked(db, request, None, _no_match)
    principal = await build_principal(db, user, "token")
    scopes = None if grant.scopes is None else frozenset(grant.scopes)
    return replace(principal, scopes=scopes, grant_id=grant.id)


async def agent_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    """Dependency of the MCP endpoint: an API token, or an OAuth access token, as a bearer
    token, and nothing else.

    No cookie, no password and no anonymous access: an agent always acts for someone,
    who made its token or approved it. Raises 401, naming where a client finds how to
    sign in (RFC 9728), or 429 after too many failed attempts.
    """
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    value = value.strip()
    try:
        if scheme.lower() != "bearer" or not value.startswith((TOKEN_PREFIX, oauth.ACCESS_PREFIX)):
            raise unauthorized("Sign in with an API token, or with OAuth, as a bearer token.")
        principal = await _agent(request, db, value)
    except ApiError as error:
        if error.status_code == 401:
            metadata = await _resource_metadata(request, db)
            error.headers = {
                "WWW-Authenticate": f'Bearer realm="MegooArti", resource_metadata="{metadata}"'
            }
        raise
    await db.commit()  # when the token, or the approval, was last used
    audit.identified(principal)
    return principal


current_principal = _principal_dependency("Bearer")  # the JSON API
client_principal = _principal_dependency("Basic")  # for package clients
AUTHENTICATION_DEPENDENCIES = frozenset(
    {current_principal, client_principal, client_credentials, registry_credentials, agent_principal}
)


def _refuse_pending_password_change(principal: Principal) -> None:
    if principal.is_interactive and principal.user.must_change_password:
        raise ApiError(
            403, "password_change_required", "Change your password before doing anything else."
        )


def authorize(
    principal: Principal | None, permission: str, *, scheme: Scheme = "Bearer"
) -> Principal:
    """The one place that decides whether a caller may do something."""
    if principal is None:
        raise unauthorized(scheme=scheme)
    _refuse_pending_password_change(principal)
    if not principal.allows(permission):
        if principal.is_anonymous:
            raise unauthorized(scheme=scheme)
        raise ApiError(403, "forbidden", "You do not have permission to do this.")
    return principal


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must hold `permission`."""

    async def dependency(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        return authorize(principal, permission)

    return dependency


async def require_caller(
    principal: Principal | None = Depends(current_principal),
) -> Principal:
    """Dependency: somebody is calling, signed in or anonymous.

    For a route whose answer depends on what the caller may do, such as a list that
    leaves out what they may not see. What they may do is for the route to check.
    """
    if principal is None:
        raise unauthorized()
    _refuse_pending_password_change(principal)
    return principal


def require_interactive(
    *, allow_pending_password_change: bool = False
) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must be signed in as a person, not with a token."""

    async def dependency(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        if principal is None or principal.is_anonymous:
            raise unauthorized()
        if not principal.is_interactive:
            raise ApiError(
                403,
                "interactive_auth_required",
                "Sign in with your password to do this; an API token is not enough.",
            )
        if not allow_pending_password_change:
            _refuse_pending_password_change(principal)
        return principal

    return dependency

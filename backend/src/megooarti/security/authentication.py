"""Who is making this request, and are they allowed to do this?"""

import asyncio
import base64
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.security import sessions, throttle, tokens, users
from megooarti.security.keys import TOKEN_PREFIX
from megooarti.security.models import ApiToken, User, UserSession
from megooarti.security.passwords import hash_password, needs_rehash, verify_password
from megooarti.security.permissions import any_grants, is_valid_permission
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

SESSION_COOKIE = "megooarti_session"
CSRF_HEADER = "X-CSRF-Token"
INVALID_CREDENTIALS = "Invalid credentials."
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

Method = Literal["session", "password", "token", "anonymous"]
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

    @property
    def is_anonymous(self) -> bool:
        return self.method == "anonymous"

    @property
    def is_interactive(self) -> bool:
        """Signed in as a person (cookie or password), not with an API token."""
        return self.method in ("session", "password")

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
    return Principal(user, method, await users.user_patterns(db, user), scopes, session, public)


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
        await db.commit()  # the count must outlive this failed request
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

    async def attempt() -> User | None:
        user = await users.get_user_by_username(db, username)
        stored = None if user is None else user.password_hash
        matched = await asyncio.to_thread(verify_password, stored, password)
        if user is None or not matched or user.status != "active":
            return None
        if needs_rehash(user.password_hash):
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
        if user is None or user.status != "active":
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


def _decode_basic(credentials: str) -> tuple[str, str]:
    try:
        decoded = base64.b64decode(credentials.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise unauthorized("The Authorization header is malformed.") from None
    username, separator, secret = decoded.partition(":")
    if not separator:
        raise unauthorized("The Authorization header is malformed.")
    return username, secret


async def _from_header(db: AsyncSession, request: Request, header: str) -> Principal:
    scheme, _, credentials = header.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer":
        user, token = await _authenticate_token(db, request, credentials.strip())
        return await build_principal(db, user, "token", token=token)
    if scheme == "basic":
        username, secret = _decode_basic(credentials)
        if secret.startswith(TOKEN_PREFIX):
            user, token = await _authenticate_token(db, request, secret, username)
            return await build_principal(db, user, "token", token=token)
        user = await authenticate_password(db, request, username, secret)
        return await build_principal(db, user, "password")
    raise unauthorized("The Authorization scheme is not supported.")


async def resolve_principal(request: Request, db: AsyncSession) -> Principal | None:
    """The principal for this request, or None when there are no credentials.

    Invalid credentials in an Authorization header are an error, never a fall-through
    to the cookie or to anonymous access.
    """
    header = request.headers.get("Authorization")
    if header:
        return await _from_header(db, request, header)

    settings = request.app.state.settings
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        now = utcnow()
        record = await sessions.find_session(
            db, cookie, now=now, idle_seconds=settings.session_idle_seconds
        )
        if record is not None:
            user = await users.get_user(db, record.user_id)
            if user is not None and user.status == "active":
                sessions.touch(record, now)
                return await build_principal(db, user, "session", session=record)

    anonymous = await _anonymous_access(db)
    if anonymous is not None:
        user, patterns = anonymous
        return Principal(user, "anonymous", patterns, public=patterns)
    return None


def _principal_dependency(scheme: Scheme) -> Callable[..., Awaitable[Principal | None]]:
    async def dependency(
        request: Request, db: AsyncSession = Depends(get_session)
    ) -> Principal | None:
        try:
            principal = await resolve_principal(request, db)
        except ApiError as error:
            if error.status_code != 401:
                raise
            raise unauthorized(error.message, scheme=scheme) from None
        await db.commit()  # last-seen times, cleared failure counts, upgraded password hashes
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

    return dependency


# Who is calling, if anyone. Both enforce CSRF for cookie requests; they differ only in
# the challenge a 401 carries.
current_principal = _principal_dependency("Bearer")  # the JSON API
client_principal = _principal_dependency("Basic")  # repository content, for package clients
AUTHENTICATION_DEPENDENCIES = frozenset({current_principal, client_principal})


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

"""Sign-in sources: where people sign in from besides MegooArti's own users (spec 4).

Each kind of source (LDAP, OIDC, a trusted header) is a `Kind`, registered by the module
that brings it. Here is what every kind shares: the order sources are asked in, their
secrets, and the users they make at a first sign-in and bring up to date at each (E2-E5).
"""

import itertools
import re
import ssl
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import httpx
import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories.remote import client_of, tls_of
from megooarti.secrets_box import seal, unseal
from megooarti.security.models import AuthSource, Role, User, UserRole, UserSession
from megooarti.security.sessions import delete_user_sessions
from megooarti.security.users import TOKEN_USERNAME, looks_like_token, normalise_username

log = structlog.get_logger(__name__)

# What a user's name may hold, as the users' API says (`[A-Za-z0-9._@-]`, lower case here).
_NOT_IN_A_NAME = re.compile(r"[^a-z0-9._@-]+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_NAME_LENGTH = 64


@dataclass(frozen=True)
class Identity:
    """Who a source says somebody is."""

    external_id: str  # what the source knows them by, for good: an OIDC subject, an LDAP DN
    username: str  # the name they sign in with there
    display_name: str = ""
    email: str | None = None
    groups: frozenset[str] = frozenset()


# What a source answers a name and a password with, when it is not who they are.
Unknown = Literal["unknown"]  # nobody of that name there: the next source is asked
Refused = Literal["refused"]  # somebody of that name, and not that password: nobody else is
UNKNOWN: Unknown = "unknown"
REFUSED: Refused = "refused"


@dataclass(frozen=True)
class Tested:
    """What testing a source found: whether it answered, and who it said someone is."""

    ok: bool
    message: str
    identity: Identity | None = None


@dataclass(frozen=True)
class Outbound:
    """How a source is reached: the server's one outbound HTTP client, and for what is not
    HTTP (LDAP) what its TLS trusts: the usual authorities and the added certificates."""

    http: httpx.AsyncClient
    tls: ssl.SSLContext


def outbound(app: Any) -> Outbound:
    return Outbound(http=client_of(app), tls=tls_of(app))


class SourceUnavailable(Exception):
    """A source could not be asked: it did not answer, or answered nothing it should."""


class Kind:
    """A kind of source. A module that brings one subclasses this and `register`s it."""

    name: ClassVar[str]
    # The settings that are secrets: sealed when kept, and shown to nobody again (E5).
    secrets: ClassVar[tuple[str, ...]] = ()
    # People sign in to it in the browser, sent there by the sign-in screen (OIDC).
    in_browser: ClassVar[bool] = False
    # It checks a name and a password, when somebody signs in with them here (E3).
    takes_passwords: ClassVar[bool] = False
    # The settings its secrets go with, such as the address they are sent to: changing one
    # asks for the secrets again, which are never sent where they were not given for (E5).
    bound: ClassVar[tuple[str, ...]] = ()

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        """The settings as they are kept, its secrets as they were sent: left out when
        none was. Raises `invalid(...)` for what is wrong with them."""
        raise NotImplementedError

    async def password(
        self,
        outbound: Outbound,
        settings: dict[str, Any],
        name: str,
        password: str,
        known: str | None,
    ) -> Identity | Unknown | Refused:
        """Who `name` is, if `password` is theirs. `known` is the identity a user of this
        source has already, when the name is theirs. Raises SourceUnavailable."""
        return UNKNOWN

    async def test(
        self,
        outbound: Outbound,
        settings: dict[str, Any],
        name: str | None,
        password: str | None,
    ) -> Tested:
        """Whether the source answers, and, given a name, who it says they are."""
        raise NotImplementedError

    def callback_path(self, source_id: uuid.UUID) -> str | None:
        """Where a provider sends people back to, for a kind signed in to in the browser:
        the address to register there, under the server's base URL."""
        return None


KINDS: dict[str, Kind] = {}


def register(kind: Kind) -> Kind:
    KINDS[kind.name] = kind
    return kind


def invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def unavailable(source: AuthSource) -> ApiError:
    return ApiError(
        503, "source_unavailable", f"The sign-in source {source.name} cannot be reached."
    )


# --- The records ----------------------------------------------------------------------


async def in_order(db: AsyncSession) -> list[AuthSource]:
    return list(await db.scalars(select(AuthSource).order_by(AuthSource.position)))


async def get_source(db: AsyncSession, source_id: uuid.UUID) -> AuthSource | None:
    return await db.get(AuthSource, source_id)


def kept_settings(
    settings: Settings, kind: Kind, sent: dict[str, Any], current: dict[str, Any] | None
) -> dict[str, Any]:
    """The settings to keep: checked by the kind, a secret sealed, or the stored one kept
    where none was sent."""
    values = kind.checked(sent)
    moved = current is not None and any(values.get(b) != current.get(b) for b in kind.bound)
    for name in kind.secrets:
        given = values.get(name)
        if given:
            values[name] = str(seal(settings, given))
        elif current is not None and current.get(name):
            if moved:
                raise invalid(f"settings.{name}", "Give it again: what it goes with has changed.")
            values[name] = current[name]
        else:
            values.pop(name, None)
    return values


def shown_settings(kind: Kind | None, stored: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The settings without their secrets, and the names of the secrets that are set."""
    secrets = () if kind is None else kind.secrets
    shown = {name: value for name, value in stored.items() if name not in secrets}
    return shown, sorted(name for name in secrets if stored.get(name))


def opened_settings(settings: Settings, kind: Kind, stored: dict[str, Any]) -> dict[str, Any]:
    """The settings as the kind uses them: its secrets unsealed."""
    opened = dict(stored)
    for name in kind.secrets:
        if opened.get(name):
            opened[name] = unseal(settings, opened[name])
    return opened


async def check_mapping(
    db: AsyncSession, mapping: list[dict[str, Any]], kept: list[dict[str, Any]] = ()
) -> None:
    """Every role a group is newly given must be one there is (spec 11). One it was given
    before and that was deleted since gives nothing, and does not stop the source being
    changed (turned off, say) until the mapping is put right."""
    before = {role for entry in kept for role in entry["roles"]}
    names = sorted({role for entry in mapping for role in entry["roles"]} - before)
    if not names:
        return
    found = set(await db.scalars(select(Role.name).where(Role.name.in_(names))))
    missing = [name for name in names if name not in found]
    if missing:
        raise invalid("group_mapping", f"Unknown role: {', '.join(missing)}")


async def next_position(db: AsyncSession) -> int:
    last = await db.scalar(select(func.max(AuthSource.position)))
    return 0 if last is None else last + 1


async def reorder(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    """Put the sources in this order: every one of them, once."""
    every = {source.id: source for source in await in_order(db)}
    if len(ids) != len(set(ids)) or set(ids) != set(every):
        raise invalid("ids", "Give every source once, in the order they are to be asked.")
    for position, source_id in enumerate(ids):
        every[source_id].position = position
    await db.flush()


async def users_of(db: AsyncSession, source: AuthSource) -> int:
    return await db.scalar(select(func.count()).where(User.source_id == source.id)) or 0


async def sign_out_users(db: AsyncSession, source: AuthSource) -> None:
    """End the sessions of a source's users: turned off, it signs them out for good."""
    await db.execute(
        delete(UserSession).where(
            UserSession.user_id.in_(select(User.id).where(User.source_id == source.id))
        )
    )


async def delete_source(db: AsyncSession, source: AuthSource) -> None:
    """Delete a source. Its users are disabled, and kept with what they own (spec 4.3)."""
    held = list(await db.scalars(select(User.id).where(User.source_id == source.id)))
    if held:
        await db.execute(update(User).where(User.id.in_(held)).values(status="disabled"))
        for user_id in held:
            await delete_user_sessions(db, user_id)
    await db.delete(source)
    await db.flush()


# --- Users of a source ----------------------------------------------------------------


def _usable(name: str) -> str:
    """A name as a user's name may be: lower case, and nothing a name may not hold."""
    return _NOT_IN_A_NAME.sub("-", normalise_username(name)).strip("-")[:_NAME_LENGTH] or "user"


def _names(wanted: str, source: AuthSource):
    """The names a user of this source may be given, the one they have there first."""
    base = _usable(wanted)
    if looks_like_token(base):
        base = f"user-{base}"[:_NAME_LENGTH]  # every name made from it would be shaped so
    yield base
    suffix = "@" + _usable(source.name)[: _NAME_LENGTH // 2]
    yield base[: _NAME_LENGTH - len(suffix)] + suffix
    for number in itertools.count(2):
        more = f"{suffix}-{number}"
        yield base[: _NAME_LENGTH - len(more)] + more


async def _free_name(
    db: AsyncSession, wanted: str, source: AuthSource, own: uuid.UUID | None
) -> str:
    """Their name there, unless another user has it: then `name@source` (spec 4.2)."""
    for name in _names(wanted, source):
        if name == TOKEN_USERNAME or looks_like_token(name):
            continue  # nobody's name, whatever a source says
        holder = await db.scalar(select(User.id).where(User.username == name))
        if holder is None or holder == own:
            return name
    raise AssertionError("unreachable")  # pragma: no cover


def mapped_role_names(source: AuthSource, groups: frozenset[str]) -> list[str]:
    """The roles a source's group mapping gives a member of these groups."""
    member = {group.casefold() for group in groups}
    return sorted(
        {
            role
            for entry in source.group_mapping
            if entry["group"].casefold() in member
            for role in entry["roles"]
        }
    )


async def _held_roles(db: AsyncSession, user: User) -> dict[uuid.UUID, str]:
    """The roles a user holds, each with who gave it."""
    rows = await db.execute(
        select(UserRole.role_id, UserRole.granted_by).where(UserRole.user_id == user.id)
    )
    return {role_id: by for role_id, by in rows}


async def _existing(db: AsyncSession, source: AuthSource, external_id: str) -> User | None:
    return await db.scalar(
        select(User).where(User.source_id == source.id, User.external_id == external_id)
    )


async def _map_roles(
    db: AsyncSession, user: User, source: AuthSource, groups: frozenset[str]
) -> None:
    """Give the roles the groups give, and take back those they no longer do. Roles an
    administrator gave are theirs, and kept (E4)."""
    names = mapped_role_names(source, groups)
    wanted = set(await db.scalars(select(Role.id).where(Role.name.in_(names)))) if names else set()
    held = await _held_roles(db, user)
    gone = [role_id for role_id, by in held.items() if by == "source" and role_id not in wanted]
    if gone:
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id.in_(gone))
        )
    new = wanted - held.keys()
    if new:
        # Another sign-in of theirs at the same moment may have given it already.
        await db.execute(
            insert(UserRole)
            .values(
                [
                    {"user_id": user.id, "role_id": role_id, "granted_by": "source"}
                    for role_id in new
                ]
            )
            .on_conflict_do_nothing()
        )


async def _first(db: AsyncSession, source: AuthSource, identity: Identity) -> User:
    """The user made at a first sign-in; or, when another sign-in of theirs made them a
    moment before (a package client's requests at once), that one."""
    made = User(
        username=await _free_name(db, identity.username, source, None),
        display_name=identity.username[:128],
        password_hash=None,
        status="active",
        must_change_password=False,
        builtin=False,
        source_id=source.id,
        external_id=identity.external_id,
    )
    try:
        async with db.begin_nested():
            db.add(made)
    except IntegrityError:
        found = await _existing(db, source, identity.external_id)
        if found is None:
            raise  # not theirs: another name taken at the same moment
        return found
    log.info("user_provisioned", username=made.username, source=source.name)
    return made


async def provision(db: AsyncSession, source: AuthSource, identity: Identity) -> User:
    """The user this identity is: made at their first sign-in, and their name, details and
    mapped roles brought up to date at each (spec 4.2)."""
    user = await _existing(db, source, identity.external_id)
    if user is None:
        user = await _first(db, source, identity)
    user.username = await _free_name(db, identity.username, source, user.id)
    user.display_name = (identity.display_name.strip() or identity.username)[:128]
    email = identity.email if identity.email and _EMAIL.fullmatch(identity.email) else None
    user.email = email if email is None else email[:254]
    await db.flush()
    await _map_roles(db, user, source, identity.groups)
    return user


async def _ask(
    settings: Settings,
    reach: Outbound,
    source: AuthSource,
    name: str,
    password: str,
    known: str | None,
) -> Identity | Unknown | Refused:
    kind = KINDS.get(source.kind)
    if kind is None or not kind.takes_passwords or not source.enabled:
        return UNKNOWN
    try:
        return await kind.password(
            reach, opened_settings(settings, kind, source.settings), name, password, known
        )
    except SourceUnavailable as error:
        log.warning("source_unavailable", source=source.name, error=str(error))
        raise unavailable(source) from None


async def password_sign_in(
    db: AsyncSession,
    settings: Settings,
    reach: Outbound,
    name: str,
    password: str,
    user: User | None,
) -> User | None:
    """The user a name and a password are, by the sources (E3): a user of a source is asked
    of their own source alone; a name nobody has, of each enabled source that takes
    passwords, in order, the first that knows the name deciding. None if none does."""
    if user is not None:
        source = None if user.source_id is None else await get_source(db, user.source_id)
        if source is None:
            return None
        answer = await _ask(settings, reach, source, name, password, user.external_id)
        if not isinstance(answer, Identity) or answer.external_id != user.external_id:
            return None
        return await provision(db, source, answer)
    for source in await in_order(db):
        answer = await _ask(settings, reach, source, name, password, None)
        if answer == REFUSED:
            return None
        if isinstance(answer, Identity):
            return await provision(db, source, answer)
    return None

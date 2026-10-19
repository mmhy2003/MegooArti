"""LDAP sign-in sources (spec 7): a person's name and password checked against a
directory (OpenLDAP, Active Directory), their groups giving them roles.

`ldap3` is blocking: everything that talks to a directory runs in a thread. TLS (ldaps,
or StartTLS) trusts what every outbound connection trusts (15c), in a context of its own:
the shared one is never changed.
"""

import asyncio
import functools
import re
import ssl
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

import ldap3
import structlog
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import parse_dn

from megooarti.repositories.remote import tls_context
from megooarti.security import sources
from megooarti.security.sources import (
    REFUSED,
    UNKNOWN,
    Identity,
    SourceUnavailable,
    Tested,
    invalid,
)

log = structlog.get_logger(__name__)

KIND = "ldap"
# How long a directory is given to connect, and to answer each request (spec 7).
TIMEOUT_SECONDS = 10
GROUP_MODES = ("member_of", "search", "none")
DEFAULTS = {
    "user_filter": "(uid={username})",
    "username_attribute": "uid",
    "name_attribute": "cn",
    "email_attribute": "mail",
    "groups": "member_of",
    "member_of_attribute": "memberOf",
    "group_filter": "(member={dn})",
    "group_name_attribute": "cn",
}
_ATTRIBUTE = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}")
# LDAP's result codes this module tells apart.
_SUCCESS = 0
_SIZE_LIMIT_EXCEEDED = 4
_REFERRAL = 10
_NO_SUCH_OBJECT = 32
_INVALID_CREDENTIALS = 49
_PRINCIPAL_NAME = re.compile(r"[^@\s=,]+@[^@\s=,]+")


class _Trusting(ldap3.Tls):
    """ldap3's TLS, with the context the server's outbound connections trust (15c)."""

    def __init__(self, context: ssl.SSLContext) -> None:
        super().__init__(validate=ssl.CERT_REQUIRED)
        self._context = context

    def wrap_socket(self, connection: Any, do_handshake: bool = False) -> None:
        connection.socket = self._context.wrap_socket(
            connection.socket,
            server_side=False,
            do_handshake_on_connect=do_handshake,
            server_hostname=connection.server.host,  # checked by the context
        )


@functools.lru_cache(maxsize=4)
def context_for(pems: tuple[str, ...]) -> ssl.SSLContext:
    """A context of LDAP's own, trusting what the shared one trusts."""
    return tls_context(pems)


def _dn(value: Any, field: str, *, required: bool) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise invalid(field, "A DN is required, as ou=people,dc=corp,dc=example.")
        return None
    try:
        parse_dn(text)
    except LDAPException:
        raise invalid(field, "This is not a DN, as ou=people,dc=corp,dc=example.") from None
    return text


def _bind_name(value: Any) -> str | None:
    """Who the server binds as: a DN, or, as Active Directory takes, a user principal name
    (svc-megooarti@corp.example)."""
    text = str(value or "").strip()
    if _PRINCIPAL_NAME.fullmatch(text):
        return text
    return _dn(text, "settings.bind_dn", required=False)


def _filter(value: Any, field: str, default: str, *names: str) -> str:
    text = str(value or default).strip()
    if not (text.startswith("(") and text.endswith(")")) or text.count("(") != text.count(")"):
        raise invalid(field, "A filter is in parentheses, as (uid={username}).")
    if not any("{" + name + "}" in text for name in names):
        said = " or ".join("{" + name + "}" for name in names)
        raise invalid(field, f"The filter must name {said}, where the name goes.")
    leftover = re.sub(r"\{(username|dn)\}", "", text)
    if "{" in leftover or "}" in leftover:
        raise invalid(field, "Only {username} and {dn} may be in braces.")
    return text


class LdapKind(sources.Kind):
    name = KIND
    secrets = ("bind_password",)
    # The password goes to the server, and in the clear without StartTLS: either changed,
    # it is asked again (S16).
    bound = ("url", "starttls")
    takes_passwords = True

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        url = str(settings.get("url") or "").strip()
        parts = urlsplit(url)
        try:
            parts.port  # noqa: B018  (a port that is not a number raises)
        except ValueError:
            raise invalid("settings.url", "The port is a number.") from None
        if parts.scheme not in ("ldap", "ldaps") or not parts.hostname:
            raise invalid(
                "settings.url", "An ldap:// or ldaps:// address, as ldaps://ldap.corp.example."
            )
        if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
            raise invalid("settings.url", "An address with a host and a port only.")
        starttls = bool(settings.get("starttls", False))
        if starttls and parts.scheme == "ldaps":
            raise invalid("settings.starttls", "ldaps:// is TLS already.")
        groups = settings.get("groups", DEFAULTS["groups"])
        if groups not in GROUP_MODES:
            raise invalid("settings.groups", f"Must be one of: {', '.join(GROUP_MODES)}.")
        values: dict[str, Any] = {
            "url": url.rstrip("/"),
            "starttls": starttls,
            "bind_dn": _bind_name(settings.get("bind_dn")),
            "bind_password": settings.get("bind_password") or None,
            "user_base": _dn(settings.get("user_base"), "settings.user_base", required=True),
            "user_filter": _filter(
                settings.get("user_filter"),
                "settings.user_filter",
                DEFAULTS["user_filter"],
                "username",
            ),
            "groups": groups,
        }
        for name in (
            "username_attribute",
            "name_attribute",
            "email_attribute",
            "member_of_attribute",
            "group_name_attribute",
        ):
            attribute = str(settings.get(name) or DEFAULTS[name]).strip()
            if not _ATTRIBUTE.fullmatch(attribute):
                raise invalid(
                    f"settings.{name}",
                    "An attribute's name is a letter, then letters, digits or -.",
                )
            values[name] = attribute
        if groups == "search":
            values["group_base"] = _dn(
                settings.get("group_base"), "settings.group_base", required=True
            )
            values["group_filter"] = _filter(
                settings.get("group_filter"),
                "settings.group_filter",
                DEFAULTS["group_filter"],
                "dn",
                "username",
            )
        return values

    async def password(self, outbound, settings, name, password, known):
        if not password:
            # A directory takes an empty password as an anonymous bind, which succeeds.
            return REFUSED
        return await in_thread(
            _sign_in, settings, context_for(outbound.trusted), name, password, known
        )

    async def test(self, outbound, settings, name, password) -> Tested:
        return await in_thread(_test, settings, context_for(outbound.trusted), name)


# --- Talking to the directory (in a thread) -----------------------------------------------

# Directories are asked on threads of their own: one that is slow, or down, must not take
# the threads the server reads and writes files with (asyncio.to_thread's).
THREAD_COUNT = 8
THREADS = ThreadPoolExecutor(max_workers=THREAD_COUNT, thread_name_prefix="ldap")


async def in_thread[T](function: Callable[..., T], *arguments: Any) -> T:
    return await asyncio.get_running_loop().run_in_executor(THREADS, function, *arguments)


def _open(
    settings: dict[str, Any], context: ssl.SSLContext, user: str | None, password: str | None
) -> ldap3.Connection:
    """A connection to the directory, TLS started where it is asked for, not yet bound.
    The tests put a directory of their own here."""
    parts = urlsplit(settings["url"])
    server = ldap3.Server(
        parts.hostname,
        port=parts.port,
        use_ssl=parts.scheme == "ldaps",
        tls=_Trusting(context),
        connect_timeout=TIMEOUT_SECONDS,
        get_info=ldap3.NONE,
    )
    connection = ldap3.Connection(
        server,
        user=user,
        password=password,
        receive_timeout=TIMEOUT_SECONDS,
        raise_exceptions=False,
        read_only=True,
        # A referral is never followed: ldap3 would bind there with the same password,
        # to any host, without TLS. A base the directory refers elsewhere is said.
        auto_referrals=False,
    )
    connection.open()
    if settings["starttls"] and not connection.start_tls():
        raise SourceUnavailable(f"{parts.hostname} did not start TLS.")
    return connection


def _close(connection: ldap3.Connection) -> None:
    try:
        connection.unbind()
    except (LDAPException, OSError):
        pass  # what goes is gone either way


def _unreachable(error: Exception) -> SourceUnavailable:
    return SourceUnavailable(f"The directory could not be reached: {error}")


def _bound(settings: dict[str, Any], context: ssl.SSLContext) -> ldap3.Connection:
    """A connection bound as the bind DN, or anonymously without one."""
    try:
        connection = _open(settings, context, settings["bind_dn"], settings.get("bind_password"))
        bound = connection.bind()
    except (LDAPException, OSError) as error:
        raise _unreachable(error) from None
    if not bound:
        said = connection.result.get("description", "refused")
        _close(connection)
        raise SourceUnavailable(f"The directory refused the bind DN ({said}).")
    return connection


def _answered(connection: ldap3.Connection, *allowed: int) -> int:
    """The result code of the last search, if it is one of these; else SourceUnavailable.
    A search that failed is never taken for one that found nobody: that would send the
    password on to the next source (S5)."""
    code = connection.result.get("result")
    if code == _REFERRAL:
        raise SourceUnavailable(
            "The directory answered with a referral to another server: set a base it holds."
        )
    if code not in allowed:
        raise SourceUnavailable(f"The directory answered {connection.result.get('description')}.")
    return code


def _attributes(settings: dict[str, Any]) -> list[str]:
    wanted = [
        settings["username_attribute"],
        settings["name_attribute"],
        settings["email_attribute"],
    ]
    if settings["groups"] == "member_of":
        wanted.append(settings["member_of_attribute"])
    return wanted


def _first(entry: dict[str, list[Any]], attribute: str) -> str | None:
    """An attribute's first value, as text; None for none, or one that is all spaces."""
    values = entry.get(attribute) or []
    value = values[0] if isinstance(values, list) and values else values
    text = str(value).strip() if value else ""
    return text or None


def _find(
    connection: ldap3.Connection, settings: dict[str, Any], name: str
) -> list[tuple[str, dict]]:
    """The entries the user filter gives for a name, at most two: one is the person."""
    wanted = settings["user_filter"].replace("{username}", escape_filter_chars(name))
    connection.search(
        settings["user_base"], wanted, ldap3.SUBTREE, attributes=_attributes(settings), size_limit=2
    )
    _answered(connection, _SUCCESS, _SIZE_LIMIT_EXCEEDED)  # the limit: two were found
    return [(entry.entry_dn, entry.entry_attributes_as_dict) for entry in connection.entries]


def _parts(dn: str) -> list[tuple[str, str]]:
    return [(attribute.lower(), value.lower()) for attribute, value, _ in parse_dn(dn)]


def _under(dn: str, base: str) -> bool:
    """Whether a DN is the base's, or beneath it."""
    try:
        entry, holder = _parts(dn), _parts(base)
    except LDAPException:
        return False
    return len(entry) >= len(holder) and entry[len(entry) - len(holder) :] == holder


def _still(
    connection: ldap3.Connection, settings: dict[str, Any], dn: str
) -> tuple[str, dict] | None:
    """A known user's entry, if the directory still gives them as one: under the users'
    base, and matching the user filter (with any name). None if it does not."""
    if not _under(dn, settings["user_base"]):
        return None
    wanted = settings["user_filter"].replace("{username}", "*")
    connection.search(dn, wanted, ldap3.BASE, attributes=_attributes(settings))
    if _answered(connection, _SUCCESS, _NO_SUCH_OBJECT) == _NO_SUCH_OBJECT:
        return None
    if not connection.entries:
        return None  # there, and no longer one the filter gives
    entry = connection.entries[0]
    return entry.entry_dn, entry.entry_attributes_as_dict


def _rdn_value(dn: str) -> str | None:
    try:
        return parse_dn(dn)[0][1]
    except (LDAPException, IndexError):
        return None


def _groups(
    connection: ldap3.Connection, settings: dict[str, Any], dn: str, entry: dict, name: str
) -> frozenset[str]:
    """Each group by its name and by its DN: a mapping may name either."""
    found: set[str] = set()
    if settings["groups"] == "member_of":
        for group in entry.get(settings["member_of_attribute"]) or []:
            found |= {str(group), _rdn_value(str(group)) or str(group)}
    elif settings["groups"] == "search":
        wanted = (
            settings["group_filter"]
            .replace("{dn}", escape_filter_chars(dn))
            .replace("{username}", escape_filter_chars(name))
        )
        connection.search(
            settings["group_base"],
            wanted,
            ldap3.SUBTREE,
            attributes=[settings["group_name_attribute"]],
        )
        # A search that failed would take away every role the groups give.
        _answered(connection, _SUCCESS)
        for group in connection.entries:
            names = group.entry_attributes_as_dict.get(settings["group_name_attribute"]) or []
            found |= {group.entry_dn, *(str(value) for value in names)}
    return frozenset(group for group in found if group)


def _identity(
    connection: ldap3.Connection, settings: dict[str, Any], dn: str, entry: dict, name: str
) -> Identity:
    # The directory's own name: the one typed may be an email, or of other letters' case.
    username = _first(entry, settings["username_attribute"]) or name
    return Identity(
        external_id=dn,
        username=username,
        display_name=_first(entry, settings["name_attribute"]) or username,
        email=_first(entry, settings["email_attribute"]),
        groups=_groups(connection, settings, dn, entry, username),
    )


def _binds(settings: dict[str, Any], context: ssl.SSLContext, dn: str, password: str) -> bool:
    """Whether the entry binds with this password. A directory that fails otherwise than
    by refusing the password is SourceUnavailable."""
    person = _open(settings, context, dn, password)
    try:
        if person.bind():
            return True
        if person.result.get("result") != _INVALID_CREDENTIALS:
            raise SourceUnavailable(f"The directory answered {person.result.get('description')}.")
        return False
    finally:
        _close(person)


def _sign_in(
    settings: dict[str, Any], context: ssl.SSLContext, name: str, password: str, known: str | None
) -> Identity | str:
    """Bind as the bind DN, find the one entry the name is (a known user's own, if the
    directory still gives it), bind as it with the password, read its groups (spec 7)."""
    connection = _bound(settings, context)
    try:
        if known is not None:
            found = _still(connection, settings, known)
            entries = [] if found is None else [found]
        else:
            entries = _find(connection, settings, name)
        if not entries:
            return UNKNOWN
        if len(entries) > 1:
            log.warning("ldap_name_ambiguous", name=name)
            return REFUSED  # several people of one name: none of them is signed in
        dn, entry = entries[0]
        if not _binds(settings, context, dn, password):
            return REFUSED
        return _identity(connection, settings, dn, entry, name)
    except (LDAPException, OSError) as error:
        raise _unreachable(error) from None
    finally:
        _close(connection)


def _test(settings: dict[str, Any], context: ssl.SSLContext, name: str | None) -> Tested:
    """Connect and bind; with a name, find its entry and groups. No password is tried."""
    connection = _bound(settings, context)
    try:
        if not name:
            return Tested(True, "The directory answered, and took the bind DN.")
        entries = _find(connection, settings, name)
        if not entries:
            return Tested(False, f"The directory has nobody the filter gives for {name}.")
        if len(entries) > 1:
            return Tested(False, f"The filter gives several entries for {name}: it must give one.")
        dn, entry = entries[0]
        identity = _identity(connection, settings, dn, entry, name)
        return Tested(True, f"{name} is {dn}.", identity)
    except (LDAPException, OSError) as error:
        raise _unreachable(error) from None
    finally:
        _close(connection)


# --- The hourly check (spec 7, D4) ---------------------------------------------------------


def missing(settings: dict[str, Any], context: ssl.SSLContext, dns: Sequence[str]) -> list[str]:
    """Which of these DNs the directory no longer gives as users: gone, moved out of the
    users' base, or no longer matching the user filter. Raises SourceUnavailable when it
    cannot be asked, or does not show the users' base: a replica that is empty, or a bind
    DN that may no longer read, would make every DN look gone."""
    connection = _bound(settings, context)
    try:
        connection.search(settings["user_base"], "(objectClass=*)", ldap3.BASE, attributes=[])
        _answered(connection, _SUCCESS)
        if not connection.entries:
            raise SourceUnavailable("The directory does not show the users' base.")
        return [dn for dn in dns if _still(connection, settings, dn) is None]
    except (LDAPException, OSError) as error:
        raise _unreachable(error) from None
    finally:
        _close(connection)


sources.register(LdapKind())

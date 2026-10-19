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
from collections.abc import Sequence
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
_NO_SUCH_OBJECT = 32
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
        return await asyncio.to_thread(
            _sign_in, settings, context_for(outbound.trusted), name, password, known
        )

    async def test(self, outbound, settings, name, password) -> Tested:
        return await asyncio.to_thread(_test, settings, context_for(outbound.trusted), name)


# --- Talking to the directory (in a thread) -----------------------------------------------


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
    )
    connection.open()
    if settings["starttls"] and not connection.start_tls():
        raise SourceUnavailable(f"{parts.hostname} did not start TLS.")
    return connection


def _bound(settings: dict[str, Any], context: ssl.SSLContext) -> ldap3.Connection:
    """A connection bound as the bind DN, or anonymously without one."""
    try:
        connection = _open(settings, context, settings["bind_dn"], settings.get("bind_password"))
        bound = connection.bind()
    except (LDAPException, OSError) as error:
        raise SourceUnavailable(f"The directory could not be reached: {error}") from None
    if not bound:
        said = connection.result.get("description", "refused")
        raise SourceUnavailable(f"The directory refused the bind DN ({said}).")
    return connection


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
    return [(entry.entry_dn, entry.entry_attributes_as_dict) for entry in connection.entries]


def _read(
    connection: ldap3.Connection, settings: dict[str, Any], dn: str
) -> tuple[str, dict] | None:
    """The entry of a DN, or None when the directory has none."""
    connection.search(dn, "(objectClass=*)", ldap3.BASE, attributes=_attributes(settings))
    if connection.result.get("result") == _NO_SUCH_OBJECT or not connection.entries:
        return None
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
        for group in connection.entries:
            names = group.entry_attributes_as_dict.get(settings["group_name_attribute"]) or []
            found |= {group.entry_dn, *(str(value) for value in names)}
    return frozenset(group for group in found if group)


def _identity(
    connection: ldap3.Connection, settings: dict[str, Any], dn: str, entry: dict, name: str
) -> Identity:
    username = _first(entry, settings["username_attribute"]) or name
    return Identity(
        external_id=dn,
        username=username,
        display_name=_first(entry, settings["name_attribute"]) or username,
        email=_first(entry, settings["email_attribute"]),
        groups=_groups(connection, settings, dn, entry, name),
    )


def _sign_in(
    settings: dict[str, Any], context: ssl.SSLContext, name: str, password: str, known: str | None
) -> Identity | str:
    """Bind as the bind DN, find the one entry the name is, bind as it with the password,
    read its groups (spec 7)."""
    connection = _bound(settings, context)
    try:
        if known is not None:
            found = _read(connection, settings, known)
            entries = [] if found is None else [found]
        else:
            entries = _find(connection, settings, name)
        if not entries:
            return UNKNOWN
        if len(entries) > 1:
            log.warning("ldap_name_ambiguous", name=name)
            return REFUSED  # several people of one name: none of them is signed in
        dn, entry = entries[0]
        try:
            person = _open(settings, context, dn, password)
            if not person.bind():
                return REFUSED
            person.unbind()
        except (LDAPException, OSError) as error:
            raise SourceUnavailable(f"The directory could not be reached: {error}") from None
        return _identity(connection, settings, dn, entry, name)
    finally:
        connection.unbind()


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
    finally:
        connection.unbind()


# --- The hourly check (spec 7, D4) ---------------------------------------------------------


def missing(settings: dict[str, Any], context: ssl.SSLContext, dns: Sequence[str]) -> list[str]:
    """Which of these DNs the directory no longer has. Raises SourceUnavailable when it
    cannot be asked: then nobody is said to be missing."""
    connection = _bound(settings, context)
    try:
        gone = []
        for dn in dns:
            connection.search(dn, "(objectClass=*)", ldap3.BASE, attributes=[])
            code = connection.result.get("result")
            if code == _NO_SUCH_OBJECT:
                gone.append(dn)
            elif code != 0:
                raise SourceUnavailable(
                    f"The directory answered {connection.result.get('description')}."
                )
        return gone
    finally:
        connection.unbind()


sources.register(LdapKind())

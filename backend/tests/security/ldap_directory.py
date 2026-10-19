"""A directory of the tests' own, answered by ldap3's mock strategy (spec 12), in place of
the connections `security.ldap` opens."""

from typing import Any

from ldap3 import MOCK_SYNC, OFFLINE_SLAPD_2_4, Connection, Server
from ldap3.core.exceptions import LDAPSocketOpenError

BASE = "dc=corp,dc=example"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
READER = f"cn=reader,{BASE}"
READER_PASSWORD = "the reader's password"


class Directory:
    def __init__(self) -> None:
        self._server = Server("ldap.corp.example", get_info=OFFLINE_SLAPD_2_4)
        self._seed = Connection(self._server, client_strategy=MOCK_SYNC)
        self.down = False
        self.binds: list[str | None] = []  # who each connection opened was to bind as
        self.add(
            READER, objectClass="person", cn="reader", sn="reader", userPassword=READER_PASSWORD
        )
        # The containers a directory has: the hourly check asks for the users' base first.
        self.add(BASE, objectClass="domain", dc="corp")
        self.add(PEOPLE, objectClass="organizationalUnit", ou="people")
        self.add(GROUPS, objectClass="organizationalUnit", ou="groups")

    def add(self, dn: str, **attributes: Any) -> None:
        self._seed.strategy.add_entry(dn, attributes)

    def person(self, uid: str, password: str, *, ou: str = "people", **more: Any) -> str:
        dn = f"uid={uid},ou={ou},{BASE}"
        self.add(
            dn,
            objectClass=["inetOrgPerson"],
            uid=uid,
            cn=more.pop("cn", uid.title()),
            sn=uid,
            userPassword=password,
            **more,
        )
        return dn

    def group(self, name: str, *members: str) -> str:
        dn = f"cn={name},{GROUPS}"
        self.add(dn, objectClass="groupOfNames", cn=name, member=list(members))
        return dn

    def remove(self, dn: str) -> None:
        self._seed.strategy.remove_entry(dn)

    def open(
        self, settings: dict, context: Any, user: str | None, password: str | None
    ) -> Connection:
        """As `security.ldap._open`: a connection, not yet bound."""
        if self.down:
            raise LDAPSocketOpenError("socket connection error while opening: [WinError 10061]")
        self.binds.append(user)
        connection = Connection(
            self._server,
            user=user,
            password=password,
            client_strategy=MOCK_SYNC,
            raise_exceptions=False,
        )
        connection.strategy.entries = self._seed.strategy.entries
        connection.open()
        return connection

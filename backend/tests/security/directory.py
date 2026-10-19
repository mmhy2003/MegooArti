"""Kinds of sign-in source for the tests, until LDAP (15d) and OIDC (15b) bring real ones.

`Directory` is a directory written in its own settings: the people it knows, by name,
with their password, identity and groups. It takes passwords as LDAP does, and answers
only when its `secret` is the one it was given, so that a test sees the secret unsealed.
`Portal` is signed in to in the browser, as OIDC is.
"""

from typing import Any

from megooarti.security import sources

SECRET = "the directory's bind password"


class Directory(sources.Kind):
    name = "directory"
    secrets = ("secret",)
    bound = ("address",)
    takes_passwords = True

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        people = settings.get("people", {})
        if not isinstance(people, dict):
            raise sources.invalid("settings.people", "Must be an object of people by name.")
        return {
            "people": people,
            "down": bool(settings.get("down")),
            "address": str(settings.get("address", "ldap://directory.example")),
            "secret": settings.get("secret"),
        }

    def _identity(self, name: str, person: dict[str, Any]) -> sources.Identity:
        return sources.Identity(
            external_id=person.get("id", f"uid={name},ou=people"),
            username=person.get("username", name),
            display_name=person.get("display_name", name.title()),
            email=person.get("email"),
            groups=frozenset(person.get("groups", [])),
        )

    async def password(self, outbound, settings, name, password, known):
        if settings["down"] or settings.get("secret") != SECRET:
            raise sources.SourceUnavailable("the directory did not answer")
        for found, person in settings["people"].items():
            identity = self._identity(found, person)
            if (known is not None and identity.external_id == known) or (
                known is None and found.casefold() == name.casefold()
            ):
                return identity if person["password"] == password else sources.REFUSED
        return sources.UNKNOWN

    async def test(self, outbound, settings, name, password):
        if settings["down"] or settings.get("secret") != SECRET:
            raise sources.SourceUnavailable("the directory did not answer")
        if name is None:
            return sources.Tested(True, "The directory answered.")
        person = settings["people"].get(name)
        if person is None or person["password"] != password:
            return sources.Tested(False, f"The directory does not know {name} by that password.")
        return sources.Tested(True, f"{name} signed in.", self._identity(name, person))


class Portal(sources.Kind):
    name = "portal"
    in_browser = True

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"issuer": str(settings.get("issuer", ""))}


def person(password: str, *groups: str, **more: Any) -> dict[str, Any]:
    return {"password": password, "groups": list(groups), **more}

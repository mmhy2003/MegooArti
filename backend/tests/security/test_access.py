"""`may` (spec 10, E6): a repository permission reaches every path; a selector permission,
the paths its selector matches; a token's scopes and the public's patterns as for any
permission. Tested against a table of permissions, selectors, paths and actions."""

import pytest
from sqlalchemy import literal

from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.security import access, roles, selectors
from megooarti.security.authentication import Principal, build_principal
from megooarti.security.models import ContentSelector, User

RELEASES = Repository(name="releases", format="maven", type="hosted", config={})
SNAPSHOTS = Repository(name="snapshots", format="maven", type="hosted", config={})
NPM = Repository(name="npm-hosted", format="npm", type="hosted", config={})
SELECTORS = {
    "acme": 'path =^ "/com/acme/"',
    "jars": 'path =~ ".*\\\\.jar"',
    "npm-only": 'format == "npm"',
    "broken": "path ==",
}
ACME_JAR = "/com/acme/app/1.0/app-1.0.jar"
ACME_POM = "com/acme/app/1.0/app-1.0.pom"  # as content paths are kept, without the slash
OTHER_JAR = "/org/other/1.0/other-1.0.jar"


def caller(
    *patterns: str,
    scopes: list[str] | None = None,
    public: tuple[str, ...] = (),
    method: str = "session",
) -> Principal:
    return Principal(
        User(username="kim", display_name="Kim", status="active"),
        method,
        frozenset(patterns),
        None if scopes is None else frozenset(scopes),
        public=frozenset(public),
        selectors=SELECTORS,
    )


@pytest.mark.parametrize(
    ("patterns", "repository", "path", "action", "allowed"),
    [
        # A repository permission: every path.
        (["repository:maven:releases:read"], RELEASES, OTHER_JAR, "read", True),
        (["repository:maven:releases:read"], SNAPSHOTS, OTHER_JAR, "read", False),
        (["repository:maven:releases:read"], RELEASES, OTHER_JAR, "add", False),
        # A selector permission: the paths its selector matches, and their neighbours not.
        (["selector:acme:maven:releases:read"], RELEASES, ACME_JAR, "read", True),
        (["selector:acme:maven:releases:read"], RELEASES, ACME_POM, "read", True),
        (["selector:acme:maven:releases:read"], RELEASES, OTHER_JAR, "read", False),
        (["selector:acme:maven:releases:read"], RELEASES, ACME_JAR, "delete", False),
        (["selector:acme:maven:releases:read"], SNAPSHOTS, ACME_JAR, "read", False),
        (["selector:acme:maven:*:read"], SNAPSHOTS, ACME_JAR, "read", True),
        (["selector:acme:*:*:*"], NPM, "/com/acme/x.tgz", "delete", True),
        (["selector:acme"], RELEASES, ACME_JAR, "edit", True),
        (["selector:jars:maven:*:read"], RELEASES, OTHER_JAR, "read", True),
        (["selector:jars:maven:*:read"], RELEASES, ACME_POM, "read", False),
        # Every selector, each by what it matches.
        (["selector:*:maven:releases:read"], RELEASES, ACME_POM, "read", True),
        (["selector:*:maven:releases:read"], RELEASES, "/org/other/x.pom", "read", False),
        # One whose format is another reaches nothing; one that no longer parses, nothing.
        (["selector:npm-only:*:*:read"], RELEASES, ACME_JAR, "read", False),
        (["selector:npm-only:*:*:read"], NPM, "/anything", "read", True),
        (["selector:broken:*:*:read"], RELEASES, ACME_JAR, "read", False),
        # A selector permission naming a selector there is none of.
        (["selector:gone:*:*:read"], RELEASES, ACME_JAR, "read", False),
        (["*"], RELEASES, OTHER_JAR, "delete", True),
        ([], RELEASES, ACME_JAR, "read", False),
    ],
)
def test_may_decides_by_repository_and_selector_permissions(
    patterns, repository, path, action, allowed
):
    assert access.may(caller(*patterns), repository, path, action) is allowed


def test_a_tokens_scopes_narrow_a_selector_permission_as_its_repository_permission():
    reader = caller("selector:acme:maven:*:*", scopes=["repository:*:*:read"])
    selector_scoped = caller("selector:acme:maven:*:*", scopes=["selector:acme:*:*:read"])

    assert access.may(reader, RELEASES, ACME_JAR, "read")
    assert not access.may(reader, RELEASES, ACME_JAR, "add")
    assert access.may(selector_scoped, RELEASES, ACME_JAR, "read")
    assert not access.may(selector_scoped, RELEASES, ACME_JAR, "delete")


def test_the_publics_selector_permissions_are_everyones():
    public = ("selector:acme:maven:releases:read",)
    anonymous = caller(*public, public=public, method="anonymous")
    signed_in = caller(public=public)

    assert access.may(anonymous, RELEASES, ACME_JAR, "read")
    assert access.may(signed_in, RELEASES, ACME_JAR, "read")
    assert not access.may(anonymous, RELEASES, OTHER_JAR, "read")


def test_what_of_a_repository_is_reached_says_what_is_listed():
    acme = access.reach(caller("selector:acme:maven:releases:browse"), RELEASES, "browse")
    whole = access.reach(caller("repository:maven:releases:browse"), RELEASES, "browse")
    elsewhere = access.reach(caller("selector:npm-only:*:*:browse"), RELEASES, "browse")

    assert (acme.anything, whole.anything, elsewhere.anything) == (True, True, False)
    assert acme.folder("com") and acme.folder("/com/acme/app")
    assert not acme.folder("org")
    assert whole.folder("org")
    assert whole.narrowing(None) == (None, True)
    jars = access.reach(caller("selector:jars:maven:releases:browse"), RELEASES, "browse")
    assert acme.narrowing(literal("/x"))[1] is True  # a prefix a database can be asked
    assert jars.narrowing(literal("/x"))[1] is False  # a pattern it cannot
    assert access.may_somewhere(caller("selector:acme:maven:releases:browse"), RELEASES, "browse")
    assert not access.may_somewhere(caller("selector:acme:maven:releases:browse"), NPM, "browse")


def test_require_answers_as_authorize_does():
    with pytest.raises(ApiError) as nobody:
        access.require(None, RELEASES, ACME_JAR, "read")
    with pytest.raises(ApiError) as anonymous:
        access.require(caller(method="anonymous"), RELEASES, ACME_JAR, "read")
    with pytest.raises(ApiError) as refused:
        access.require(caller("selector:acme:maven:*:read"), RELEASES, OTHER_JAR, "read")
    with pytest.raises(ApiError) as nowhere:
        access.require_somewhere(caller("selector:acme:maven:*:read"), NPM, "read")

    assert (nobody.value.status_code, anonymous.value.status_code) == (401, 401)
    assert (refused.value.status_code, nowhere.value.status_code) == (403, 403)
    assert access.require(caller("selector:acme:maven:*:read"), RELEASES, ACME_JAR, "read")


async def test_a_principal_holds_the_selectors_its_permissions_name_and_no_others(db, make_user):
    db.add_all(
        [
            ContentSelector(name="acme", expression='path =^ "/com/acme/"'),
            ContentSelector(name="other", expression='path =^ "/org/"'),
        ]
    )
    await roles.create_role(db, "acme-readers", "", ["selector:acme:maven:*:read"], [])
    await roles.create_role(db, "plain", "", ["repository:maven:*:read"], [])
    await db.commit()
    acme = await make_user("ada", roles=["acme-readers"])
    plain = await make_user("pat", roles=["plain"])

    held = await build_principal(db, acme, "session")
    none = await build_principal(db, plain, "session")

    assert held.selectors == {"acme": 'path =^ "/com/acme/"'}
    assert none.selectors == {}
    assert await selectors.held(db, ["selector:*:maven:*:read"]) == {
        "acme": 'path =^ "/com/acme/"',
        "other": 'path =^ "/org/"',
    }
    assert await selectors.held(db, ["*", "repository:*:*:read"]) == {}

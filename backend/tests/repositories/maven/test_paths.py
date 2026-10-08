import pytest

from megooarti.repositories.maven.paths import (
    MavenPath,
    allowed_by,
    classify,
    content_type,
    split_checksum,
)

BASE = "com/acme/app/1.0"
SNAP = "com/acme/app/1.0-SNAPSHOT"


def artifact(**fields) -> MavenPath:
    fields.setdefault("group_id", "com.acme")
    fields.setdefault("artifact_id", "app")
    fields.setdefault("version", "1.0")
    return MavenPath("artifact", **fields)


def snapshot(**fields) -> MavenPath:
    return artifact(version="1.0-SNAPSHOT", **fields)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"{BASE}/app-1.0.jar", artifact(extension="jar")),
        (f"{BASE}/app-1.0.pom", artifact(extension="pom")),
        (f"{BASE}/app-1.0-sources.jar", artifact(classifier="sources", extension="jar")),
        (f"{BASE}/app-1.0.tar.gz", artifact(extension="tar.gz")),
        (f"{BASE}/app-1.0-bin.tar.gz", artifact(classifier="bin", extension="tar.gz")),
        (f"{BASE}/app-1.0.jar.asc", artifact(extension="jar.asc")),
        ("acme/app/1.0/app-1.0.jar", artifact(group_id="acme", extension="jar")),
        (
            "com/acme/my.app/1.0.1/my.app-1.0.1.jar",
            artifact(artifact_id="my.app", version="1.0.1", extension="jar"),
        ),
        # A name that fits two readings is read the simplest way, never refused.
        (f"{BASE}/app-1.0.1.jar", artifact(extension="1.jar")),
        (
            "com/acme/app/1.0-20261008.101500-3/app-1.0-20261008.101500-3.jar",
            artifact(version="1.0-20261008.101500-3", extension="jar"),
        ),
    ],
)
def test_release_artifact_paths(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("app-1.0-20261008.101500-3.jar", snapshot(extension="jar", build=("20261008.101500", 3))),
        (
            "app-1.0-20261008.101500-3-sources.jar",
            snapshot(classifier="sources", extension="jar", build=("20261008.101500", 3)),
        ),
        (
            "app-1.0-20261008.101500-12.pom",
            snapshot(extension="pom", build=("20261008.101500", 12)),
        ),
        ("app-1.0-SNAPSHOT.jar", snapshot(extension="jar")),
        ("app-1.0-SNAPSHOT-sources.jar", snapshot(classifier="sources", extension="jar")),
    ],
)
def test_snapshot_artifact_paths(name, expected):
    assert classify(f"{SNAP}/{name}") == expected
    assert classify(f"{SNAP}/{name}").is_snapshot is True


@pytest.mark.parametrize(
    "path",
    [
        "app/1.0/app-1.0.jar",  # no group directory
        f"{BASE}/other-1.0.jar",
        f"{BASE}/app-2.0.jar",
        f"{BASE}/app-1.0",
        f"{BASE}/app-1.0.",
        f"{BASE}/app-1.0-.jar",
        f"{BASE}/app-1.0jar",
        "com.acme/app/1.0/app-1.0.jar",  # a dot in a group directory
        f"{SNAP}/app-1.0-2026-1.jar",
        f"{SNAP}/app-1.0-SNAPSHOTS.jar",
        f"{SNAP}/app-1.0-٢٠٢٦١٠٠٨.١٠١٥٠٠-٣.jar",  # digits, but not ASCII ones
        "com/acme/app/-SNAPSHOT/app--SNAPSHOT.jar",
        f"com/acme/app/{'9' * 256}/app-{'9' * 256}.jar",  # longer than a version may be
        "notes/readme.txt",
        "maven-metadata.xml",
        "deep/archetype-catalog.xml",
        "com.acme/app/maven-metadata.xml",
        "com.acme/app/1.0-SNAPSHOT/maven-metadata.xml",
    ],
)
def test_paths_outside_the_layout_are_other(path):
    assert classify(path) == MavenPath("other")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "com/acme/app/maven-metadata.xml",
            MavenPath(
                "metadata", group_id="com.acme", artifact_id="app", plugin_group="com.acme.app"
            ),
        ),
        ("com/maven-metadata.xml", MavenPath("metadata", plugin_group="com")),
        (
            "com/acme/my.app/maven-metadata.xml",
            MavenPath("metadata", group_id="com.acme", artifact_id="my.app"),
        ),
        (
            f"{SNAP}/maven-metadata.xml",
            MavenPath(
                "snapshot_metadata", group_id="com.acme", artifact_id="app", version="1.0-SNAPSHOT"
            ),
        ),
        # Too shallow to be a version directory: an artifact that happens to be named so.
        (
            "app/1.0-SNAPSHOT/maven-metadata.xml",
            MavenPath("metadata", group_id="app", artifact_id="1.0-SNAPSHOT"),
        ),
    ],
)
def test_metadata_paths(path, expected):
    assert classify(path) == expected
    assert classify(path).is_metadata is True


def test_the_catalog_is_only_at_the_root():
    assert classify("archetype-catalog.xml") == MavenPath("catalog")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/b/app-1.0.jar.md5", ("a/b/app-1.0.jar", "md5")),
        ("a/b/app-1.0.jar.sha1", ("a/b/app-1.0.jar", "sha1")),
        ("a/b/app-1.0.jar.sha256", ("a/b/app-1.0.jar", "sha256")),
        ("a/b/app-1.0.jar.sha512", ("a/b/app-1.0.jar", "sha512")),
        ("a/b/maven-metadata.xml.sha1", ("a/b/maven-metadata.xml", "sha1")),
        ("a/b/app-1.0.jar", ("a/b/app-1.0.jar", None)),
        ("a/b/app-1.0.jar.SHA1", ("a/b/app-1.0.jar.SHA1", None)),
        ("a/b/.sha1", ("a/b/.sha1", None)),
        (".md5", (".md5", None)),
    ],
)
def test_a_checksum_path_names_its_file_and_algorithm(path, expected):
    assert split_checksum(path) == expected


RELEASE = classify(f"{BASE}/app-1.0.jar")
SNAPSHOT_FILE = classify(f"{SNAP}/app-1.0-SNAPSHOT.jar")
ARTIFACT_LEVEL = classify("com/acme/app/maven-metadata.xml")
VERSION_LEVEL = classify(f"{SNAP}/maven-metadata.xml")


@pytest.mark.parametrize(
    ("policy", "parsed", "allowed"),
    [
        ("release", RELEASE, True),
        ("release", SNAPSHOT_FILE, False),
        ("release", ARTIFACT_LEVEL, True),
        ("release", VERSION_LEVEL, False),
        ("release", MavenPath("other"), True),
        ("release", MavenPath("catalog"), True),
        ("snapshot", RELEASE, False),
        ("snapshot", SNAPSHOT_FILE, True),
        ("snapshot", ARTIFACT_LEVEL, True),
        ("snapshot", VERSION_LEVEL, True),
        ("snapshot", MavenPath("other"), True),
        ("mixed", RELEASE, True),
        ("mixed", SNAPSHOT_FILE, True),
        ("mixed", VERSION_LEVEL, True),
    ],
)
def test_the_version_policy(policy, parsed, allowed):
    assert allowed_by(policy, parsed) is allowed


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/app-1.0.pom", "application/xml"),
        ("a/maven-metadata.xml", "application/xml"),
        ("a/app-1.0.jar", "application/java-archive"),
        ("a/app-1.0.war", "application/java-archive"),
        ("a/app-1.0.module", "application/json"),
        ("a/app-1.0.jar.asc", "text/plain"),
        ("a/app-1.0.zip", None),
        ("a/no-extension", None),
    ],
)
def test_content_types_for_the_files_maven_uses(path, expected):
    assert content_type(path) == expected

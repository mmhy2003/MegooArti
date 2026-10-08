from datetime import UTC, datetime, timedelta, timezone

import pytest

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.metadata import (
    InvalidMetadata,
    Metadata,
    Plugin,
    SnapshotVersion,
)
from megooarti.repositories.maven.paths import classify

T1 = datetime(2026, 10, 8, 10, 15, 0, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
SNAP = "com/acme/app/1.0-SNAPSHOT"

ARTIFACT = Metadata(
    group_id="com.acme",
    artifact_id="app",
    versions=("1.0", "1.1"),
    latest="1.1",
    release="1.1",
    last_updated="20261008101500",
)
SNAPSHOT = Metadata(
    group_id="com.acme",
    artifact_id="app",
    version="1.0-SNAPSHOT",
    snapshot_timestamp="20261008.101500",
    snapshot_build=3,
    snapshot_versions=(
        SnapshotVersion("", "jar", "1.0-20261008.101500-3", "20261008101500"),
        SnapshotVersion("sources", "jar", "1.0-20261008.101500-3", "20261008101500"),
    ),
    last_updated="20261008101500",
)
PLUGINS = Metadata(plugins=(Plugin("Acme Plugin", "acme", "acme-maven-plugin"),))


def entry(name: str, when: datetime):
    return classify(f"{SNAP}/{name}"), when


def snapshot_of(*entries) -> Metadata | None:
    return metadata.for_snapshot("com.acme", "app", "1.0-SNAPSHOT", entries)


def test_stamp_is_utc_to_the_second():
    east = timezone(timedelta(hours=3))

    assert metadata.stamp(datetime(2026, 10, 8, 13, 15, 59, 999, tzinfo=east)) == "20261008101559"


def test_artifact_metadata_lists_versions_in_maven_order():
    built = metadata.for_artifact("com.acme", "app", {"1.10": T1, "1.9": T3, "2.0-SNAPSHOT": T2})

    assert built == Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.9", "1.10", "2.0-SNAPSHOT"),
        latest="2.0-SNAPSHOT",
        release="1.10",
        last_updated=metadata.stamp(T3),
    )


def test_artifact_metadata_without_a_release_names_none():
    built = metadata.for_artifact("com.acme", "app", {"1.0-SNAPSHOT": T1})

    assert (built.latest, built.release) == ("1.0-SNAPSHOT", "")


def test_metadata_for_nothing_is_nothing():
    assert metadata.for_artifact("com.acme", "app", {}) is None
    assert snapshot_of() is None


def test_plugins_alone_make_a_group_document():
    built = metadata.for_artifact("com", "acme", {}, PLUGINS.plugins)

    assert built == PLUGINS


def test_an_artifact_that_is_also_a_group_carries_both():
    built = metadata.for_artifact("com", "acme", {"1.0": T1}, PLUGINS.plugins)

    assert (built.group_id, built.artifact_id, built.versions) == ("com", "acme", ("1.0",))
    assert built.plugins == PLUGINS.plugins


def test_snapshot_metadata_points_at_the_highest_build():
    built = snapshot_of(
        entry("app-1.0-20261008.101500-1.jar", T1),
        entry("app-1.0-20261008.101500-1.pom", T1),
        entry("app-1.0-20261008.101500-1-sources.jar", T1),
        entry("app-1.0-20261008.111500-2.jar", T2),
        entry("app-1.0-20261008.111500-2.pom", T2),
    )

    assert (built.group_id, built.artifact_id, built.version) == (
        "com.acme",
        "app",
        "1.0-SNAPSHOT",
    )
    assert (built.snapshot_timestamp, built.snapshot_build) == ("20261008.111500", 2)
    assert built.last_updated == metadata.stamp(T2)
    assert built.snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-20261008.111500-2", metadata.stamp(T2)),
        SnapshotVersion("", "pom", "1.0-20261008.111500-2", metadata.stamp(T2)),
        SnapshotVersion("sources", "jar", "1.0-20261008.101500-1", metadata.stamp(T1)),
    )


def test_the_build_number_decides_before_the_timestamp():
    built = snapshot_of(
        entry("app-1.0-20261008.120000-2.jar", T1),
        entry("app-1.0-20261008.090000-3.jar", T2),
    )

    assert (built.snapshot_timestamp, built.snapshot_build) == ("20261008.090000", 3)


def test_old_style_snapshot_names_are_listed_with_the_literal_version():
    built = snapshot_of(entry("app-1.0-SNAPSHOT.jar", T1), entry("app-1.0-SNAPSHOT.pom", T2))

    assert (built.snapshot_timestamp, built.snapshot_build) == ("", None)
    assert built.snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-SNAPSHOT", metadata.stamp(T1)),
        SnapshotVersion("", "pom", "1.0-SNAPSHOT", metadata.stamp(T2)),
    )


def test_a_timestamped_build_wins_over_an_old_style_name():
    built = snapshot_of(
        entry("app-1.0-SNAPSHOT.jar", T2), entry("app-1.0-20261008.101500-1.jar", T1)
    )

    assert built.snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-20261008.101500-1", metadata.stamp(T1)),
    )
    assert built.last_updated == metadata.stamp(T2)


def test_an_artifact_document_is_written_in_mavens_layout():
    assert metadata.serialise(ARTIFACT).decode() == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<metadata>\n"
        "  <groupId>com.acme</groupId>\n"
        "  <artifactId>app</artifactId>\n"
        "  <versioning>\n"
        "    <latest>1.1</latest>\n"
        "    <release>1.1</release>\n"
        "    <versions>\n"
        "      <version>1.0</version>\n"
        "      <version>1.1</version>\n"
        "    </versions>\n"
        "    <lastUpdated>20261008101500</lastUpdated>\n"
        "  </versioning>\n"
        "</metadata>\n"
    )


def test_a_snapshot_document_declares_the_newer_model():
    assert b'<metadata modelVersion="1.1.0">' in metadata.serialise(SNAPSHOT)
    assert b"<buildNumber>3</buildNumber>" in metadata.serialise(SNAPSHOT)
    assert b"modelVersion" not in metadata.serialise(ARTIFACT)


@pytest.mark.parametrize("original", [ARTIFACT, SNAPSHOT, PLUGINS])
def test_a_document_survives_being_written_and_read(original):
    assert metadata.parse(metadata.serialise(original)) == original


def test_special_characters_are_escaped():
    awkward = Metadata(plugins=(Plugin("A & B <plugin>", "ab", "ab-maven-plugin"),))

    written = metadata.serialise(awkward)

    assert b"A &amp; B &lt;plugin&gt;" in written
    assert metadata.parse(written) == awkward


WRITTEN_BY_MAVEN = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://maven.apache.org/METADATA/1.1.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <groupId>com.acme</groupId>
  <artifactId>app</artifactId>
  <versioning>
    <latest>1.1</latest>
    <release>1.1</release>
    <versions>
      <version> 1.0 </version>
      <version>1.1</version>
      <version></version>
    </versions>
    <lastUpdated>20261008101500</lastUpdated>
  </versioning>
  <plugins>
    <plugin>
      <name>Acme Plugin</name>
      <prefix>acme</prefix>
      <artifactId>acme-maven-plugin</artifactId>
    </plugin>
    <plugin>
      <name>No prefix</name>
      <artifactId>broken-plugin</artifactId>
    </plugin>
  </plugins>
</metadata>
"""


def test_a_document_written_by_maven_is_read():
    assert metadata.parse(WRITTEN_BY_MAVEN) == Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.0", "1.1"),
        latest="1.1",
        release="1.1",
        last_updated="20261008101500",
        plugins=PLUGINS.plugins,
    )


EXPANDING = b"""<?xml version="1.0"?>
<!DOCTYPE metadata [
  <!ENTITY a "aaaaaaaaaa">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
]>
<metadata><groupId>&b;</groupId></metadata>"""
EXTERNAL = b"""<!DOCTYPE metadata [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<metadata><groupId>&x;</groupId></metadata>"""


@pytest.mark.parametrize("document", [EXPANDING, EXTERNAL, b"<!DOCTYPE metadata><metadata/>"])
def test_a_document_with_a_doctype_is_refused(document):
    with pytest.raises(InvalidMetadata, match="DOCTYPE"):
        metadata.parse(document)


@pytest.mark.parametrize(
    "document",
    [
        b"",
        b"not xml",
        b"<metadata>",
        b"<metadata></wrong>",
        b"<project/>",
        b"\x00\x01\x02",
        "<metadata>".encode("utf-16"),
    ],
)
def test_a_document_that_is_not_metadata_is_refused(document):
    with pytest.raises(InvalidMetadata):
        metadata.parse(document)


def test_overlong_fields_are_ignored():
    long = "x" * 256
    document = (
        f"<metadata><groupId>{long}</groupId>"
        f"<versioning><versions><version>{long}</version><version>1.0</version></versions>"
        f"</versioning><plugins><plugin><prefix>{long}</prefix><artifactId>p</artifactId>"
        "</plugin></plugins></metadata>"
    )

    assert metadata.parse(document.encode()) == Metadata(versions=("1.0",))


@pytest.mark.parametrize(("written", "expected"), [("7", 7), ("seven", None), ("9" * 30, None)])
def test_a_build_number_must_be_a_small_number(written, expected):
    document = (
        "<metadata><versioning><snapshot><timestamp>20261008.101500</timestamp>"
        f"<buildNumber>{written}</buildNumber></snapshot></versioning></metadata>"
    )

    assert metadata.parse(document.encode()).snapshot_build == expected


def test_uploaded_plugins_replace_stored_ones_for_the_same_artifact():
    stored = (Plugin("Old", "old", "a-plugin"), Plugin("Kept", "kept", "b-plugin"))
    uploaded = (Plugin("New", "new", "a-plugin"), Plugin("Added", "added", "c-plugin"))

    assert metadata.merge_plugins(stored, uploaded) == (
        Plugin("Added", "added", "c-plugin"),
        Plugin("Kept", "kept", "b-plugin"),
        Plugin("New", "new", "a-plugin"),
    )

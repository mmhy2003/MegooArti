import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from megooarti.repositories.npm import documents
from megooarti.repositories.npm.documents import (
    ChecksumMismatch,
    Found,
    InvalidPackage,
    Version,
)

TARBALL = b"\x1f\x8b not really a tarball"
SHA1 = hashlib.sha1(TARBALL).hexdigest()
SHA256 = hashlib.sha256(TARBALL).hexdigest()
SHA512 = hashlib.sha512(TARBALL).hexdigest()
INTEGRITY = "sha512-" + base64.b64encode(hashlib.sha512(TARBALL).digest()).decode()
T1 = datetime(2026, 10, 8, 10, 15, 0, 123456, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
BASE = "https://repo.example/repository/npm"


def manifest(package: str = "left-pad", version: str = "1.0.0", **extra) -> dict:
    dist = {"shasum": SHA1, "integrity": INTEGRITY, "tarball": "http://client.example/x.tgz"}
    return {"name": package, "version": version, "dist": dist, **extra}


def publish(package: str = "left-pad", version: str = "1.0.0", **changes) -> dict:
    """What `npm publish` sends for one version."""
    body = {
        "_id": package,
        "name": package,
        "dist-tags": {"latest": version},
        "versions": {version: manifest(package, version)},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(TARBALL).decode(),
                "length": len(TARBALL),
            }
        },
    }
    body.update(changes)
    return body


def read(body, package: str = "left-pad"):
    return documents.read_upload(package, json.dumps(body).encode())


def stored(version: str, when: datetime = T1, **extra) -> Version:
    kept = documents.stored_manifest(manifest(version=version, **extra), sha1=SHA1, sha512=SHA512)
    return Version(version=version, manifest=kept, created=when, modified=when)


def test_a_publish_is_read_into_its_releases():
    upload = read(publish())

    assert [release.version for release in upload.releases] == ["1.0.0"]
    assert upload.releases[0].data == TARBALL
    assert upload.releases[0].manifest["name"] == "left-pad"
    assert upload.tags == {"latest": "1.0.0"}


def test_a_scoped_publish_names_its_tarball_with_or_without_the_scope():
    as_npm_sends = read(publish("@acme/widget"), "@acme/widget")
    body = publish("@acme/widget")
    body["_attachments"] = {"widget-1.0.0.tgz": body["_attachments"]["@acme/widget-1.0.0.tgz"]}

    assert as_npm_sends.releases[0].data == TARBALL
    assert read(body, "@acme/widget").releases[0].data == TARBALL


def test_a_body_without_attachments_is_an_update():
    body = publish()
    del body["_attachments"]

    upload = read(body)

    assert upload.releases == ()
    assert upload.document["versions"].keys() == {"1.0.0"}


def with_manifest(**changes) -> dict:
    body = publish()
    body["versions"]["1.0.0"].update(changes)
    return body


def with_attachment(**changes) -> dict:
    body = publish()
    body["_attachments"]["left-pad-1.0.0.tgz"].update(changes)
    return body


@pytest.mark.parametrize(
    "body",
    [
        [],
        "a string",
        publish(name="other"),
        publish(**{"dist-tags": ["latest"]}),
        publish(**{"dist-tags": {"": "1.0.0"}}),
        publish(**{"dist-tags": {"a/b": "1.0.0"}}),
        publish(**{"dist-tags": {"latest": 1}}),
        publish(versions={}),
        publish(versions=[]),
        publish(versions={"1.0.0": "not an object"}),
        publish(versions={"1.0": manifest(version="1.0")}),
        publish(versions={"1.0.0": manifest(version="2.0.0")}),
        publish(versions={"1.0.0": manifest(package="other")}),
        publish(_attachments={"other-1.0.0.tgz": {"data": "aGk="}}),
        publish(_attachments=["left-pad-1.0.0.tgz"]),
        with_attachment(data="not base64!"),
        with_attachment(data=None),
        with_manifest(readme="x" * (1024 * 1024)),
    ],
)
def test_a_body_that_is_not_a_package_is_refused(body):
    with pytest.raises(InvalidPackage):
        read(body)


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"\xff\xfe", b"[" * 100_000],
    ids=["empty", "text", "not-utf8", "nested-too-deeply"],
)
def test_a_body_that_is_not_json_is_refused(raw):
    with pytest.raises(InvalidPackage):
        documents.read_upload("left-pad", raw)


def test_a_tarball_shorter_than_declared_is_a_mismatch():
    with pytest.raises(ChecksumMismatch, match="length"):
        read(with_attachment(length=len(TARBALL) + 1))


def test_declared_digests_are_checked():
    actual = {"sha1": SHA1, "sha256": SHA256, "sha512": SHA512}
    sha256 = "sha256-" + base64.b64encode(hashlib.sha256(TARBALL).digest()).decode()

    documents.verify(manifest(), **actual)
    documents.verify({"dist": {"shasum": SHA1.upper()}}, **actual)
    documents.verify({"dist": {"integrity": f"md5-ignored {sha256} {INTEGRITY}"}}, **actual)
    documents.verify({"dist": {}}, **actual)
    documents.verify({}, **actual)
    documents.verify({"dist": "odd"}, **actual)


@pytest.mark.parametrize(
    ("dist", "check"),
    [
        ({"shasum": "0" * 40}, "shasum"),
        ({"integrity": "sha512-" + base64.b64encode(b"\x00" * 64).decode()}, "integrity"),
        ({"integrity": "sha512-not-base64!"}, "integrity"),
        (
            {"shasum": SHA1, "integrity": "sha1-" + base64.b64encode(b"\x00" * 20).decode()},
            "integrity",
        ),
    ],
)
def test_a_wrong_digest_is_a_mismatch(dist, check):
    with pytest.raises(ChecksumMismatch, match=check):
        documents.verify({"dist": dist}, sha1=SHA1, sha256=SHA256, sha512=SHA512)


def test_the_stored_manifest_has_our_digests_and_no_link():
    sent = manifest(
        description="pads", dist={"shasum": "f" * 40, "tarball": "http://x", "fileCount": 3}
    )

    kept = documents.stored_manifest(sent, sha1=SHA1, sha512=SHA512)

    assert kept["dist"] == {"fileCount": 3, "shasum": SHA1, "integrity": INTEGRITY}
    assert (kept["description"], kept["version"]) == ("pads", "1.0.0")
    assert sent["dist"]["shasum"] == "f" * 40  # what was sent is not changed


def test_tags_shown_point_at_versions_that_exist():
    stored_tags = {"latest": "1.0.0", "beta": "2.0.0-beta.1", "old": "0.1.0"}

    shown = documents.effective_tags(stored_tags, ["1.0.0", "2.0.0-beta.1"])

    assert shown == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}
    assert list(shown)[0] == "latest"


def test_latest_falls_back_to_the_highest_version():
    assert documents.effective_tags({}, ["1.0.0", "1.2.0", "1.1.0"]) == {"latest": "1.2.0"}
    assert documents.effective_tags({"latest": "9.9.9"}, ["1.0.0"]) == {"latest": "1.0.0"}
    assert documents.effective_tags({"latest": "1.0.0"}, []) == {}


def test_merging_tags_applies_what_was_sent():
    merged = documents.merge_tags(
        {"latest": "1.0.0"}, {"beta": "2.0.0-beta.1"}, ["1.0.0"], ["1.0.0", "2.0.0-beta.1"]
    )

    assert merged == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}


def test_latest_does_not_jump_to_a_prerelease_because_its_version_was_removed_earlier():
    # 2.0.0 was tagged latest and has been removed; 1.0.0 remains. A beta is published.
    merged = documents.merge_tags(
        {"latest": "2.0.0"}, {"beta": "3.0.0-beta.1"}, ["1.0.0"], ["1.0.0", "3.0.0-beta.1"]
    )

    assert merged == {"latest": "1.0.0", "beta": "3.0.0-beta.1"}


def test_the_first_publish_decides_latest():
    assert documents.merge_tags({}, {"next": "1.0.0-rc.1"}, [], ["1.0.0-rc.1"]) == {
        "latest": "1.0.0-rc.1",
        "next": "1.0.0-rc.1",
    }


def test_the_package_document():
    built = documents.document(
        "left-pad",
        [stored("1.10.0", T2, description="newer"), stored("1.9.0", T1, description="older")],
        {"latest": "1.10.0"},
        BASE,
    )

    assert (built["_id"], built["name"]) == ("left-pad", "left-pad")
    assert list(built["versions"]) == ["1.9.0", "1.10.0"]
    assert built["dist-tags"] == {"latest": "1.10.0"}
    newest = built["versions"]["1.10.0"]
    assert newest["_id"] == "left-pad@1.10.0"
    assert newest["dist"] == {
        "shasum": SHA1,
        "integrity": INTEGRITY,
        "tarball": f"{BASE}/left-pad/-/left-pad-1.10.0.tgz",
    }
    assert built["time"] == {
        "created": "2026-10-08T10:15:00.123Z",
        "modified": "2026-10-08T11:15:00.123Z",
        "1.9.0": "2026-10-08T10:15:00.123Z",
        "1.10.0": "2026-10-08T11:15:00.123Z",
    }
    assert built["description"] == "newer"  # copied from the latest version
    assert built["_rev"].startswith("2-")


def test_a_scoped_document_links_to_the_scoped_path():
    kept = documents.stored_manifest(manifest("@acme/widget"), sha1=SHA1, sha512=SHA512)
    built = documents.document("@acme/widget", [Version("1.0.0", kept, T1, T1)], {}, BASE)

    assert (
        built["versions"]["1.0.0"]["dist"]["tarball"] == f"{BASE}/@acme/widget/-/widget-1.0.0.tgz"
    )
    assert built["versions"]["1.0.0"]["_id"] == "@acme/widget@1.0.0"


def test_a_package_without_versions_has_no_document():
    assert documents.document("left-pad", [], {"latest": "1.0.0"}, BASE) is None
    assert documents.render("left-pad", [], {}, BASE) is None


def test_the_revision_changes_with_the_document():
    one = documents.document("left-pad", [stored("1.0.0")], {}, BASE)
    same = documents.document("left-pad", [stored("1.0.0")], {}, BASE)
    deprecated = documents.document("left-pad", [stored("1.0.0", deprecated="no")], {}, BASE)

    assert one["_rev"] == same["_rev"]
    assert one["_rev"] != deprecated["_rev"]


def test_rendering_gives_bytes_an_etag_and_a_time():
    rendered = documents.render("left-pad", [stored("1.0.0", T1), stored("1.1.0", T2)], {}, BASE)

    assert json.loads(rendered.data)["dist-tags"] == {"latest": "1.1.0"}
    assert rendered.etag == hashlib.sha256(rendered.data).hexdigest()
    assert rendered.modified == T2


def test_one_manifest_by_version_or_by_tag():
    built = documents.document(
        "left-pad", [stored("1.0.0"), stored("1.1.0")], {"old": "1.0.0"}, BASE
    )

    assert documents.manifest_of(built, "1.0.0")["version"] == "1.0.0"
    assert documents.manifest_of(built, "latest")["version"] == "1.1.0"
    assert documents.manifest_of(built, "old")["version"] == "1.0.0"
    assert documents.manifest_of(built, "9.9.9") is None


def test_an_update_names_what_was_deprecated_and_what_was_removed():
    held = {
        "1.0.0": {"version": "1.0.0"},
        "1.1.0": {"version": "1.1.0", "deprecated": "old"},
        "1.2.0": {"version": "1.2.0", "deprecated": "keep"},
        "2.0.0": {"version": "2.0.0"},
    }
    sent = {
        "versions": {
            "1.0.0": {"deprecated": "use 2"},
            "1.1.0": {"deprecated": ""},
            "1.2.0": {"deprecated": "keep", "description": "ignored"},
        }
    }

    plan = documents.update_plan(held, sent)

    assert plan.deprecations == {"1.0.0": "use 2", "1.1.0": None}
    assert plan.removals == ("2.0.0",)


def test_an_update_that_says_nothing_about_versions_removes_nothing():
    held = {"1.0.0": {"version": "1.0.0"}}

    assert documents.update_plan(held, {}).removals == ()
    assert documents.update_plan(held, {"versions": None}).removals == ()
    assert documents.update_plan(held, {"versions": {}}).removals == ("1.0.0",)


def test_a_deprecation_message_has_a_limit():
    with pytest.raises(InvalidPackage):
        documents.update_plan({"1.0.0": {}}, {"versions": {"1.0.0": {"deprecated": "x" * 1025}}})


def test_setting_and_clearing_a_deprecation():
    kept = {"version": "1.0.0", "deprecated": "old"}

    assert documents.deprecated(kept, "new") == {"version": "1.0.0", "deprecated": "new"}
    assert documents.deprecated(kept, None) == {"version": "1.0.0"}
    assert kept == {"version": "1.0.0", "deprecated": "old"}


def test_search_results_are_in_the_shape_npm_reads():
    found = [Found("@acme/widget", "2.0.0", "A widget", T1), Found("left-pad", "1.3.0", "", T2)]

    results = documents.search_results(found, 7, T2)

    assert results["total"] == 7
    assert [entry["package"]["name"] for entry in results["objects"]] == [
        "@acme/widget",
        "left-pad",
    ]
    first = results["objects"][0]["package"]
    assert (first["version"], first["description"]) == ("2.0.0", "A widget")
    assert first["date"] == "2026-10-08T10:15:00.123Z"
    assert (first["keywords"], first["maintainers"]) == ([], [])


@pytest.mark.parametrize(
    ("tag", "valid"),
    [
        ("latest", True),
        ("next-11", True),
        ("", False),
        ("a/b", False),
        ("x" * 215, False),
        ("a\nb", False),
    ],
)
def test_tag_names(tag, valid):
    assert documents.is_valid_tag(tag) is valid


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": NaN}',
        b'{"a": -Infinity}',
        b'{"a": 1e999}',
        b'{"a": "nul \\u0000 inside"}',
        b'{"nul \\u0000 key": 1}',
        b'{"a": ["deep", {"b": "half a pair \\ud800"}]}',
        b'{"\\udfff": 1}',
    ],
    ids=["nan", "infinity", "overflow", "nul", "nul-key", "lone-surrogate", "surrogate-key"],
)
def test_json_that_cannot_be_stored_is_refused(raw):
    with pytest.raises(InvalidPackage):
        documents.loads(raw)


def test_ordinary_json_is_read():
    raw = b'{"emoji": "\\ud83d\\ude00", "number": 1.5, "big": 123456789012345678901234567890}'

    assert documents.loads(raw) == {
        "emoji": "\U0001f600",
        "number": 1.5,
        "big": 123456789012345678901234567890,
    }
    assert documents.loads(b"[" * 500 + b"]" * 500) is not None


def test_a_publish_is_read_without_keeping_the_encoded_tarballs():
    upload = read(publish())

    assert "_attachments" not in upload.document
    assert upload.releases[0].data == TARBALL


def test_empty_attachments_are_refused_not_taken_for_an_update():
    with pytest.raises(InvalidPackage):
        read(publish(_attachments={}))


def test_too_many_dist_tags_are_refused():
    tags = {f"tag-{number}": "1.0.0" for number in range(251)}

    with pytest.raises(InvalidPackage):
        read(publish(**{"dist-tags": tags}))
    assert len(read(publish(**{"dist-tags": dict(list(tags.items())[:250])})).tags) == 250


def test_an_update_naming_a_version_that_is_not_stored_is_refused():
    with pytest.raises(InvalidPackage):
        documents.update_plan({"1.0.0": {}}, {"versions": {"1.0.0": {}, "2.0.0": {}}})


def test_the_readme_is_shown_once_not_with_every_version():
    built = documents.document(
        "left-pad",
        [stored("1.0.0", readme="first readme"), stored("1.1.0", readme="latest readme")],
        {},
        BASE,
    )

    assert built["readme"] == "latest readme"
    assert all("readme" not in manifest for manifest in built["versions"].values())


def test_what_several_repositories_hold_is_combined_and_the_earlier_one_wins():
    first = ([stored("1.0.0", description="from the first")], {"latest": "1.0.0"})
    second = (
        [stored("1.0.0", T2, description="from the second"), stored("2.0.0-beta.1", T2)],
        {"latest": "1.0.0", "beta": "2.0.0-beta.1", "gone": "9.9.9"},
    )

    versions, tags = documents.combine([first, second])

    assert [version.version for version in versions] == ["1.0.0", "2.0.0-beta.1"]
    assert versions[0].manifest["description"] == "from the first"
    assert tags == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}


def test_the_first_repositorys_latest_is_the_latest_even_when_a_later_one_is_higher():
    first = ([stored("1.0.0")], {})  # no tags stored: its highest version is its latest
    second = ([stored("3.0.0")], {"latest": "3.0.0", "next": "3.0.0"})

    versions, tags = documents.combine([first, second])
    built = documents.document("left-pad", versions, tags, BASE)

    assert tags == {"latest": "1.0.0", "next": "3.0.0"}
    assert list(built["versions"]) == ["1.0.0", "3.0.0"]
    assert built["dist-tags"] == {"latest": "1.0.0", "next": "3.0.0"}


def test_combining_one_repository_changes_nothing():
    only = ([stored("1.0.0"), stored("1.1.0", T2)], {"latest": "1.0.0"})

    versions, tags = documents.combine([only])

    assert documents.render("left-pad", versions, tags, BASE) == documents.render(
        "left-pad", only[0], only[1], BASE
    )
    assert documents.combine([]) == ([], {})


def served(*versions: str, at: str = "https://registry.example", **extra) -> bytes:
    """A package document as another registry serves it."""
    body = {
        "_id": "left-pad",
        "name": "left-pad",
        "dist-tags": {"latest": versions[-1]},
        "versions": {
            version: {
                "name": "left-pad",
                "version": version,
                "dist": {"shasum": SHA1, "tarball": f"{at}/left-pad/-/left-pad-{version}.tgz"},
            }
            for version in versions
        },
        "time": {version: "2020-01-01T00:00:00.000Z" for version in versions},
        **extra,
    }
    return json.dumps(body).encode()


def test_the_documents_of_several_registries_are_merged_and_the_earlier_one_wins():
    first = served("1.0.0", "1.1.0", description="from the first", readme="# first")
    second = served("1.1.0", "2.0.0", at="https://other.example/npm", description="second")
    second = second.replace(b'"2020-01-01', b'"2024-06-01')

    merged = documents.merge_remote("left-pad", [first, second], BASE)

    body = json.loads(merged.data)
    assert merged.used == (0, 1)
    assert merged.etag == hashlib.sha256(merged.data).hexdigest()
    assert list(body["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]
    assert body["dist-tags"] == {"latest": "1.1.0"}
    assert (body["description"], body["readme"]) == ("from the first", "# first")
    assert body["time"] == {
        "1.0.0": "2020-01-01T00:00:00.000Z",
        "1.1.0": "2020-01-01T00:00:00.000Z",
        "2.0.0": "2024-06-01T00:00:00.000Z",
    }
    assert [version["dist"]["tarball"] for version in body["versions"].values()] == [
        f"{BASE}/left-pad/-/left-pad-{version}.tgz" for version in ("1.0.0", "1.1.0", "2.0.0")
    ]


def test_merged_tags_point_at_versions_and_latest_is_always_there():
    first = served("1.0.0", **{"dist-tags": {"next": "1.0.0", "broken": "7.7.7", "odd": 3}})
    second = served("0.9.0", **{"dist-tags": {"latest": "0.9.0", "next": "0.9.0"}})

    body = json.loads(documents.merge_remote("left-pad", [first, second], BASE).data)

    # `next` is the first one's; `latest` is the only one set, by the second.
    assert body["dist-tags"] == {"latest": "0.9.0", "next": "1.0.0"}


@pytest.mark.parametrize(
    "unreadable",
    [b"not json", b"[]", b'{"name":"left-pad"}', b'{"versions":[]}', b'{"versions":{"1.0.0":NaN}}'],
)
def test_a_document_that_cannot_be_read_is_left_out_of_the_merge(unreadable):
    good, other = served("1.0.0"), served("2.0.0")

    three = documents.merge_remote("left-pad", [good, unreadable, other], BASE)
    two = documents.merge_remote("left-pad", [unreadable, good], BASE)

    assert three.used == (0, 2)
    assert list(json.loads(three.data)["versions"]) == ["1.0.0", "2.0.0"]
    assert (two.data, two.used) == (None, (1,))  # one is left: there is nothing to merge


def test_fewer_than_two_documents_are_not_read_at_all():
    assert documents.merge_remote("left-pad", [b"not json"], BASE) == documents.Merged(
        None, "", (0,)
    )
    assert documents.merge_remote("left-pad", [], BASE) == documents.Merged(None, "", ())


def test_odd_parts_of_a_remote_document_do_not_break_the_merge():
    first = served("1.0.0", time="yesterday", **{"dist-tags": None})
    second = served("2.0.0", maintainers=[{"name": "someone"}])

    body = json.loads(documents.merge_remote("left-pad", [first, second], BASE).data)

    assert list(body["versions"]) == ["1.0.0", "2.0.0"]
    assert body["time"] == {"2.0.0": "2020-01-01T00:00:00.000Z"}
    assert body["dist-tags"] == {"latest": "2.0.0"}
    assert "maintainers" not in body  # everything else is the first one's

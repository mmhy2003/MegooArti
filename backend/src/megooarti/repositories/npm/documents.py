"""npm package documents: read what a client sends, and build what a client reads.

Pure functions: no database, no files, no clock.
"""

import base64
import binascii
import hashlib
import json
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from megooarti.repositories.npm import paths, semver
from megooarti.repositories.npm.rewrite import rewrite

# A manifest is stored with its component and repeated in every package document.
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DEPRECATION_LENGTH = 1024
_MAX_TAG_LENGTH = 214
# The tags are read with every package document, so there cannot be many.
MAX_TAGS = 250
# What the package document repeats at the top from the latest version's manifest.
_COPIED = (
    "description",
    "readme",
    "license",
    "repository",
    "homepage",
    "keywords",
    "author",
    "maintainers",
    "bugs",
)
# The digests a blob store computes, by the names npm's `integrity` uses.
_INTEGRITY = ("sha1", "sha256", "sha512")


class InvalidPackage(Exception):
    """What was sent is not a package this registry can take. The message says why."""


class ChecksumMismatch(Exception):
    """A tarball is not the one its manifest describes. The message names the check."""


@dataclass(frozen=True)
class Release:
    """One version in a publish: its manifest and its tarball."""

    version: str
    manifest: dict[str, Any]
    data: bytes


@dataclass(frozen=True)
class Upload:
    """A body sent to a package's address. `releases` is empty when it is an update."""

    document: dict[str, Any]
    releases: tuple[Release, ...]
    tags: dict[str, str] | None  # the dist-tags it carries, if it carries any


@dataclass(frozen=True)
class Version:
    """A stored version: its manifest, and when it was published and last changed."""

    version: str
    manifest: dict[str, Any]
    created: datetime
    modified: datetime


@dataclass(frozen=True)
class Rendered:
    """A document as bytes, with what a response needs to say about it."""

    data: bytes
    etag: str
    modified: datetime


@dataclass(frozen=True)
class Update:
    """What an update asks for, compared with what is stored."""

    deprecations: dict[str, str | None]  # version -> the new message, or None to clear it
    removals: tuple[str, ...]


@dataclass(frozen=True)
class Found:
    """One search result."""

    name: str
    version: str
    description: str
    date: datetime


def dumps(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _refuse_constant(name: str) -> Any:
    raise ValueError(name)  # NaN and the infinities are not JSON, and JSONB refuses them


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)  # 1e999 reads as infinity
    return value


def _check_storable(value: Any) -> None:
    """Refuse text that cannot be kept: PostgreSQL has no NUL, and JSON no half pair."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if "\x00" in item:
                raise InvalidPackage("it contains a NUL character")
            if not item.isascii():
                try:
                    item.encode("utf-8")
                except UnicodeEncodeError:
                    raise InvalidPackage("it contains text that is not valid Unicode") from None
        elif isinstance(item, dict):
            pending.extend(item)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def loads(raw: bytes, what: str = "the body") -> Any:
    """Parse JSON a client sent, refusing what could not be stored. Raises InvalidPackage."""
    try:
        value = json.loads(raw, parse_constant=_refuse_constant, parse_float=_finite)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise InvalidPackage(f"{what} is not JSON") from None
    _check_storable(value)
    return value


def iso(moment: datetime) -> str:
    """A time as npm writes it: 2026-10-08T10:15:00.000Z."""
    moment = moment.astimezone(UTC)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


def _tags(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidPackage("dist-tags is not an object")
    if len(value) > MAX_TAGS:
        raise InvalidPackage(f"it has more than {MAX_TAGS} dist-tags")
    for tag, version in value.items():
        if not is_valid_tag(tag) or not isinstance(version, str):
            raise InvalidPackage(f"the dist-tag {tag!r} is not valid")
    return dict(value)


def is_valid_tag(tag: str) -> bool:
    return 0 < len(tag) <= _MAX_TAG_LENGTH and "/" not in tag and tag.isprintable()


def _attachment(attachments: dict[str, Any], package: str, version: str) -> bytes:
    """The tarball sent for a version. npm names it with the scope; others without."""
    names = (f"{package}-{version}.tgz", paths.tarball_filename(package, version))
    found = next((attachments[name] for name in names if name in attachments), None)
    if not isinstance(found, dict) or not isinstance(found.get("data"), str):
        raise InvalidPackage(f"there is no tarball for version {version}")
    try:
        data = base64.b64decode(found["data"], validate=True)
    except (binascii.Error, ValueError):
        raise InvalidPackage(f"the tarball for version {version} is not base64") from None
    length = found.get("length")
    if isinstance(length, int) and not isinstance(length, bool) and length != len(data):
        raise ChecksumMismatch("length")
    return data


def check_version(package: str, version: str, manifest: Any) -> None:
    """Check one version a publish carries, by its manifest. Raises InvalidPackage."""
    if not semver.is_valid(version):
        raise InvalidPackage(f"{version!r} is not a valid version")
    if not isinstance(manifest, dict):
        raise InvalidPackage(f"the manifest of version {version} is not an object")
    if manifest.get("name") != package or manifest.get("version") != version:
        raise InvalidPackage(f"the manifest of version {version} names something else")
    if len(dumps(manifest)) > MAX_MANIFEST_BYTES:
        raise InvalidPackage(f"the manifest of version {version} is larger than 1 MiB")


def read_upload(package: str, raw: bytes) -> Upload:
    """Read and check a body sent to a package's address.

    Raises InvalidPackage, or ChecksumMismatch if a tarball is not as long as declared.
    """
    document = loads(raw)
    if not isinstance(document, dict):
        raise InvalidPackage("the body is not an object")
    if document.get("name") != package:
        raise InvalidPackage("its name is not the package it was sent to")
    tags = _tags(document.get("dist-tags"))
    if "_attachments" not in document:
        return Upload(document=document, releases=(), tags=tags)

    # Attachments that are present but empty are a broken publish, not an update: taken
    # for an update, a body listing one new version would remove every other.
    attachments, versions = document["_attachments"], document.get("versions")
    if not isinstance(attachments, dict) or not attachments:
        raise InvalidPackage("its attachments are empty")
    if not isinstance(versions, dict) or not versions:
        raise InvalidPackage("it has attachments but no versions")
    releases = []
    for version, manifest in versions.items():
        check_version(package, version, manifest)
        data = _attachment(attachments, package, version)
        releases.append(Release(version=version, manifest=manifest, data=data))
    # The tarballs are decoded now; their encoded copies need not stay in memory.
    rest = {key: value for key, value in document.items() if key != "_attachments"}
    return Upload(document=rest, releases=tuple(releases), tags=tags)


def _hex_of(encoded: str) -> str | None:
    try:
        return base64.b64decode(encoded, validate=True).hex()
    except (binascii.Error, ValueError):
        return None


def verify(manifest: Mapping[str, Any], *, sha1: str, sha256: str, sha512: str) -> None:
    """Check a tarball's digests against what its manifest declares. Raises ChecksumMismatch.

    Only what is declared is checked, and only in the algorithms a blob store computes.
    """
    actual = {"sha1": sha1, "sha256": sha256, "sha512": sha512}
    dist = manifest.get("dist")
    if not isinstance(dist, dict):
        return
    shasum = dist.get("shasum")
    if isinstance(shasum, str) and shasum.lower() != sha1:
        raise ChecksumMismatch("shasum")
    integrity = dist.get("integrity")
    for entry in integrity.split() if isinstance(integrity, str) else ():
        algorithm, _, encoded = entry.partition("-")
        if algorithm in _INTEGRITY and _hex_of(encoded) != actual[algorithm]:
            raise ChecksumMismatch("integrity")


def stored_manifest(manifest: Mapping[str, Any], *, sha1: str, sha512: str) -> dict[str, Any]:
    """A manifest as it is kept: without its link, and with the digests computed here."""
    dist = manifest.get("dist")
    kept = {} if not isinstance(dist, dict) else {k: v for k, v in dist.items() if k != "tarball"}
    kept["shasum"] = sha1
    kept["integrity"] = "sha512-" + base64.b64encode(bytes.fromhex(sha512)).decode()
    return {**manifest, "dist": kept}


def effective_tags(stored: Mapping[str, str], versions: Collection[str]) -> dict[str, str]:
    """The dist-tags to show: those that point at a version that exists, and `latest`.

    If nothing valid is tagged `latest`, the highest version is.
    """
    latest = stored.get("latest")
    if latest not in versions:
        latest = semver.highest(versions)
    if latest is None:
        return {}
    others = {
        tag: stored[tag] for tag in sorted(stored) if tag != "latest" and stored[tag] in versions
    }
    return {"latest": latest, **others}


def merge_tags(
    stored: Mapping[str, str],
    incoming: Mapping[str, str] | None,
    before: Collection[str],
    after: Collection[str],
) -> dict[str, str]:
    """The dist-tags to keep after a change.

    `before` and `after` are the versions that existed before it and exist after it.
    The stored tags are first made true of `before`, so that `latest` does not jump to
    a version only because the one it named was removed earlier.
    """
    merged = effective_tags(stored, before)
    merged.update(incoming or {})
    return effective_tags(merged, after)


def _shown(package: str, version: Version, base: str) -> dict[str, Any]:
    """A stored manifest as a client sees it, with its identity and its link.

    Without its readme: the document shows the latest one once, not one for each version.
    """
    manifest = {key: value for key, value in version.manifest.items() if key != "readme"}
    dist = manifest.get("dist")
    link = f"{base}/{paths.tarball_path(package, version.version)}"
    manifest["_id"] = f"{package}@{version.version}"
    manifest["dist"] = {**(dist if isinstance(dist, dict) else {}), "tarball": link}
    return manifest


def document(
    package: str, versions: Sequence[Version], tags: Mapping[str, str], base: str
) -> dict[str, Any] | None:
    """The package document, or None if the package has no version.

    `base` is the public address of the repository; tarball links are built on it.
    """
    if not versions:
        return None
    ordered = sorted(versions, key=lambda version: semver.sort_key(version.version))
    shown = {version.version: _shown(package, version, base) for version in ordered}
    shown_tags = effective_tags(tags, shown)
    built: dict[str, Any] = {
        "_id": package,
        "name": package,
        "dist-tags": shown_tags,
        "versions": shown,
        "time": {
            "created": iso(min(version.created for version in ordered)),
            "modified": iso(max(version.modified for version in ordered)),
            **{version.version: iso(version.created) for version in ordered},
        },
    }
    latest = next(v.manifest for v in ordered if v.version == shown_tags["latest"])
    built.update({field: latest[field] for field in _COPIED if field in latest})
    # It changes whenever the document does. It is accepted back and not checked.
    built["_rev"] = f"{len(shown)}-{hashlib.sha1(dumps(built)).hexdigest()[:32]}"
    return built


def render(
    package: str, versions: Sequence[Version], tags: Mapping[str, str], base: str
) -> Rendered | None:
    """The package document as bytes, or None if the package has no version."""
    built = document(package, versions, tags, base)
    if built is None:
        return None
    data = dumps(built)
    return Rendered(
        data=data,
        etag=hashlib.sha256(data).hexdigest(),
        modified=max(version.modified for version in versions),
    )


def manifest_of(built: Mapping[str, Any], wanted: str) -> dict[str, Any] | None:
    """One version's manifest from a package document, by version or by dist-tag."""
    version = built["dist-tags"].get(wanted, wanted)
    return built["versions"].get(version)


def update_plan(stored: Mapping[str, Mapping[str, Any]], sent: Mapping[str, Any]) -> Update:
    """What a document sent back without attachments changes: deprecations and removals.

    `stored` maps each version held to its manifest. Raises InvalidPackage.
    """
    versions = sent.get("versions")
    if not isinstance(versions, dict):
        return Update(deprecations={}, removals=())  # nothing is removed by saying nothing
    unknown = next((version for version in versions if version not in stored), None)
    if unknown is not None:
        # A version arrives with its tarball, in a publish. Listed here, it is a publish
        # gone wrong, and acting on the rest of the list would remove real versions.
        raise InvalidPackage(f"it names version {unknown!r}, which is not stored")
    deprecations: dict[str, str | None] = {}
    for version, manifest in stored.items():
        theirs = versions.get(version)
        if not isinstance(theirs, dict):
            continue
        message = theirs.get("deprecated")
        new = message if isinstance(message, str) and message else None  # "" clears it
        if new is not None and len(new) > MAX_DEPRECATION_LENGTH:
            raise InvalidPackage("a deprecation message is longer than 1024 characters")
        if new != (manifest.get("deprecated") or None):
            deprecations[version] = new
    removals = tuple(version for version in stored if version not in versions)
    return Update(deprecations=deprecations, removals=removals)


def deprecated(manifest: Mapping[str, Any], message: str | None) -> dict[str, Any]:
    """A manifest with its deprecation message set, or removed."""
    changed = {key: value for key, value in manifest.items() if key != "deprecated"}
    if message is not None:
        changed["deprecated"] = message
    return changed


def search_results(found: Sequence[Found], total: int, now: datetime) -> dict[str, Any]:
    """Search results in the shape `npm search` reads."""
    objects = [
        {
            "package": {
                "name": entry.name,
                "version": entry.version,
                "description": entry.description,
                "date": iso(entry.date),
                "keywords": [],
                "maintainers": [],
                "links": {},
            },
            "score": {"final": 1, "detail": {"quality": 1, "popularity": 1, "maintenance": 1}},
            "searchScore": 1,
        }
        for entry in found
    ]
    return {"objects": objects, "total": total, "time": iso(now)}


def combine(
    held: Sequence[tuple[Sequence[Version], Mapping[str, str]]],
) -> tuple[list[Version], dict[str, str]]:
    """What several repositories hold of one package, as if one repository held it.

    `held` gives each repository's versions and its stored dist-tags, in the order the
    repositories are tried. The earlier one wins a version both hold and a tag both
    set, so the `latest` of the first repository is the `latest` of the result.
    """
    versions: dict[str, Version] = {}
    tags: dict[str, str] = {}
    for theirs, stored in held:
        for version in theirs:
            versions.setdefault(version.version, version)
        shown = effective_tags(stored, [version.version for version in theirs])
        for tag, version in shown.items():
            tags.setdefault(tag, version)
    return list(versions.values()), tags


@dataclass(frozen=True)
class Merged:
    """The documents several registries serve for one package, as one."""

    data: bytes | None  # None when fewer than two of them could be read
    etag: str
    used: tuple[int, ...]  # the positions of those that could be read


def _served(raw: bytes) -> dict[str, Any] | None:
    """A package document another registry served, or None if it is not one."""
    try:
        value = loads(raw)
    except InvalidPackage:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("versions"), dict):
        return None
    return value


def merge_remote(package: str, raw: Sequence[bytes], base: str) -> Merged:
    """Merge the documents several registries serve for one package.

    `raw` is in the order the registries are tried. The earlier one wins a version, a
    time and a dist-tag that two of them have, and everything else is the first
    one's. Tarball links are pointed at `base`, the public address of the repository
    that answers. A document that cannot be read is left out.
    """
    if len(raw) < 2:
        return Merged(None, "", tuple(range(len(raw))))
    read = [(position, _served(data)) for position, data in enumerate(raw)]
    used = tuple(position for position, document in read if document is not None)
    documents = [document for _, document in read if document is not None]
    if len(documents) < 2:
        return Merged(None, "", used)

    merged = dict(documents[0])
    for field in ("versions", "time", "dist-tags"):
        union: dict[str, Any] = {}
        for document in documents:
            theirs = document.get(field)
            for key, value in theirs.items() if isinstance(theirs, dict) else ():
                union.setdefault(key, value)
        merged[field] = union
    tags = {
        tag: version for tag, version in merged["dist-tags"].items() if isinstance(version, str)
    }
    merged["dist-tags"] = effective_tags(tags, merged["versions"])
    data = rewrite(dumps(merged), base, package)
    return Merged(data, hashlib.sha256(data).hexdigest(), used)

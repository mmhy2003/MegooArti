"""Container image names, tags and digests, and what a registry request path means.

Pure functions. A request under `/v2/<repository>/` names an image and then says what
is wanted of it; an image's name may itself contain slashes, so a path is read from
its end.
"""

import re
from dataclasses import dataclass

# An image's name with its repository in front, as a client writes it.
MAX_NAME_LENGTH = 255
_COMPONENT = r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
_NAME = re.compile(rf"{_COMPONENT}(?:/{_COMPONENT})*")
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_UPLOAD = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class DockerPath:
    """A request path, classified. Fields that do not apply to its kind are left empty."""

    # manifest, blob, upload_start, upload, tags, referrers or other
    kind: str
    image: str = ""
    reference: str = ""  # manifest: a tag or a digest; blob, referrers: a digest; upload: its ID


_OTHER = DockerPath("other")


def is_valid_name(image: str) -> bool:
    return len(image) <= MAX_NAME_LENGTH and _NAME.fullmatch(image) is not None


def is_tag(text: str) -> bool:
    return _TAG.fullmatch(text) is not None


def is_digest(text: str) -> bool:
    """Whether this is a digest this registry takes: SHA-256, in lower case."""
    return _DIGEST.fullmatch(text) is not None


def hex_of(digest: str) -> str:
    """The hash in a digest: `sha256:<hex>` without its algorithm."""
    return digest.partition(":")[2]


def blob_path(digest: str) -> str:
    """Where a layer or an image configuration is stored: once for the repository."""
    return f"blobs/{digest}"


def manifest_path(image: str, digest: str) -> str:
    return f"manifests/{image}/{digest}"


def tag_path(image: str, tag: str) -> str:
    """Where a tag is stored: a file that holds the manifest the tag names."""
    return f"tags/{image}/{tag}"


def tag_of(path: str) -> tuple[str, str] | None:
    """The image and the tag a stored path is for, or None if it is not a tag's."""
    kind, _, rest = path.partition("/")
    image, _, tag = rest.rpartition("/")
    if kind != "tags" or not is_valid_name(image) or not is_tag(tag):
        return None
    return image, tag


def _split(path: str, marker: str) -> tuple[str, str] | None:
    """The image before the last `marker` and what follows it, if the image is one."""
    image, found, rest = path.rpartition(marker)
    if not found or not is_valid_name(image):
        return None
    return image, rest


def classify(path: str) -> DockerPath:
    """What a request path under `/v2/<repository>/` asks for."""
    if path.endswith("/tags/list"):
        image = path.removesuffix("/tags/list")
        return DockerPath("tags", image) if is_valid_name(image) else _OTHER
    found = _split(path, "/blobs/uploads/")
    if found is not None and found[1] == "":
        return DockerPath("upload_start", found[0])
    if found is not None and _UPLOAD.fullmatch(found[1]):
        return DockerPath("upload", found[0], found[1])
    if path.endswith("/blobs/uploads"):
        image = path.removesuffix("/blobs/uploads")
        return DockerPath("upload_start", image) if is_valid_name(image) else _OTHER
    for marker, kind in (("/blobs/", "blob"), ("/referrers/", "referrers")):
        found = _split(path, marker)
        if found is not None and is_digest(found[1]):
            return DockerPath(kind, found[0], found[1])
    found = _split(path, "/manifests/")
    if found is not None and (is_tag(found[1]) or is_digest(found[1])):
        return DockerPath("manifest", found[0], found[1])
    return _OTHER

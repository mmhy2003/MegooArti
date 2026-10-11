"""Container image manifests: what one is, and what it refers to.

Pure functions. A manifest is kept and served exactly as it was pushed, because its
digest is the hash of those bytes. It is read here only to learn its kind and the
blobs and manifests it needs.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from megooarti.repositories.docker import names

DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
DOCKER_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
# One image, and several images for several platforms.
_IMAGES = (DOCKER_MANIFEST, OCI_MANIFEST)
_LISTS = (DOCKER_LIST, OCI_INDEX)
MAX_BYTES = 4 * 1024 * 1024


class InvalidManifest(Exception):
    """What was pushed is not a manifest this registry takes. The message says why."""


@dataclass(frozen=True)
class Manifest:
    media_type: str
    digest: str  # `sha256:<hex>` of the bytes as pushed
    blobs: tuple[str, ...]  # digests of the configuration and layers it needs
    manifests: tuple[str, ...]  # digests of its platforms' manifests, if it is a list


def _digest_in(descriptor: Any, what: str) -> str:
    digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    if not isinstance(digest, str) or not names.is_digest(digest):
        raise InvalidManifest(f"{what} has no SHA-256 digest")
    return digest


def _kind(document: dict[str, Any], declared: str | None) -> str:
    """The media type: what the request declared, or what the manifest says of itself."""
    stated = document.get("mediaType")
    if stated is not None and not isinstance(stated, str):
        raise InvalidManifest("its mediaType is not text")
    sent = (declared or "").partition(";")[0].strip().lower()
    if sent in ("", "application/json", "application/octet-stream"):
        sent = ""  # says nothing about which kind of manifest it is
    if sent and stated and sent != stated:
        raise InvalidManifest("its mediaType is not the Content-Type it was sent with")
    kind = sent or stated
    if not kind:
        # OCI lets the type be left out. What the document holds says which it is.
        kind = OCI_INDEX if "manifests" in document else OCI_MANIFEST
    if kind not in _IMAGES + _LISTS:
        raise InvalidManifest(f"{kind} is not a manifest type this registry takes")
    return kind


def read(raw: bytes, declared: str | None) -> Manifest:
    """Read a manifest as pushed. `declared` is the request's Content-Type.

    Raises InvalidManifest.
    """
    if len(raw) > MAX_BYTES:
        raise InvalidManifest("it is larger than 4 MiB")
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise InvalidManifest("it is not JSON") from None
    if not isinstance(document, dict):
        raise InvalidManifest("it is not a JSON object")
    version = document.get("schemaVersion")
    if version != 2 or isinstance(version, bool):
        raise InvalidManifest("its schemaVersion is not 2")
    kind = _kind(document, declared)

    blobs: list[str] = []
    manifests: list[str] = []
    if kind in _LISTS:
        listed = document.get("manifests")
        if not isinstance(listed, list):
            raise InvalidManifest("it lists no manifests")
        manifests = [_digest_in(entry, "a listed manifest") for entry in listed]
    else:
        layers = document.get("layers")
        if not isinstance(layers, list):
            raise InvalidManifest("it has no layers")
        blobs.append(_digest_in(document.get("config"), "its configuration"))
        for layer in layers:
            digest = _digest_in(layer, "a layer")
            # A layer that says where else it is kept need not be here.
            if not (isinstance(layer.get("urls"), list) and layer["urls"]):
                blobs.append(digest)
    return Manifest(
        media_type=kind,
        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        blobs=tuple(dict.fromkeys(blobs)),
        manifests=tuple(dict.fromkeys(manifests)),
    )

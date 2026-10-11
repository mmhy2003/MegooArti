import hashlib
import json

import pytest

from megooarti.errors import ApiError
from megooarti.repositories.docker import errors, manifests
from megooarti.repositories.docker.errors import RegistryError
from megooarti.repositories.docker.manifests import (
    DOCKER_LIST,
    DOCKER_MANIFEST,
    OCI_INDEX,
    OCI_MANIFEST,
    InvalidManifest,
)

CONFIG = "sha256:" + "c" * 64
LAYER_ONE = "sha256:" + "1" * 64
LAYER_TWO = "sha256:" + "2" * 64
AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64


def image(media_type: str | None = OCI_MANIFEST, **changes) -> bytes:
    document = {
        "schemaVersion": 2,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": CONFIG},
        "layers": [{"digest": LAYER_ONE, "size": 10}, {"digest": LAYER_TWO, "size": 20}],
    }
    if media_type is not None:
        document["mediaType"] = media_type
    document.update(changes)
    return json.dumps(document).encode()


def index(media_type: str | None = OCI_INDEX, **changes) -> bytes:
    document = {
        "schemaVersion": 2,
        "manifests": [
            {"digest": AMD64, "platform": {"architecture": "amd64", "os": "linux"}},
            {"digest": ARM64, "platform": {"architecture": "arm64", "os": "linux"}},
        ],
    }
    if media_type is not None:
        document["mediaType"] = media_type
    document.update(changes)
    return json.dumps(document).encode()


@pytest.mark.parametrize("media_type", [OCI_MANIFEST, DOCKER_MANIFEST])
def test_an_image_refers_to_its_configuration_and_its_layers(media_type):
    raw = image(media_type)

    read = manifests.read(raw, media_type)

    assert read.media_type == media_type
    assert read.digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert read.blobs == (CONFIG, LAYER_ONE, LAYER_TWO)
    assert read.manifests == ()


@pytest.mark.parametrize("media_type", [OCI_INDEX, DOCKER_LIST])
def test_a_list_refers_to_the_manifest_of_each_platform(media_type):
    read = manifests.read(index(media_type), media_type)

    assert (read.media_type, read.blobs, read.manifests) == (media_type, (), (AMD64, ARM64))


@pytest.mark.parametrize(
    ("raw", "declared", "expected"),
    [
        (image(DOCKER_MANIFEST), None, DOCKER_MANIFEST),  # only the manifest says
        (image(DOCKER_MANIFEST), "application/json", DOCKER_MANIFEST),
        (image(None), OCI_MANIFEST, OCI_MANIFEST),  # only the request says
        (image(None), f"{DOCKER_MANIFEST}; charset=utf-8", DOCKER_MANIFEST),
        (image(None), None, OCI_MANIFEST),  # neither says: what it holds decides
        (index(None), "", OCI_INDEX),
        (image(OCI_MANIFEST), OCI_MANIFEST.upper(), OCI_MANIFEST),
    ],
)
def test_the_kind_is_what_the_request_or_the_manifest_says(raw, declared, expected):
    assert manifests.read(raw, declared).media_type == expected


def test_a_layer_kept_elsewhere_need_not_be_here():
    foreign = {"digest": LAYER_TWO, "urls": ["https://elsewhere.example/layer"]}
    raw = image(layers=[{"digest": LAYER_ONE}, foreign, {"digest": LAYER_ONE, "urls": []}])

    assert manifests.read(raw, None).blobs == (CONFIG, LAYER_ONE)  # each once


def test_an_artifact_is_an_image_like_any_other():
    empty = {"mediaType": "application/vnd.oci.empty.v1+json", "digest": CONFIG, "size": 2}
    raw = image(config=empty, artifactType="application/vnd.example.chart", subject={})

    assert manifests.read(raw, OCI_MANIFEST).blobs == (CONFIG, LAYER_ONE, LAYER_TWO)


def test_the_digest_is_of_the_bytes_as_pushed():
    spaced = json.dumps(json.loads(image()), indent=3).encode()

    assert manifests.read(spaced, None).digest != manifests.read(image(), None).digest
    assert manifests.read(spaced, None).blobs == manifests.read(image(), None).blobs


@pytest.mark.parametrize(
    ("raw", "declared", "reason"),
    [
        (b"not json", None, "not JSON"),
        (b"\xff\xfe", None, "not JSON"),
        (b"[]", None, "not a JSON object"),
        (image(schemaVersion=1), None, "schemaVersion"),
        (image(schemaVersion=True), None, "schemaVersion"),
        (image(schemaVersion="2"), None, "schemaVersion"),
        (
            image("application/vnd.docker.distribution.manifest.v1+json"),
            None,
            "not a manifest type",
        ),
        (
            image(None),
            "application/vnd.docker.distribution.manifest.v1+prettyjws",
            "not a manifest",
        ),
        (image(OCI_MANIFEST), DOCKER_MANIFEST, "Content-Type"),
        (image(mediaType=7), None, "mediaType"),
        (image(config=None), None, "configuration"),
        (image(config={"digest": "sha512:" + "a" * 128}), None, "configuration"),
        (image(config={"digest": "sha256:" + "A" * 64}), None, "configuration"),
        (image(layers=None), None, "no layers"),
        (image(layers=[{"size": 3}]), None, "a layer"),
        (image(layers=["sha256:" + "1" * 64]), None, "a layer"),
        (index(manifests=None), None, "no manifests"),
        (index(manifests=[{"digest": "latest"}]), None, "a listed manifest"),
        (image(OCI_INDEX), None, "no manifests"),  # says it is a list, holds an image
    ],
)
def test_what_is_not_a_manifest_this_registry_takes(raw, declared, reason):
    with pytest.raises(InvalidManifest, match=reason):
        manifests.read(raw, declared)


def test_a_manifest_nested_too_deep_or_too_large_is_refused():
    with pytest.raises(InvalidManifest, match="not JSON"):
        manifests.read(b"[" * 100_000, None)
    with pytest.raises(InvalidManifest, match="larger than 4 MiB"):
        manifests.read(image() + b" " * manifests.MAX_BYTES, None)
    assert manifests.read(image() + b" " * 1000, None).blobs  # space after it is still JSON


def test_an_error_is_answered_in_the_registrys_shape():
    error = RegistryError(404, "BLOB_UNKNOWN", "No such blob.", detail={"digest": CONFIG})

    answer = errors.response(error)

    assert answer.status_code == 404
    assert json.loads(answer.body) == {
        "errors": [
            {"code": "BLOB_UNKNOWN", "message": "No such blob.", "detail": {"digest": CONFIG}}
        ]
    }
    assert answer.headers["Docker-Distribution-Api-Version"] == "registry/2.0"
    assert isinstance(error, ApiError) and error.code == "BLOB_UNKNOWN"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "UNAUTHORIZED"),
        (403, "DENIED"),
        (404, "NAME_UNKNOWN"),
        (405, "UNSUPPORTED"),
        (409, "DENIED"),
        (413, "SIZE_INVALID"),
        (429, "TOOMANYREQUESTS"),
        (502, "UNKNOWN"),
        (503, "UNKNOWN"),
    ],
)
def test_an_error_of_the_cores_gets_the_code_that_fits_its_status(status, code):
    core = ApiError(status, "something_ours", "What happened.", headers={"Retry-After": "7"})

    answer = errors.response(core, headers={"WWW-Authenticate": "Bearer"})

    assert answer.status_code == status
    assert json.loads(answer.body) == {"errors": [{"code": code, "message": "What happened."}]}
    assert answer.headers["Retry-After"] == "7"
    assert answer.headers["WWW-Authenticate"] == "Bearer"

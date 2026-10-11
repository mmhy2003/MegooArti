import hashlib
import json

import pytest

from megooarti.repositories import service
from megooarti.repositories.docker.manifests import OCI_INDEX, OCI_MANIFEST
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

V2 = "/v2/images"


async def create(
    db, name: str, *, hosted: dict | None = None, proxy: dict | None = None
) -> Repository:
    """A Docker repository, committed: hosted, or a proxy if its settings are given."""
    repository = await service.create_repository(
        db,
        name=name,
        format="docker",
        type="hosted" if proxy is None else "proxy",
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        format_config={},
    )
    await db.commit()
    return repository


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def layer(text: str) -> bytes:
    """Stand-in layer bytes, different for every text."""
    return f"\x1f\x8b a layer holding {text}".encode()


def image_manifest(config: bytes, *layers: bytes, media_type: str = OCI_MANIFEST) -> bytes:
    """The manifest of an image with this configuration and these layers."""
    document = {
        "schemaVersion": 2,
        "mediaType": media_type,
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": digest_of(config),
            "size": len(config),
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": digest_of(data),
                "size": len(data),
            }
            for data in layers
        ],
    }
    return json.dumps(document).encode()


def index_manifest(*platforms: bytes, media_type: str = OCI_INDEX) -> bytes:
    """A manifest for several platforms, each given as its own manifest."""
    architectures = ("amd64", "arm64", "riscv64", "s390x")
    document = {
        "schemaVersion": 2,
        "mediaType": media_type,
        "manifests": [
            {
                "mediaType": OCI_MANIFEST,
                "digest": digest_of(manifest),
                "size": len(manifest),
                "platform": {"architecture": architectures[position], "os": "linux"},
            }
            for position, manifest in enumerate(platforms)
        ],
    }
    return json.dumps(document).encode()


def config_for(*texts: str) -> bytes:
    """The configuration of the image `push_image` makes of these layers."""
    return json.dumps({"architecture": "amd64", "os": "linux", "made-of": texts}).encode()


async def push_blob(client, headers, image: str, data: bytes, repository: str = "images") -> str:
    """Upload a blob the way Docker does: begin, one chunk, complete. Returns its digest."""
    begun = await client.post(f"/v2/{repository}/{image}/blobs/uploads/", headers=headers)
    assert begun.status_code == 202, begun.text
    sent = await client.patch(begun.headers["Location"], content=data, headers=headers)
    assert sent.status_code == 202, sent.text
    digest = digest_of(data)
    done = await client.put(f"{sent.headers['Location']}?digest={digest}", headers=headers)
    assert done.status_code == 201, done.text
    return digest


async def push_manifest(
    client, headers, image: str, reference: str, manifest: bytes, repository: str = "images"
):
    """Put a manifest as it is, by tag or by digest. Returns the response."""
    declared = json.loads(manifest).get("mediaType", OCI_MANIFEST)
    return await client.put(
        f"/v2/{repository}/{image}/manifests/{reference}",
        content=manifest,
        headers={**headers, "Content-Type": declared},
    )


async def push_image(
    client, headers, image: str, tag: str, *texts: str, repository: str = "images"
) -> bytes:
    """Push an image whose layers hold these texts, under a tag. Returns its manifest."""
    config = config_for(*texts)
    layers = [layer(text) for text in texts]
    for data in (config, *layers):
        await push_blob(client, headers, image, data, repository)
    manifest = image_manifest(config, *layers)
    response = await push_manifest(client, headers, image, tag, manifest, repository)
    assert response.status_code == 201, response.text
    return manifest


def error_code(response) -> str:
    """The registry's code for an error answer."""
    return response.json()["errors"][0]["code"]


@pytest.fixture
async def images(db) -> Repository:
    return await create(db, "images")


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)

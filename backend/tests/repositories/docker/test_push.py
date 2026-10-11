import hashlib

import pytest
from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Upload
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import V2, create, digest_of, error_code, layer, push_blob

LAYER = layer("one") * 500  # 12,500 bytes
DIGEST = digest_of(LAYER)
UPLOADS = f"{V2}/team/app/blobs/uploads/"
BLOB = f"{V2}/team/app/blobs/{DIGEST}"


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def temporary_files(settings) -> list[str]:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return [path.name for path in directory.iterdir()] if directory.exists() else []


async def test_a_layer_is_pushed_as_docker_pushes_it(client, images, root, db, settings):
    missing = await client.head(BLOB, headers=root)
    begun = await client.post(UPLOADS, headers=root)
    upload = begun.headers["Docker-Upload-UUID"]
    sent = await client.patch(begun.headers["Location"], content=LAYER, headers=root)
    done = await client.put(f"{sent.headers['Location']}?digest={DIGEST}", headers=root)
    found = await client.head(BLOB, headers=root)
    fetched = await client.get(BLOB, headers=root)

    assert (missing.status_code, missing.content) == (404, b"")
    assert begun.status_code == 202
    assert begun.headers["Location"] == f"{UPLOADS}{upload}"
    assert (begun.headers["Range"], len(upload)) == ("0-0", 32)
    assert (sent.status_code, sent.headers["Range"]) == (202, f"0-{len(LAYER) - 1}")
    assert sent.headers["Docker-Upload-UUID"] == upload
    assert (done.status_code, done.content) == (201, b"")
    assert done.headers["Location"] == BLOB
    assert done.headers["Docker-Content-Digest"] == DIGEST
    assert (found.status_code, found.headers["Content-Length"]) == (200, str(len(LAYER)))
    assert found.headers["Docker-Content-Digest"] == DIGEST
    assert (fetched.content, fetched.headers["Content-Type"]) == (LAYER, "application/octet-stream")
    assert fetched.headers["Docker-Distribution-Api-Version"] == "registry/2.0"
    assert list(await db.scalars(select(Asset.path))) == [f"blobs/{DIGEST}"]
    assert await count(db, Upload) == 0
    assert temporary_files(settings) == []


async def test_a_layer_is_shared_by_every_image_of_the_repository(client, images, root):
    await push_blob(client, root, "team/app", LAYER)

    elsewhere = await client.get(f"{V2}/another/image/blobs/{DIGEST}", headers=root)
    ranged = await client.get(BLOB, headers={**root, "Range": "bytes=0-9"})

    assert elsewhere.content == LAYER
    assert (ranged.status_code, ranged.content) == (206, LAYER[:10])


async def test_a_layer_can_arrive_in_chunks_and_be_resumed(client, images, root):
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]

    first = await client.patch(
        location, content=LAYER[:5000], headers={**root, "Content-Range": "0-4999"}
    )
    asked = await client.get(location, headers=root)
    again = await client.patch(
        location, content=LAYER[:5000], headers={**root, "Content-Range": "0-4999"}
    )
    second = await client.patch(
        location, content=LAYER[5000:9000], headers={**root, "Content-Range": "5000-8999"}
    )
    # The last chunk may come with the request that completes the upload.
    done = await client.put(f"{location}?digest={DIGEST}", content=LAYER[9000:], headers=root)

    assert (first.status_code, first.headers["Range"]) == (202, "0-4999")
    assert (asked.status_code, asked.headers["Range"]) == (204, "0-4999")
    assert (again.status_code, error_code(again)) == (416, "BLOB_UPLOAD_INVALID")
    assert again.headers["Range"] == "0-4999"  # where to go on from
    assert second.headers["Range"] == "0-8999"
    assert done.status_code == 201
    assert (await client.get(BLOB, headers=root)).content == LAYER


async def test_a_whole_layer_in_one_request(client, images, root):
    at_once = await client.post(f"{UPLOADS}?digest={DIGEST}", content=LAYER, headers=root)
    begun = await client.post(UPLOADS, headers=root)
    with_the_last = await client.put(
        f"{begun.headers['Location']}?digest={DIGEST}", content=LAYER, headers=root
    )

    assert (at_once.status_code, at_once.headers["Location"]) == (201, BLOB)
    assert with_the_last.status_code == 201  # here already: nothing new is stored
    assert (await client.get(BLOB, headers=root)).content == LAYER


async def test_a_layer_that_is_here_is_mounted_not_uploaded(client, images, root, db):
    await push_blob(client, root, "team/app", LAYER)
    other = digest_of(b"not here")

    mounted = await client.post(
        f"{V2}/another/image/blobs/uploads/",
        params={"mount": DIGEST, "from": "images/team/app"},
        headers=root,
    )
    not_here = await client.post(UPLOADS, params={"mount": other, "from": "x/y"}, headers=root)

    assert mounted.status_code == 201
    assert mounted.headers["Location"] == f"{V2}/another/image/blobs/{DIGEST}"
    assert mounted.headers["Docker-Content-Digest"] == DIGEST
    assert (not_here.status_code, "Docker-Upload-UUID" in not_here.headers) == (202, True)


async def test_content_that_is_not_what_its_digest_says_is_refused(
    client, images, root, db, settings
):
    wrong = digest_of(b"something else")
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]
    await client.patch(location, content=LAYER, headers=root)

    finished = await client.put(f"{location}?digest={wrong}", headers=root)
    after = await client.get(location, headers=root)
    at_once = await client.post(f"{UPLOADS}?digest={wrong}", content=LAYER, headers=root)

    for response in (finished, at_once):
        assert (response.status_code, error_code(response)) == (400, "DIGEST_INVALID")
    assert (after.status_code, error_code(after)) == (404, "BLOB_UPLOAD_UNKNOWN")  # it is over
    assert await count(db, Asset) == 0
    assert temporary_files(settings) == []


@pytest.mark.parametrize(
    "digest",
    ["", "latest", "sha256:" + "A" * 64, "sha512:" + "a" * 128, "sha256:" + "a" * 63],
)
async def test_only_a_sha256_digest_completes_an_upload(client, images, root, digest):
    begun = await client.post(UPLOADS, headers=root)
    await client.patch(begun.headers["Location"], content=LAYER, headers=root)

    response = await client.put(begun.headers["Location"], params={"digest": digest}, headers=root)
    missing = await client.put(begun.headers["Location"], headers=root)

    for refused in (response, missing):
        assert (refused.status_code, error_code(refused)) == (400, "DIGEST_INVALID")
    still = await client.get(begun.headers["Location"], headers=root)
    assert still.headers["Range"] == f"0-{len(LAYER) - 1}"  # the upload can still be completed


async def test_an_abandoned_upload_is_gone(client, images, root, db, settings):
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]
    await client.patch(location, content=LAYER, headers=root)

    abandoned = await client.delete(location, headers=root)
    again = await client.delete(location, headers=root)
    more = await client.patch(location, content=b"more", headers=root)

    assert abandoned.status_code == 204
    for response in (again, more):
        assert (response.status_code, error_code(response)) == (404, "BLOB_UPLOAD_UNKNOWN")
    assert await count(db, Upload) == 0
    assert temporary_files(settings) == []


async def test_an_upload_belongs_to_the_image_it_was_begun_for(client, images, root, db):
    await create(db, "others")
    begun = await client.post(UPLOADS, headers=root)
    upload = begun.headers["Docker-Upload-UUID"]

    for address in (
        f"{V2}/another/app/blobs/uploads/{upload}",
        f"/v2/others/team/app/blobs/uploads/{upload}",
        f"{UPLOADS}{'0' * 32}",
    ):
        response = await client.patch(address, content=b"x", headers=root)
        assert (response.status_code, error_code(response)) == (404, "BLOB_UPLOAD_UNKNOWN")


async def test_a_bad_content_range_is_refused(client, images, root):
    begun = await client.post(UPLOADS, headers=root)

    response = await client.patch(
        begun.headers["Location"], content=b"x", headers={**root, "Content-Range": "start-end"}
    )

    assert (response.status_code, error_code(response)) == (400, "BLOB_UPLOAD_INVALID")


async def test_pushing_needs_the_right_to_add(client, images, root, make_user, db):
    await push_blob(client, root, "team/app", LAYER)
    await roles.create_role(db, "readers", "", ["repository:docker:images:read"], [])
    await db.commit()
    await make_user("reader", roles=["readers"])
    reader = basic("reader", PASSWORD)
    begun = await client.post(UPLOADS, headers=root)
    location = begun.headers["Location"]

    attempts = [
        await client.post(UPLOADS, headers=reader),
        await client.post(f"{UPLOADS}?digest={DIGEST}", content=LAYER, headers=reader),
        await client.post(UPLOADS, params={"mount": DIGEST, "from": "x"}, headers=reader),
        await client.patch(location, content=b"x", headers=reader),
        await client.get(location, headers=reader),
        await client.put(f"{location}?digest={DIGEST}", headers=reader),
        await client.delete(location, headers=reader),
    ]

    for response in attempts:
        assert (response.status_code, error_code(response)) == (403, "DENIED")
    assert (await client.get(BLOB, headers=reader)).content == LAYER  # reading is allowed
    assert (await client.get(location, headers=root)).headers["Range"] == "0-0"  # untouched


async def test_a_read_only_repository_takes_no_uploads(client, db, root):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await client.post("/v2/frozen/app/blobs/uploads/", headers=root)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "allow"),
    [
        ("DELETE", f"team/app/blobs/{DIGEST}", "GET, HEAD"),
        ("PUT", f"team/app/blobs/{DIGEST}", "GET, HEAD"),
        ("GET", "team/app/blobs/uploads/", "POST"),
        ("POST", "team/app/blobs/uploads/" + "0" * 32, "GET, PATCH, PUT, DELETE"),
    ],
)
async def test_what_an_address_does_not_do(client, images, root, method, path, allow):
    response = await client.request(method, f"{V2}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
    assert response.headers["Allow"] == allow


async def test_a_large_layer_arrives_whole_without_being_copied(client, images, root, settings):
    data = bytes(range(256)) * 4096 * 3  # 3 MiB, sent in many pieces
    digest = digest_of(data)

    async def pieces():
        for start in range(0, len(data), 65_521):
            yield data[start : start + 65_521]

    begun = await client.post(UPLOADS, headers=root)
    sent = await client.patch(begun.headers["Location"], content=pieces(), headers=root)
    done = await client.put(f"{begun.headers['Location']}?digest={digest}", headers=root)
    fetched = await client.get(f"{V2}/team/app/blobs/{digest}", headers=root)

    assert (sent.headers["Range"], done.status_code) == (f"0-{len(data) - 1}", 201)
    assert hashlib.sha256(fetched.content).hexdigest() == hashlib.sha256(data).hexdigest()
    assert temporary_files(settings) == []

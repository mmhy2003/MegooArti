import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.security import roles, users
from megooarti.security.models import LoginFailure
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer
from tests.repositories.docker.conftest import V2, error_code, push_image

CHALLENGE = 'Bearer realm="https://test/v2/token",service="test"'


async def sign_in(client, headers: dict | None = None) -> dict[str, str]:
    """Do what `docker login` does. Returns the header to send from then on."""
    response = await client.get("/v2/token", params={"service": "test"}, headers=headers or {})
    assert response.status_code == 200, response.text
    return bearer(response.json()["token"])


async def let_anyone(db, *permissions: str) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    await roles.create_role(db, "public", "", list(permissions), [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await db.commit()


async def test_a_request_without_credentials_is_told_how_to_sign_in(client, images):
    base = await client.get("/v2/")
    pull = await client.get(f"{V2}/app/manifests/latest")
    push = await client.post(f"{V2}/team/app/blobs/uploads/")

    for response in (base, pull, push):
        assert (response.status_code, error_code(response)) == (401, "UNAUTHORIZED")
        assert response.headers["Docker-Distribution-Api-Version"] == "registry/2.0"
    assert base.headers["WWW-Authenticate"] == CHALLENGE
    assert pull.headers["WWW-Authenticate"] == f'{CHALLENGE},scope="repository:images/app:pull"'
    assert push.headers["WWW-Authenticate"] == (
        f'{CHALLENGE},scope="repository:images/team/app:pull,push"'
    )


async def test_the_challenge_names_the_public_address(client, images, db):
    await set_setting(db, "base_url", "https://registry.example/")
    await db.commit()

    response = await client.get("/v2/")

    assert response.headers["WWW-Authenticate"].startswith(
        'Bearer realm="https://registry.example/v2/token",'
    )


async def test_signing_in_gives_a_token_that_the_registry_takes(client, images, make_user):
    await make_user("root", roles=["admin"])

    response = await client.get("/v2/token", headers=basic("root", PASSWORD))
    token = bearer(response.json()["token"])
    base = await client.get("/v2/", headers=token)

    assert response.json()["token"] == response.json()["access_token"]
    assert response.json()["expires_in"] == 300
    assert response.headers["Cache-Control"] == "no-store"
    assert (base.status_code, base.json()) == (200, {})
    assert base.headers["Docker-Distribution-Api-Version"] == "registry/2.0"


async def test_an_api_token_signs_in_too(client, images, make_user, make_token):
    owner = await make_user("root", roles=["admin"])
    api_token = await make_token(owner)

    for credentials in (basic("root", api_token), basic("__token__", api_token), bearer(api_token)):
        token = await sign_in(client, credentials)
        assert (await client.get("/v2/", headers=token)).status_code == 200


async def test_credentials_sent_with_the_request_itself_are_taken(
    client, images, root, make_token, db
):
    api_token = await make_token(await users.get_user_by_username(db, "root"))

    for credentials in (root, bearer(api_token)):
        assert (await client.get("/v2/", headers=credentials)).status_code == 200


async def test_wrong_credentials_get_no_token_and_are_counted(client, images, make_user, db):
    await make_user("root", roles=["admin"])

    response = await client.get("/v2/token", headers=basic("root", "not the password"))

    assert (response.status_code, error_code(response)) == (401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'
    assert await db.scalar(select(LoginFailure.count).where(LoginFailure.subject == "user:root"))


async def test_too_many_wrong_sign_ins_are_slowed_down(client, images, make_user):
    await make_user("root", roles=["admin"])
    for _ in range(5):
        await client.get("/v2/token", headers=basic("root", "a guess"))

    response = await client.get("/v2/token", headers=basic("root", "another guess"))

    assert (response.status_code, error_code(response)) == (429, "TOOMANYREQUESTS")
    assert "Retry-After" in response.headers


async def test_a_token_that_is_not_ours_is_refused_with_the_challenge(client, images):
    for value in ("mgr_made-up", "mga_" + "x" * 43, "anything"):
        response = await client.get("/v2/", headers=bearer(value))
        assert (response.status_code, error_code(response)) == (401, "UNAUTHORIZED")
        assert response.headers["WWW-Authenticate"] == CHALLENGE


async def test_nobody_gets_a_token_unless_anyone_may_read(client, images, root, db):
    await push_image(client, root, "app", "latest", "one")
    refused = await client.get("/v2/token")
    await let_anyone(db, "repository:docker:images:read")

    token = await sign_in(client)
    base = await client.get("/v2/", headers=token)
    pulled = await client.get(f"{V2}/app/manifests/latest", headers=token)
    pushed = await client.post(f"{V2}/app/blobs/uploads/", headers=token)

    assert (refused.status_code, error_code(refused)) == (401, "UNAUTHORIZED")
    assert (base.status_code, pulled.status_code) == (200, 200)
    # Not signed in: asked to, so that the client prompts for credentials.
    assert (pushed.status_code, error_code(pushed)) == (401, "UNAUTHORIZED")
    assert pushed.headers["WWW-Authenticate"].startswith("Bearer ")


async def test_anonymous_access_does_not_spare_a_request_the_challenge(client, images, db):
    await let_anyone(db, "repository:docker:images:read")

    response = await client.get(f"{V2}/app/manifests/latest")

    assert response.status_code == 401  # a client then fetches a token, and learns it may read


async def test_reading_needs_read_and_a_signed_in_caller_is_denied_not_challenged(
    client, images, root, make_user, db
):
    await push_image(client, root, "app", "latest", "one")
    await roles.create_role(db, "readers", "", ["repository:docker:images:read"], [])
    await db.commit()
    await make_user("reader", roles=["readers"])
    await make_user("stranger")
    reader = await sign_in(client, basic("reader", PASSWORD))
    stranger = await sign_in(client, basic("stranger", PASSWORD))

    allowed = await client.get(f"{V2}/app/manifests/latest", headers=reader)
    denied = await client.get(f"{V2}/app/manifests/latest", headers=stranger)
    push = await client.post(f"{V2}/app/blobs/uploads/", headers=reader)

    assert allowed.status_code == 200
    for response in (denied, push):
        assert (response.status_code, error_code(response)) == (403, "DENIED")
        assert "WWW-Authenticate" not in response.headers


async def test_a_repository_that_is_not_a_registry_is_unknown_here(client, files, images, root):
    not_docker = await client.get("/v2/files/app/manifests/latest", headers=root)
    missing = await client.get("/v2/no-such-repository/app/manifests/latest", headers=root)
    under_repository = await client.get("/repository/images/app/manifests/latest", headers=root)

    for response in (not_docker, missing):
        assert (response.status_code, error_code(response)) == (404, "NAME_UNKNOWN")
    # And a registry is not served where the other formats are.
    assert under_repository.status_code == 404
    assert under_repository.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "path",
    ["app", "app/manifests", "App/manifests/latest", "app/blobs/latest", "app/tags", "x/y/z"],
)
async def test_an_address_that_means_nothing_is_unknown(client, images, root, path):
    response = await client.get(f"{V2}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "NAME_UNKNOWN")


async def test_an_image_name_has_a_limit_with_its_repository(client, images, root):
    long_name = "/".join(["a" * 60] * 4)  # 243 characters, and "images/" before it

    fits = await client.get(f"/v2/images/{long_name}/tags/list", headers=root)
    too_long = await client.get(f"/v2/images/{long_name}/aaaaaa/tags/list", headers=root)

    assert (fits.status_code, error_code(fits)) == (404, "NAME_UNKNOWN")  # no such image
    assert (too_long.status_code, error_code(too_long)) == (400, "NAME_INVALID")


async def test_an_offline_repository_is_unavailable(client, images, root, db):
    repository = await service.get_repository(db, "images")
    repository.online = False
    await db.commit()

    response = await client.get(f"{V2}/app/manifests/latest", headers=root)

    assert (response.status_code, error_code(response)) == (503, "UNKNOWN")


async def test_the_referrers_api_is_not_there(client, images, root):
    response = await client.get(f"{V2}/app/referrers/sha256:{'a' * 64}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "UNSUPPORTED")


@pytest.mark.parametrize(
    "name", ["Images", "my_.repo", "-edge", "a..b", "x--y.", "_catalog", "a___b"]
)
async def test_a_repository_is_named_as_the_first_part_of_an_image_name(admin_client, name):
    body = {"name": name, "format": "docker", "type": "hosted"}

    response = await admin_client.post("/api/v1/repositories", json=body)
    elsewhere = await admin_client.post("/api/v1/repositories", json={**body, "format": "raw"})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "name"
    assert elsewhere.status_code == 201  # fine where no container client has to write it


async def test_names_a_container_client_can_write_are_taken(admin_client):
    for name in ("images", "team-1", "docker.hosted", "a__b", "x--y", "0"):
        body = {"name": name, "format": "docker", "type": "hosted"}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == 201, name


@pytest.mark.parametrize("name", ["a%22b", "a%0D%0Ab", "%E2%82%AC", "Images", "a%20b"])
async def test_the_challenge_carries_nothing_a_client_wrote_unless_it_is_a_name(
    client, images, name
):
    response = await client.get(f"/v2/{name}/img/manifests/latest")
    odd_image = await client.get(f"/v2/images/{name}/manifests/latest")

    for refused in (response, odd_image):
        if refused.status_code == 404:
            assert "%0A" in name  # no route takes a line break in an image's name
            continue
        assert refused.status_code == 401
        challenge = refused.headers["WWW-Authenticate"]
        assert challenge == 'Bearer realm="https://test/v2/token",service="test"'
    assert response.status_code == 401


async def test_the_challenge_names_the_host_only_if_it_is_one(client, images):
    response = await client.get("/v2/", headers={"Host": 'evil",realm="https://elsewhere'})

    challenge = response.headers["WWW-Authenticate"]
    assert response.status_code == 401
    assert "elsewhere" not in challenge
    assert challenge.count('"') == 4  # a realm and a service, and nothing else
    assert challenge.endswith('/v2/token",service="registry"')


async def test_a_repository_is_hosted_a_proxy_or_a_group(admin_client):
    proxy = {"proxy": {"remote_url": "https://registry-1.docker.io"}}
    group = {"group": {"members": ["docker-hosted", "docker-proxy"]}}
    for kind, extra in (("hosted", {}), ("proxy", proxy), ("group", group)):
        body = {"name": f"docker-{kind}", "format": "docker", "type": kind, **extra}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == 201, kind

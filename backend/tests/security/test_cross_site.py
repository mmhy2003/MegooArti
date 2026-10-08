import pytest

from tests.accounts import PASSWORD, basic, error_code

ROLES = "/api/v1/roles"
ROLE = {"name": "readers", "description": "", "permissions": [], "roles": []}


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def test_a_write_from_another_site_is_refused_even_with_valid_credentials(client, root):
    response = await client.post(ROLES, json=ROLE, headers={**root, "Sec-Fetch-Site": "cross-site"})

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
    assert (await client.get(f"{ROLES}/readers", headers=root)).status_code == 404


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
async def test_writes_from_the_same_site_or_typed_by_the_user_are_accepted(client, root, site):
    response = await client.post(ROLES, json=ROLE, headers={**root, "Sec-Fetch-Site": site})

    assert response.status_code == 201


async def test_clients_that_do_not_send_the_header_are_unaffected(client, root):
    assert (await client.post(ROLES, json=ROLE, headers=root)).status_code == 201


async def test_reads_from_another_site_are_not_refused(client, root):
    response = await client.get(ROLES, headers={**root, "Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 200


async def test_uploads_from_another_site_are_refused(client, root, files):
    response = await client.put(
        "/repository/files/a.bin", content=b"x", headers={**root, "Sec-Fetch-Site": "cross-site"}
    )

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")

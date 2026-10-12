import pytest

from megooarti.system.settings_store import set_setting
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


async def test_without_fetch_metadata_a_foreign_origin_is_refused(client, root):
    # Browsers omit Sec-Fetch-Site on plain HTTP, but still send Origin.
    foreign = {**root, "Origin": "http://evil.example", "Host": "arti.example"}

    response = await client.post(ROLES, json=ROLE, headers=foreign)

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")


@pytest.mark.parametrize("origin", ["http://arti.example", "http://ARTI.example"])
async def test_without_fetch_metadata_the_sites_own_origin_is_accepted(client, root, origin):
    own = {**root, "Origin": origin, "Host": "arti.example"}

    assert (await client.post(ROLES, json=ROLE, headers=own)).status_code == 201


async def test_the_configured_base_url_counts_as_the_sites_own_origin(client, root, db):
    await set_setting(db, "base_url", "https://repo.example.org")
    await db.commit()
    proxied = {**root, "Origin": "https://repo.example.org", "Host": "backend:8000"}

    assert (await client.post(ROLES, json=ROLE, headers=proxied)).status_code == 201


LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
SESSION = "/api/v1/auth/session"
CREDENTIALS = {"username": "root", "password": PASSWORD}


@pytest.mark.parametrize(
    "said",
    [
        {"Sec-Fetch-Site": "cross-site"},
        # Without fetch metadata (plain HTTP), where the page is from is all there is.
        {"Origin": "http://evil.example", "Host": "arti.example"},
    ],
)
async def test_nobody_is_signed_in_from_another_site(client, root, said):
    # A page elsewhere could sign its visitor in to an account of its own (H5).
    response = await client.post(LOGIN, json=CREDENTIALS, headers=said)

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
    assert "set-cookie" not in response.headers
    assert (await client.get(SESSION)).json()["authenticated"] is False


@pytest.mark.parametrize(
    "said",
    [
        {},  # curl, a script: they say nothing of where they are from
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": "http://arti.example", "Host": "arti.example"},
    ],
)
async def test_signing_in_from_the_site_itself_or_from_no_site_goes_on(client, root, said):
    response = await client.post(LOGIN, json=CREDENTIALS, headers=said)

    assert response.status_code == 200
    assert (await client.get(SESSION)).json()["authenticated"] is True


async def test_a_wrong_password_from_another_site_is_not_counted_as_an_attempt(client, root):
    wrong = {"username": "root", "password": "not the password"}
    for _ in range(10):  # more than the failures that lock an account for a while
        refused = await client.post(LOGIN, json=wrong, headers={"Sec-Fetch-Site": "cross-site"})
        assert refused.status_code == 403

    assert (await client.post(LOGIN, json=CREDENTIALS)).status_code == 200


async def test_nobody_is_signed_out_from_another_site(client, root):
    signed_in = (await client.post(LOGIN, json=CREDENTIALS)).json()
    token = {"X-CSRF-Token": signed_in["csrf_token"]}

    response = await client.post(LOGOUT, headers={**token, "Sec-Fetch-Site": "cross-site"})

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
    assert (await client.get(SESSION)).json()["authenticated"] is True

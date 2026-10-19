"""An OIDC source as it is kept and tested (spec 5): its settings checked, its secret
sealed and bound to its issuer, the provider's metadata and keys asked for and kept an
hour, and the address to register at the provider."""

import pytest

from tests.accounts import error_code
from tests.security.provider import CLIENT_ID, CLIENT_SECRET, ISSUER

SOURCES = "/api/v1/auth-sources"


def oidc(name: str = "Corp SSO", **settings) -> dict:
    return {
        "kind": "oidc",
        "name": name,
        "settings": {
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            **settings,
        },
    }


async def test_an_oidc_source_is_kept_with_its_defaults_and_its_secret_sealed(admin_client):
    made = await admin_client.post(SOURCES, json=oidc(issuer=f"{ISSUER}/", scopes="email groups"))

    assert made.status_code == 201, made.text
    body = made.json()
    assert body["settings"] == {
        "issuer": ISSUER,  # without the slash it was given with
        "client_id": CLIENT_ID,
        "scopes": ["openid", "email", "groups"],
        "require_verified_email": False,
        "username_claim": "preferred_username",
        "name_claim": "name",
        "email_claim": "email",
        "groups_claim": "groups",
    }
    assert body["secrets"] == ["client_secret"]
    assert CLIENT_SECRET not in made.text


async def test_the_address_to_register_at_the_provider_is_under_the_base_url(admin_client):
    made = (await admin_client.post(SOURCES, json=oidc())).json()
    callback = f"/api/v1/auth/oidc/{made['id']}/callback"

    await admin_client.put(
        "/api/v1/settings/base-url", json={"base_url": "https://repo.example.org"}
    )
    based = (await admin_client.get(f"{SOURCES}/{made['id']}")).json()

    assert made["redirect_uri"] == f"https://test{callback}"
    assert based["redirect_uri"] == f"https://repo.example.org{callback}"


@pytest.mark.parametrize(
    ("sent", "field"),
    [
        ({"issuer": "sso.example"}, "settings.issuer"),
        ({"issuer": "ftp://sso.example"}, "settings.issuer"),
        ({"issuer": "https://sso.example/realms/corp?x=1"}, "settings.issuer"),
        ({"issuer": "https://someone:pw@sso.example"}, "settings.issuer"),
        ({"client_id": ""}, "settings.client_id"),
        ({"scopes": 'openid "profile"'}, "settings.scopes"),
        ({"scopes": ["openid", 7]}, "settings.scopes"),
        ({"groups_claim": "groups and roles"}, "settings.groups_claim"),
    ],
)
async def test_what_is_wrong_with_an_oidc_source_is_said_where_it_is(admin_client, sent, field):
    refused = await admin_client.post(SOURCES, json=oidc(**sent))

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_the_client_secret_is_asked_again_for_another_issuer(admin_client):
    made = (await admin_client.post(SOURCES, json=oidc())).json()
    elsewhere = {**made["settings"], "issuer": "https://attacker.example"}

    refused = await admin_client.put(
        f"{SOURCES}/{made['id']}", json={"name": made["name"], "settings": elsewhere}
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "settings.client_secret"


async def test_testing_a_source_asks_the_provider_for_its_metadata_and_keys(admin_client, provider):
    made = (await admin_client.post(SOURCES, json=oidc())).json()

    tested = await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})

    assert tested.json() == {
        "ok": True,
        "message": f"{ISSUER} answered. It signs with RS256; 1 keys.",
        "user": None,
    }
    assert provider.asked == [
        "/realms/corp/.well-known/openid-configuration",
        "/realms/corp/protocol/openid-connect/certs",
    ]


async def test_a_provider_that_does_not_answer_or_names_another_issuer_fails_its_test(
    admin_client, provider
):
    made = (await admin_client.post(SOURCES, json=oidc())).json()

    provider.down = True
    down = (await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})).json()
    provider.down = False
    provider.issuer_said = "https://elsewhere.example"
    other = (await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})).json()

    assert down["ok"] is False and "could not be reached" in down["message"]
    assert other["ok"] is False and "https://elsewhere.example" in other["message"]

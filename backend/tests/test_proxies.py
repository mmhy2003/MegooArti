"""Who a request comes from, behind proxies (spec 8): X-Forwarded-For read from the right,
past the gateway and the proxies an administrator trusts; the rest never believed."""

import pytest
from sqlalchemy import select

from megooarti.proxies import UNKNOWN, Deployment, address, networks, resolve
from megooarti.security.models import UserSession
from tests.accounts import PASSWORD, error_code

GATEWAY = "172.18.0.4"
SIGN_IN = "/api/v1/settings/sign-in"
PROXIES = "/api/v1/settings/trusted-proxies"


@pytest.mark.parametrize(
    ("peer", "forwarded", "deployment", "proxies", "client", "proxied"),
    [
        # The gateway alone: what it saw is the client.
        (GATEWAY, ["203.0.113.7"], "*", [], "203.0.113.7", False),
        # What the client wrote of itself, before the gateway's word, is not believed.
        (GATEWAY, ["1.1.1.1", "203.0.113.7"], "*", [], "203.0.113.7", False),
        # A proxy of the administrator's in front of the gateway: past it.
        (GATEWAY, ["198.51.100.9", "10.0.0.5"], "*", ["10.0.0.5"], "198.51.100.9", True),
        (
            GATEWAY,
            ["6.6.6.6", "198.51.100.9", "10.0.0.5"],
            "*",
            ["10.0.0.0/8"],
            "198.51.100.9",
            True,
        ),
        # Without the gateway: a trusted proxy that reaches the backend itself.
        ("10.0.0.5", ["198.51.100.9"], "127.0.0.1", ["10.0.0.5"], "198.51.100.9", True),
        # A peer nobody trusts: whatever it says is its own.
        ("192.0.2.1", ["198.51.100.9"], "127.0.0.1", [], "192.0.2.1", False),
        # The deployment's addresses are trusted as the peer only, never further left.
        (
            GATEWAY,
            ["127.0.0.1", "203.0.113.7"],
            "127.0.0.1,172.18.0.0/16",
            [],
            "203.0.113.7",
            False,
        ),
        # What is not an address, where an address must be.
        (GATEWAY, ["not an address"], "*", [], UNKNOWN, False),
        (GATEWAY, ["198.51.100.9", "garbage"], "*", [], UNKNOWN, False),
        # Every one trusted: the furthest is the client.
        (GATEWAY, ["10.0.0.6", "10.0.0.5"], "*", ["10.0.0.0/8"], "10.0.0.6", True),
        (None, [], "*", [], UNKNOWN, False),
    ],
)
def test_the_client_is_the_first_address_from_the_right_that_is_no_trusted_proxy(
    peer, forwarded, deployment, proxies, client, proxied
):
    assert resolve(peer, forwarded, Deployment(deployment), networks(proxies)) == (client, proxied)


@pytest.mark.parametrize(
    ("written", "read"),
    [
        ("203.0.113.7", "203.0.113.7"),
        (" 203.0.113.7:51234 ", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("unknown", None),
        ("", None),
    ],
)
def test_an_address_is_read_as_proxies_write_it(written, read):
    assert address(written) == read


async def session_ip(sessionmaker) -> str:
    async with sessionmaker() as db:
        return await db.scalar(
            select(UserSession.ip).order_by(UserSession.created_at.desc()).limit(1)
        )


async def test_a_sessions_address_is_the_one_the_proxies_say(client, make_user, sessionmaker):
    # The tests' client comes from 127.0.0.1, which the deployment trusts as the gateway.
    await make_user("dana")

    await client.post(
        "/api/v1/auth/login",
        json={"username": "dana", "password": PASSWORD},
        headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.7"},
    )

    assert await session_ip(sessionmaker) == "203.0.113.7"


async def test_trusted_proxies_are_kept_checked_and_believed_at_once(
    admin_client, other_client, make_user, sessionmaker
):
    await make_user("dana")
    chain = {"X-Forwarded-For": "198.51.100.9, 10.0.0.5"}
    login = {"username": "dana", "password": PASSWORD}

    await other_client.post("/api/v1/auth/login", json=login, headers=chain)
    before = await session_ip(sessionmaker)
    kept = await admin_client.put(
        PROXIES, json={"trusted_proxies": ["10.0.0.5", "10.0.0.0/8", "10.0.0.5"]}
    )
    await other_client.post("/api/v1/auth/login", json=login, headers=chain)
    after = await session_ip(sessionmaker)
    shown = (await admin_client.get(SIGN_IN)).json()

    assert (before, after) == ("10.0.0.5", "198.51.100.9")
    assert kept.json()["trusted_proxies"] == ["10.0.0.5/32", "10.0.0.0/8"]
    assert shown["trusted_proxies"] == ["10.0.0.5/32", "10.0.0.0/8"]


@pytest.mark.parametrize("entry", ["10.0.0.0/33", "proxy.corp.example", "", "10.0.0.5/8/1"])
async def test_what_is_no_address_or_network_is_refused_where_it_is(admin_client, entry):
    refused = await admin_client.put(PROXIES, json={"trusted_proxies": ["10.0.0.5", entry]})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "trusted_proxies.1"


async def test_trusted_proxies_need_the_security_permission(client, make_user):
    from tests.accounts import basic

    await make_user("sam")

    refused = await client.put(
        PROXIES, json={"trusted_proxies": ["10.0.0.5"]}, headers=basic("sam", PASSWORD)
    )

    assert refused.status_code == 403


async def test_the_scheme_a_trusted_peer_says_is_believed(admin_client):
    # The address a provider sends people back to is written from it (15b).
    made = await admin_client.post(
        "/api/v1/auth-sources",
        json={
            "kind": "oidc",
            "name": "Corp SSO",
            "settings": {"issuer": "https://sso.example", "client_id": "megooarti"},
        },
    )
    said = await admin_client.get(
        f"/api/v1/auth-sources/{made.json()['id']}", headers={"X-Forwarded-Proto": "http"}
    )

    assert made.json()["redirect_uri"].startswith("https://test/")
    assert said.json()["redirect_uri"].startswith("http://test/")

"""The trusted certificates' API (spec 6): listed, added by pasting one, fetched from a
host to be checked, and removed; and the outbound connections trusting them at once."""

import uuid

from megooarti.repositories import remote
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.tls import authority, https_server

CERTIFICATES = "/api/v1/certificates"


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def test_certificates_need_their_permissions(client, make_user, sessionmaker):
    await make_role(sessionmaker, "certificate-reader", "admin:certificates:read")
    await make_user("rita", roles=["certificate-reader"])
    await make_user("sam")
    pem = authority().pem

    nobody = await client.get(CERTIFICATES)
    sam = await client.get(CERTIFICATES, headers=basic("sam", PASSWORD))
    rita = await client.get(CERTIFICATES, headers=basic("rita", PASSWORD))
    rita_adds = await client.post(CERTIFICATES, json={"pem": pem}, headers=basic("rita", PASSWORD))
    rita_fetches = await client.post(
        f"{CERTIFICATES}/fetch", json={"host": "127.0.0.1"}, headers=basic("rita", PASSWORD)
    )

    assert (nobody.status_code, sam.status_code, rita.status_code) == (401, 403, 200)
    assert (rita_adds.status_code, rita_fetches.status_code) == (403, 403)


async def test_a_certificate_is_added_with_who_added_it_and_listed(admin_client):
    ca = authority("Corp Root CA")

    added = await admin_client.post(CERTIFICATES, json={"pem": ca.pem})
    listed = (await admin_client.get(CERTIFICATES)).json()

    assert added.status_code == 201, added.text
    body = added.json()
    assert (body["subject"], body["fingerprint"], body["added_by"]) == (
        "CN=Corp Root CA,O=Corp",
        ca.fingerprint,
        "root",
    )
    assert listed["total"] == 1 and listed["items"][0]["id"] == body["id"]


async def test_a_certificate_trusted_already_or_not_one_is_refused(admin_client):
    pem = authority().pem
    await admin_client.post(CERTIFICATES, json={"pem": pem})

    again = await admin_client.post(CERTIFICATES, json={"pem": pem})
    nothing = await admin_client.post(CERTIFICATES, json={"pem": "a certificate, honestly"})

    assert (again.status_code, error_code(again)) == (409, "conflict")
    assert (nothing.status_code, error_code(nothing)) == (422, "validation_error")
    assert nothing.json()["error"]["details"][0]["field"] == "pem"


async def test_adding_and_removing_a_certificate_changes_what_is_trusted_at_once(app, admin_client):
    ca = authority()
    async with https_server(ca) as port:
        added = (await admin_client.post(CERTIFICATES, json={"pem": ca.pem})).json()
        trusted = await remote.client_of(app).get(f"https://127.0.0.1:{port}/")

        removed = await admin_client.delete(f"{CERTIFICATES}/{added['id']}")
        after = app.state.trusted_certificates

    assert trusted.status_code == 200
    assert removed.status_code == 204
    assert after == []


async def test_what_a_host_presents_is_fetched_and_nothing_is_added(admin_client):
    ca = authority("Corp Root CA")
    async with https_server(ca) as port:
        fetched = await admin_client.post(
            f"{CERTIFICATES}/fetch", json={"host": "127.0.0.1", "port": port}
        )
    listed = (await admin_client.get(CERTIFICATES)).json()

    assert fetched.status_code == 200, fetched.text
    chain = fetched.json()["chain"]
    assert [item["subject"] for item in chain] == ["CN=127.0.0.1,O=Corp", "CN=Corp Root CA,O=Corp"]
    assert chain[1]["fingerprint"] == ca.fingerprint and chain[1]["pem"] == ca.pem
    assert listed["total"] == 0


async def test_a_host_that_cannot_be_reached_is_said(admin_client):
    failed = await admin_client.post(f"{CERTIFICATES}/fetch", json={"host": "127.0.0.1", "port": 1})
    odd = await admin_client.post(f"{CERTIFICATES}/fetch", json={"host": "evil.example/x"})

    assert (failed.status_code, error_code(failed)) == (502, "fetch_failed")
    assert "127.0.0.1:1" in failed.json()["error"]["message"]
    assert (odd.status_code, error_code(odd)) == (422, "validation_error")


async def test_removing_a_certificate_that_is_not_there_is_said(admin_client):
    gone = await admin_client.delete(f"{CERTIFICATES}/{uuid.uuid4()}")

    assert (gone.status_code, error_code(gone)) == (404, "not_found")

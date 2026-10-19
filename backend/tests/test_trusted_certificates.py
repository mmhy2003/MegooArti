"""Trusted certificates as they are read and kept, and what outbound TLS trusts (spec 6):
the usual authorities and the added certificates, from the start, and anew when they
change."""

import httpx
import pytest

from megooarti.errors import ApiError
from megooarti.repositories import remote
from megooarti.security import sources
from megooarti.system import certificates
from tests.clients import client_for
from tests.tls import authority, https_server, silent_server, unreadable_name


def test_a_certificate_is_read_with_what_a_person_checks_it_by():
    ca = authority("Corp Root CA")

    read = certificates.read_one(f"\n  {ca.pem}\n")

    assert read.subject == "CN=Corp Root CA,O=Corp"
    assert read.issuer == "CN=Corp Root CA,O=Corp"
    assert read.fingerprint == ca.fingerprint and len(read.fingerprint) == 64
    assert read.not_after == ca.certificate.not_valid_after_utc
    assert read.pem == ca.pem


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("", "Paste a certificate in PEM"),
        ("MIIBszCCAVmgAwIBAgIU", "Paste a certificate in PEM"),
        (
            "-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----",
            "not a certificate that can be read",
        ),
        (None, "one certificate at a time"),
    ],
    ids=["nothing", "no-pem", "not-a-certificate", "two"],
)
def test_anything_but_one_certificate_is_refused_at_the_pem(text, said):
    if text is None:
        text = authority("One").pem + authority("Two").pem

    with pytest.raises(ApiError) as refused:
        certificates.read_one(text)

    assert refused.value.status_code == 422
    assert refused.value.details[0]["field"] == "pem"
    assert said in refused.value.details[0]["message"]


async def test_the_outbound_client_trusts_an_added_certificate_and_not_before(app):
    ca = authority()
    async with https_server(ca) as port:
        address = f"https://127.0.0.1:{port}/"
        with pytest.raises(httpx.ConnectError):
            await remote.client_of(app).get(address)

        remote.trust(app, [ca.pem])
        answered = await remote.client_of(app).get(address)

        remote.trust(app, [])
        with pytest.raises(httpx.ConnectError):
            await remote.client_of(app).get(address)
    await remote.close_clients(app)

    assert answered.text == "served over TLS"


async def test_a_client_replaced_is_closed_only_when_the_server_shuts_down(app, monkeypatch):
    # A download under way with it may outlast any grace: it is never cut off.
    import asyncio

    monkeypatch.setattr(remote, "RETIRED_SECONDS", 0, raising=False)  # were there a grace
    first = remote.client_of(app)

    remote.trust(app, [authority().pem])
    second = remote.client_of(app)
    await asyncio.sleep(0.1)
    open_after_the_change = not first.is_closed
    await remote.close_clients(app)

    assert first is not second
    assert open_after_the_change
    assert first.is_closed and second.is_closed


async def test_what_a_source_reaches_trusts_the_added_certificates(app):
    ca = authority()
    remote.trust(app, [ca.pem])

    reach = sources.outbound(app)
    trusted = reach.tls.get_ca_certs(binary_form=True)

    assert ca.certificate.public_bytes(certificates.Encoding.DER) in trusted
    assert reach.http is remote.client_of(app)
    await remote.close_clients(app)


async def test_the_certificates_kept_are_trusted_from_the_start(app, sessionmaker):

    ca = authority()
    async with sessionmaker() as db:
        await certificates.add(db, certificates.read_one(ca.pem), "root")
        await db.commit()

    async with client_for(app), https_server(ca) as port:
        answered = await remote.client_of(app).get(f"https://127.0.0.1:{port}/")

    assert answered.status_code == 200


async def test_what_a_host_presents_is_fetched_its_own_certificate_first():
    ca = authority("Corp Root CA")
    async with https_server(ca) as port:
        chain = await certificates.fetch("127.0.0.1", port)

    assert [item.subject for item in chain] == ["CN=127.0.0.1,O=Corp", "CN=Corp Root CA,O=Corp"]
    assert chain[1].fingerprint == ca.fingerprint


async def test_a_host_that_does_not_answer_over_tls_is_said():
    with pytest.raises(certificates.FetchFailed) as failed:
        # Long enough for Windows to say that the port is closed, which takes it two seconds.
        await certificates.fetch("127.0.0.1", 1, seconds=8)

    assert "127.0.0.1:1 could not be reached over TLS" in str(failed.value)


async def test_an_older_private_authority_is_trusted_once_added(app):
    # Not critical BasicConstraints, no Authority Key Identifier in what it signs: as
    # many organisations' own authorities are, which Python 3.13's strict checks refuse.
    ca = authority("Old Corp CA", legacy=True)
    async with https_server(ca) as port:
        remote.trust(app, [ca.pem])
        answered = await remote.client_of(app).get(f"https://127.0.0.1:{port}/")
    await remote.close_clients(app)

    assert answered.text == "served over TLS"


def test_a_certificate_whose_names_cannot_be_read_is_refused_at_the_pem():
    with pytest.raises(ApiError) as refused:
        certificates.read_one(unreadable_name())

    assert (refused.value.status_code, refused.value.details[0]["field"]) == (422, "pem")


async def test_a_host_that_takes_the_connection_and_says_nothing_is_said_so():
    async with silent_server() as port:
        with pytest.raises(certificates.FetchFailed) as failed:
            await certificates.fetch("127.0.0.1", port, seconds=0.5)

    assert str(failed.value) == f"127.0.0.1:{port} gave no answer over TLS within 0.5 seconds."


async def test_a_host_named_so_that_it_is_no_name_is_said_not_raised():
    with pytest.raises(certificates.FetchFailed) as failed:
        await certificates.fetch("a..b", 443, seconds=2)

    assert "a..b:443" in str(failed.value)


async def test_an_ipv6_host_is_written_in_brackets():
    with pytest.raises(certificates.FetchFailed) as failed:
        await certificates.fetch("::1", 1, seconds=2)

    assert str(failed.value).startswith("[::1]:1 ")

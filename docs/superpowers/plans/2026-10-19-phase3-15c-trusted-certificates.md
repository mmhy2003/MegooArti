# External Identity: Trusted Certificates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator adds the organisation's own certificate authorities (or a server's self-signed certificate), by pasting one or by fetching what a server presents and checking its fingerprint, and from that moment every outbound TLS connection (proxies' remotes, OIDC providers, and LDAP in plan 15d) trusts them besides the usual authorities (SEC-18).

**Architecture:** `system/certificates.py` reads a certificate (`read_one`), keeps it (`trusted_certificates`, migration `0011`) and fetches what a host presents (`fetch`, with Python 3.13's unverified chain). `repositories/remote.py` builds one SSL context from httpx's authorities and the kept certificates (`tls_context`, `tls_of`), builds the shared client with it, and builds both anew when the certificates change (`trust`), retiring the client in use; the certificates are read at start. `sources.Outbound` gains `tls`, for what is not HTTP. `system/certificates_api.py` serves `/api/v1/certificates`; the web UI gains the Certificates screen.

**Tech Stack:** Python 3.13 (`ssl`, `asyncio`), `cryptography`, httpx, FastAPI, SQLAlchemy and Alembic; Next.js, React, TanStack Query, Vitest.

**Spec:** [docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md](../specs/2026-10-19-identity-audit-selectors-design.md): section 6, with 11, 12 and the row of plan 15c in 13; SEC-18.

## Decisions this plan settles

Task 3 writes these into the spec, as "Settled while building plan 15c".

| # | Decision | Reason |
| --- | --- | --- |
| C1 | What outbound TLS trusts is one SSL context, `remote.tls_context(pems)`: httpx's own authorities (certifi's, or those of `SSL_CERT_FILE`) and the added certificates. The shared client is built with it, and `sources.Outbound.tls` gives it to what is not HTTP (LDAP, 15d). | Section 6: the system's authorities and these, for every outbound connection. |
| C2 | The certificates are read at start, before anything goes out, and given anew when they change (`remote.trust`): new requests get a new client; the one in use is closed ten minutes after, or at shutdown. A list that did not change changes nothing. The server is one process, so this is the whole of it. | Section 6: the shared client is made again. Requests under way are not cut off. |
| C3 | A certificate is pasted one at a time, in PEM: an authority's or a server's own, expired or not (an expired one is kept, and shown as such). Its fingerprint is SHA-256 of its DER bytes, one record each (`409`); subject and issuer are kept as RFC 4514 says them. Who added it is kept by name. | Section 6's record. A name outlives the user. |
| C4 | Fetch connects over TLS directly (no StartTLS), without checking what is presented, for ten seconds, and answers the certificates the host sent, its own first (Python 3.13's unverified chain); a host that cannot be reached so is `502 fetch_failed`. It needs `admin:certificates:write`: it reaches out. | Section 6: fetch adds nothing; the fingerprint is checked by a person. A StartTLS server's authority is pasted. |
| C5 | Removing a certificate stops new connections trusting it; connections open are not undone. | As C2. |
| C6 | The screen is `/admin/certificates`: the list shows a fingerprint's first eight pairs; trusting a fetched certificate asks first, showing its whole fingerprint, in pairs. | Section 6: a fingerprint is confirmed before it is trusted. |

## Global Constraints

- **`trusted_certificates`: id, subject, issuer, fingerprint (SHA-256), not-after, PEM, added by and when** (section 6).
- **Fetching (`POST /api/v1/certificates/fetch`) adds nothing**; a certificate is added once its fingerprint is confirmed (section 6).
- **Permissions `admin:certificates:read` and `write`** (section 6).
- **Every outbound TLS connection trusts the system's authorities and these; the shared HTTP client is made again when the list changes** (section 6).
- **Every new list is paged** (section 11).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

What could hurt a person using this most, and which test of this plan pins it.

1. **A certificate trusted that a man in the middle presented:** fetching adds nothing, and trusting a fetched certificate asks first with its whole fingerprint. Task 2: `test_what_a_host_presents_is_fetched_and_nothing_is_added`; Task 3: the screen's test "are fetched from a server, and one is trusted only after its fingerprint is shown".
2. **A change of what is trusted that takes effect only after a restart, or not for every connection:** the client is built anew at once, for proxies and sources alike. Task 1: `test_the_outbound_client_trusts_an_added_certificate_and_not_before`, `test_what_a_source_reaches_trusts_the_added_certificates`; Task 2: `test_adding_and_removing_a_certificate_changes_what_is_trusted_at_once`.
3. **A restart that forgets what was trusted:** the certificates are read at start. Task 1: `test_the_certificates_kept_are_trusted_from_the_start`.
4. **Something kept that is not one certificate** (two, a key pasted by mistake, nonsense): refused at the field, and nothing kept. Task 1: `test_anything_but_one_certificate_is_refused_at_the_pem`; Task 2: `test_a_certificate_trusted_already_or_not_one_is_refused`.
5. **A host that does not answer, or not over TLS:** said with `502 fetch_failed` within seconds. Task 1: `test_a_host_that_does_not_answer_over_tls_is_said`; Task 2: `test_a_host_that_cannot_be_reached_is_said`.

---

### Task 1: What outbound TLS trusts

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0011_add_trusted_certificates.py`, `backend/src/megooarti/system/certificates.py`
- Modify: `backend/src/megooarti/system/models.py`, `backend/src/megooarti/repositories/remote.py`, `backend/src/megooarti/security/sources.py`, `backend/src/megooarti/main.py`
- Test: `backend/tests/tls.py` (an authority and an HTTPS server of the tests' own), `backend/tests/test_trusted_certificates.py`; modify `backend/tests/repositories/test_remote.py` (an application's state now holds what TLS trusts)

**Interfaces:**
- Consumes: `repositories.remote.new_client`, `client_of`; plan 15b's `sources.Outbound`, `outbound`; `main._first_start`; the fixtures `app`, `sessionmaker`; `tests.clients.client_for`.
- Produces:
  - Model `TrustedCertificate` (`id`, `subject`, `issuer`, `fingerprint`, `not_after`, `pem`, `added_by`, `added_at`).
  - `certificates.Described(subject, issuer, fingerprint, not_after, pem)`, `read_one(text) -> Described` (422 at `pem`), `list_certificates(db, limit, offset)`, `trusted_pems(db) -> list[str]`, `get_certificate(db, id)`, `add(db, described, by)` (409 if trusted already), `FetchFailed`, `fetch(host, port, *, seconds=10.0) -> list[Described]`, `FETCH_SECONDS`.
  - `remote.RETIRED_SECONDS`, `tls_context(pems) -> ssl.SSLContext`, `new_client(transport=None, verify=True)`, `tls_of(app)`, `client_of(app)`, `trust(app, pems)`, `close_clients(app)`; `app.state.trusted_certificates`, `tls`, `retired`, `retiring`.
  - `sources.Outbound.tls`.
  - For tests: `tests.tls` (`Issued` with `.pem`, `.fingerprint`; `authority(common_name)`, `server_certificate(ca, host)`, `https_server(ca)`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/tls.py`:

```python
"""An authority and an HTTPS server of the tests' own (spec 12): certificates made here,
signed by a CA nobody else trusts, served on 127.0.0.1 from this process."""

import asyncio
import datetime
import ssl
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Corp"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


@dataclass(frozen=True)
class Issued:
    certificate: x509.Certificate
    key: ec.EllipticCurvePrivateKey

    @property
    def pem(self) -> str:
        return self.certificate.public_bytes(serialization.Encoding.PEM).decode()

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint(hashes.SHA256()).hex()


def authority(common_name: str = "Corp Root CA") -> Issued:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(_name(common_name))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )  # fmt: skip
    return Issued(certificate, key)


def server_certificate(ca: Issued, host: str = "127.0.0.1") -> Issued:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(host))
        .issuer_name(ca.certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(IPv4Address(host))]), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.key.public_key()), critical=False
        )
        .sign(ca.key, hashes.SHA256())
    )  # fmt: skip
    return Issued(certificate, key)


async def _answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await reader.readuntil(b"\r\n\r\n")
        body = b"served over TLS"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    except (OSError, asyncio.IncompleteReadError, ssl.SSLError):
        pass  # a client that refused our certificate, or only looked at it
    finally:
        writer.close()


@asynccontextmanager
async def https_server(ca: Issued) -> AsyncIterator[int]:
    """An HTTPS server on 127.0.0.1, presenting a certificate of `ca` and `ca` itself: its port."""
    served = server_certificate(ca)
    with tempfile.TemporaryDirectory() as folder:
        chain, key = Path(folder) / "chain.pem", Path(folder) / "key.pem"
        chain.write_text(served.pem + ca.pem)
        key.write_bytes(
            served.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(chain, key)
    server = await asyncio.start_server(_answer, "127.0.0.1", 0, ssl=context)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()
```

Create `backend/tests/test_trusted_certificates.py`:

```python
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
from tests.tls import authority, https_server


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


async def test_a_client_replaced_is_closed_only_when_the_server_shuts_down_or_later(app):
    first = remote.client_of(app)

    remote.trust(app, [authority().pem])
    second = remote.client_of(app)
    await remote.close_clients(app)

    assert first is not second
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
        await certificates.fetch("127.0.0.1", 1, seconds=2)

    assert "127.0.0.1:1 could not be reached over TLS" in str(failed.value)
```

Change `backend/tests/repositories/test_remote.py`:

```diff
@@ -259,7 +259,10 @@ def test_a_credential_sealed_with_another_key_is_unreadable(tmp_path):
 
 
 async def test_the_outbound_client_is_built_once_when_first_needed():
-    application = SimpleNamespace(state=SimpleNamespace(http=None))
+    # As create_app leaves the state: no client yet, and nothing added to trust.
+    application = SimpleNamespace(
+        state=SimpleNamespace(http=None, tls=None, trusted_certificates=[])
+    )
 
     first = remote.client_of(application)
     try:
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/test_trusted_certificates.py tests/repositories/test_remote.py`
Expected: The tests do not load: `ImportError: cannot import name 'certificates' from 'megooarti.system'`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/system/models.py`:

```diff
@@ -1,12 +1,14 @@
 """Instance-wide settings that administrators change at runtime."""
 
+import uuid
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import DateTime, String, func
+from sqlalchemy import DateTime, String, Text, func
 from sqlalchemy.dialects.postgresql import JSONB
 from sqlalchemy.orm import Mapped, mapped_column
 
+from megooarti.clock import utcnow
 from megooarti.db.base import Base
 
 
@@ -18,3 +20,20 @@ class SystemSetting(Base):
     updated_at: Mapped[datetime] = mapped_column(
         DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
     )
+
+
+class TrustedCertificate(Base):
+    """A certificate every outbound TLS connection trusts, besides the authorities the
+    server trusts already: an organisation's own authority, or a server's own (spec 6)."""
+
+    __tablename__ = "trusted_certificates"
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    subject: Mapped[str] = mapped_column(String(1024))
+    issuer: Mapped[str] = mapped_column(String(1024))
+    # SHA-256 of the certificate's DER bytes, in lower-case hex: how a person checks it.
+    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
+    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
+    pem: Mapped[str] = mapped_column(Text)
+    added_by: Mapped[str] = mapped_column(String(64))  # the name, which outlives the user
+    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

Create `backend/src/megooarti/migrations/versions/0011_add_trusted_certificates.py`:

```python
"""add trusted certificates, which every outbound TLS connection trusts

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trusted_certificates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=1024), nullable=False),
        sa.Column("issuer", sa.String(length=1024), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pem", sa.Text(), nullable=False),
        sa.Column("added_by", sa.String(length=64), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trusted_certificates")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_trusted_certificates_fingerprint")),
    )


def downgrade() -> None:
    op.drop_table("trusted_certificates")
```

Create `backend/src/megooarti/system/certificates.py`:

```python
"""Trusted TLS certificates (spec 6, SEC-18): an organisation's own authorities, or a
server's own certificate, trusted by every outbound TLS connection besides the
authorities the server trusts already. Here are the certificates as they are kept, and
what a host presents when asked."""

import asyncio
import hashlib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.system.models import TrustedCertificate

# How long a host is given to present its certificates.
FETCH_SECONDS = 10.0
_PEM_BEGIN = "-----BEGIN CERTIFICATE-----"


@dataclass(frozen=True)
class Described:
    """A certificate as a person checks it, and as it is kept."""

    subject: str
    issuer: str
    fingerprint: str  # SHA-256 of its DER bytes, lower-case hex
    not_after: datetime
    pem: str


def _described(certificate: x509.Certificate) -> Described:
    der = certificate.public_bytes(Encoding.DER)
    return Described(
        subject=certificate.subject.rfc4514_string()[:1024],
        issuer=certificate.issuer.rfc4514_string()[:1024],
        fingerprint=hashlib.sha256(der).hexdigest(),
        not_after=certificate.not_valid_after_utc,
        pem=certificate.public_bytes(Encoding.PEM).decode("ascii"),
    )


def _invalid(message: str) -> ApiError:
    details = [{"field": "pem", "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def read_one(text: str) -> Described:
    """The one certificate pasted as PEM. Raises a 422 for anything else."""
    found = text.count(_PEM_BEGIN)
    if found == 0:
        raise _invalid("Paste a certificate in PEM: -----BEGIN CERTIFICATE----- and what follows.")
    if found > 1:
        raise _invalid("Paste one certificate at a time.")
    try:
        certificate = x509.load_pem_x509_certificate(text.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise _invalid("This is not a certificate that can be read.") from None
    return _described(certificate)


# --- The records ----------------------------------------------------------------------


async def list_certificates(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[TrustedCertificate], int]:
    total = await db.scalar(select(func.count()).select_from(TrustedCertificate))
    page = await db.scalars(
        select(TrustedCertificate)
        .order_by(TrustedCertificate.subject, TrustedCertificate.fingerprint)
        .limit(limit)
        .offset(offset)
    )
    return list(page), total or 0


async def trusted_pems(db: AsyncSession) -> list[str]:
    """Every trusted certificate, in PEM: what the outbound connections are given."""
    return list(
        await db.scalars(select(TrustedCertificate.pem).order_by(TrustedCertificate.added_at))
    )


async def get_certificate(db: AsyncSession, certificate_id: uuid.UUID) -> TrustedCertificate | None:
    return await db.get(TrustedCertificate, certificate_id)


async def add(db: AsyncSession, described: Described, by: str) -> TrustedCertificate:
    held = await db.scalar(
        select(TrustedCertificate.id).where(TrustedCertificate.fingerprint == described.fingerprint)
    )
    if held is not None:
        raise ApiError(409, "conflict", "This certificate is trusted already.")
    record = TrustedCertificate(
        subject=described.subject,
        issuer=described.issuer,
        fingerprint=described.fingerprint,
        not_after=described.not_after,
        pem=described.pem,
        added_by=by,
    )
    db.add(record)
    await db.flush()
    return record


# --- What a host presents ---------------------------------------------------------------


class FetchFailed(Exception):
    """The host could not be reached, or presented nothing over TLS."""


async def fetch(host: str, port: int, *, seconds: float = FETCH_SECONDS) -> list[Described]:
    """What a host presents over TLS at a port, its own certificate first: trusted or not,
    which is why it is asked. Nothing is kept."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # to see what is presented, whoever signed it
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            seconds,
        )
    except (OSError, ssl.SSLError, TimeoutError) as error:
        raise FetchFailed(f"{host}:{port} could not be reached over TLS: {error}") from None
    try:
        # Each as DER, its own first (Python 3.13).
        presented = writer.get_extra_info("ssl_object").get_unverified_chain() or []
        chain = [_described(x509.load_der_x509_certificate(der)) for der in presented]
    finally:
        writer.close()
    if not chain:
        raise FetchFailed(f"{host}:{port} presented no certificate.")
    return chain
```

Change `backend/src/megooarti/repositories/remote.py`:

```diff
@@ -11,10 +11,11 @@ import ipaddress
 import json
 import re
 import socket
+import ssl
 import time
 import weakref
 import zlib
-from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
+from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
 from dataclasses import dataclass, field
 from http.cookiejar import CookieJar
 from typing import Any
@@ -178,9 +179,27 @@ def refusal(remote_url: str, address: str) -> str | None:
     return None
 
 
-def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
+# How long a client replaced after the trusted certificates changed is left to finish
+# the requests it has under way: longer than any one of them may take.
+RETIRED_SECONDS = 600
+
+
+def tls_context(pems: Sequence[str]) -> ssl.SSLContext:
+    """What an outbound TLS connection trusts: the authorities the server trusts already
+    (httpx's, which honours SSL_CERT_FILE), and the certificates an administrator added
+    (spec 6)."""
+    context = httpx.create_ssl_context()
+    if pems:
+        context.load_verify_locations(cadata="\n".join(pems))
+    return context
+
+
+def new_client(
+    transport: httpx.AsyncBaseTransport | None = None, verify: ssl.SSLContext | bool = True
+) -> httpx.AsyncClient:
     return httpx.AsyncClient(
         transport=transport,
+        verify=verify,
         follow_redirects=True,  # httpx drops Authorization when the host changes
         max_redirects=5,
         timeout=httpx.Timeout(60.0, connect=10.0),
@@ -190,17 +209,54 @@ def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.Async
     )
 
 
-def client_of(app: Any) -> httpx.AsyncClient:
-    """The application's one outbound client, built the first time it is needed.
+def tls_of(app: Any) -> ssl.SSLContext:
+    """What the application's outbound TLS connections trust, built when first needed:
+    loading the authorities takes a noticeable fraction of a second."""
+    if app.state.tls is None:
+        app.state.tls = tls_context(app.state.trusted_certificates)
+    return app.state.tls
 
-    Building it loads the system's TLS trust store, which takes a noticeable fraction
-    of a second: too slow to do for every application start that never proxies.
-    """
+
+def client_of(app: Any) -> httpx.AsyncClient:
+    """The application's one outbound client, built the first time it is needed, and
+    again after the certificates it trusts changed (`trust`)."""
     if app.state.http is None:
-        app.state.http = new_client()
+        app.state.http = new_client(verify=tls_of(app))
     return app.state.http
 
 
+def trust(app: Any, pems: Sequence[str]) -> None:
+    """Trust these certificates from now on. The client in use is retired: requests under
+    way finish with it, and it is closed a while after; new ones get a new client."""
+    if list(pems) == app.state.trusted_certificates:
+        return  # nothing changed: the client in use trusts these already
+    app.state.trusted_certificates = list(pems)
+    app.state.tls = None
+    retired, app.state.http = app.state.http, None
+    if retired is not None:
+        app.state.retired.add(retired)
+        task = asyncio.get_running_loop().create_task(_close_later(app, retired))
+        app.state.retiring.add(task)
+        task.add_done_callback(app.state.retiring.discard)
+
+
+async def _close_later(app: Any, client: httpx.AsyncClient) -> None:
+    await asyncio.sleep(RETIRED_SECONDS)
+    app.state.retired.discard(client)
+    await client.aclose()
+
+
+async def close_clients(app: Any) -> None:
+    """At shutdown: the client in use, and those retired that are not closed yet."""
+    for task in list(app.state.retiring):
+        task.cancel()
+    for client in [app.state.http, *app.state.retired]:
+        if client is not None:
+            await client.aclose()
+    app.state.http = None
+    app.state.retired.clear()
+
+
 def authorization(settings: Settings, remote_auth: dict[str, Any]) -> str | None:
     """The Authorization header for a stored credential. Raises SecretUnreadable."""
     kind = remote_auth.get("type", "none")
```

Change `backend/src/megooarti/security/sources.py`:

```diff
@@ -7,6 +7,7 @@ secrets, and the users they make at a first sign-in and bring up to date at each
 
 import itertools
 import re
+import ssl
 import uuid
 from dataclasses import dataclass
 from typing import Any, ClassVar, Literal
@@ -20,7 +21,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.config import Settings
 from megooarti.errors import ApiError
-from megooarti.repositories.remote import client_of
+from megooarti.repositories.remote import client_of, tls_of
 from megooarti.secrets_box import seal, unseal
 from megooarti.security.models import AuthSource, Role, User, UserRole, UserSession
 from megooarti.security.sessions import delete_user_sessions
@@ -63,14 +64,15 @@ class Tested:
 
 @dataclass(frozen=True)
 class Outbound:
-    """How a source is reached: the server's one outbound HTTP client, which trusts what
-    the server trusts."""
+    """How a source is reached: the server's one outbound HTTP client, and for what is not
+    HTTP (LDAP) what its TLS trusts: the usual authorities and the added certificates."""
 
     http: httpx.AsyncClient
+    tls: ssl.SSLContext
 
 
 def outbound(app: Any) -> Outbound:
-    return Outbound(http=client_of(app))
+    return Outbound(http=client_of(app), tls=tls_of(app))
 
 
 class SourceUnavailable(Exception):
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -19,7 +19,7 @@ from megooarti.maintenance import run_exclusively, run_periodically
 from megooarti.mcp.endpoint import router as mcp_router
 from megooarti.mcp.server import Server as McpServer
 from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
-from megooarti.repositories import upkeep
+from megooarti.repositories import remote, upkeep
 from megooarti.repositories.api import router as repositories_router
 from megooarti.repositories.apk import format as _apk_format  # noqa: F401  (registers it)
 from megooarti.repositories.apt import format as _apt_format  # noqa: F401  (registers it)
@@ -46,6 +46,7 @@ from megooarti.security.api import users as users_api
 from megooarti.security.bootstrap import ensure_initial_admin_password
 from megooarti.storage import blobs
 from megooarti.storage.api import router as blob_stores_router
+from megooarti.system import certificates
 from megooarti.system.information_api import router as information_router
 from megooarti.system.settings_api import router as settings_router
 from megooarti.system.status import router as status_router
@@ -63,6 +64,8 @@ async def _first_start(app: FastAPI) -> None:
     await ensure_initial_admin_password(
         app.state.sessionmaker, app.state.settings, app.state.head_revision
     )
+    async with app.state.sessionmaker() as db:
+        remote.trust(app, await certificates.trusted_pems(db))  # before anything goes out
 
 
 async def _first_start_when_possible(app: FastAPI, last_error: str) -> None:
@@ -122,8 +125,7 @@ async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
     for task in background:
         with suppress(asyncio.CancelledError):
             await task
-    if app.state.http is not None:
-        await app.state.http.aclose()
+    await remote.close_clients(app)
     await app.state.engine.dispose()
 
 
@@ -149,6 +151,12 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.state.started_at = utcnow()
     # The one client for requests to proxy remotes. Tests replace it with a fake remote.
     app.state.http = None  # built by remote.client_of on first use: it is slow to create
+    # What outbound TLS trusts besides the usual authorities: read from the database at
+    # start, and changed with the certificates (spec 6).
+    app.state.trusted_certificates = []
+    app.state.tls = None
+    app.state.retired = set()  # clients replaced, closed once their requests are done
+    app.state.retiring = set()
     register_error_handlers(app)
     app.include_router(docs_router(f"{API_PREFIX}/openapi.json", "MegooArti API"))
     app.include_router(status_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/test_trusted_certificates.py tests/test_migrations.py tests/repositories/test_proxy.py tests/repositories/test_remote.py tests/security`
Expected: 526 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: trusted certificates kept, and trusted by every outbound TLS connection from the start and anew when they change"
```

---

### Task 2: The certificates' API

**Files:**
- Create: `backend/src/megooarti/system/certificates_api.py`
- Modify: `backend/src/megooarti/main.py`, `frontend/openapi.json` (written by a command), `docs/administration.md`
- Test: `backend/tests/test_certificates_api.py`

**Interfaces:**
- Consumes: Task 1's `certificates` and `remote.trust`; `tests.tls`; `require`; `pagination`.
- Produces: `GET`/`POST /api/v1/certificates`, `DELETE /api/v1/certificates/{id}`, `POST /api/v1/certificates/fetch` (`{"host", "port": 443}` → `{"chain": [...]}`, `502 fetch_failed`); schemas `CertificateView`, `CertificateOut`, `CertificateIn`, `FetchIn`, `Fetched`; the guide's "Trusted certificates" and `admin:certificates`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_certificates_api.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/test_certificates_api.py`
Expected: 6 failed, 1 passed: `/api/v1/certificates` is not there (`assert 404 == 201`, `assert (404, 404, 404) == (401, 403, 200)`). Removing one that is not there answers `404` already.

- [ ] **Step 3: Write the code and the guide**

Create `backend/src/megooarti/system/certificates_api.py`:

```python
"""Administration of trusted certificates (spec 6): what outbound TLS trusts besides the
usual authorities, added by pasting one or by fetching what a host presents."""

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import remote
from megooarti.security.authentication import Principal, require
from megooarti.system import certificates
from megooarti.system.models import TrustedCertificate

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/certificates", tags=["certificates"])

# A host as it is typed: a name, an IPv4 address, or an IPv6 one without its brackets.
_HOST = r"^[A-Za-z0-9.-]{1,253}$|^[0-9A-Fa-f:.]{2,45}$"


class CertificateView(BaseModel):
    """A certificate as a person checks it: by its fingerprint, which its owner can tell."""

    subject: str
    issuer: str
    fingerprint: str  # SHA-256, lower-case hex
    not_after: datetime
    pem: str


class CertificateOut(CertificateView):
    id: uuid.UUID
    added_by: str
    added_at: datetime


class CertificateIn(BaseModel):
    pem: str = Field(max_length=65536)


class FetchIn(BaseModel):
    host: str = Field(pattern=_HOST)
    port: int = Field(default=443, ge=1, le=65535)


class Fetched(BaseModel):
    """What the host presented, its own certificate first. Nothing was added."""

    chain: list[CertificateView]


async def _trust_again(request: Request, db: AsyncSession) -> None:
    """The outbound connections trust the certificates as they are now (spec 6)."""
    remote.trust(request.app, await certificates.trusted_pems(db))


@router.get("", response_model=Page[CertificateOut])
async def list_certificates(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:certificates:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await certificates.list_certificates(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=CertificateOut, status_code=201)
async def add_certificate(
    body: CertificateIn,
    request: Request,
    principal: Principal = Depends(require("admin:certificates:write")),
    db: AsyncSession = Depends(get_session),
) -> TrustedCertificate:
    """Trust a certificate: an authority's, or a server's own. Check its fingerprint first."""
    added = await certificates.add(db, certificates.read_one(body.pem), principal.user.username)
    await db.commit()
    await _trust_again(request, db)
    log.info(
        "certificate_trusted",
        subject=added.subject,
        fingerprint=added.fingerprint,
        by=principal.user.username,
    )
    return added


@router.post("/fetch", response_model=Fetched)
async def fetch_certificates(
    body: FetchIn,
    _: Principal = Depends(require("admin:certificates:write")),
) -> Fetched:
    """What a host presents over TLS at a port, trusted or not: to choose one to add,
    once its fingerprint is checked. Nothing is added."""
    try:
        chain = await certificates.fetch(body.host, body.port)
    except certificates.FetchFailed as error:
        raise ApiError(502, "fetch_failed", str(error)) from None
    return Fetched(chain=[CertificateView(**vars(item)) for item in chain])


@router.delete("/{certificate_id}", status_code=204)
async def delete_certificate(
    certificate_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("admin:certificates:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Trust a certificate no more. Connections made with it are not undone."""
    held = await certificates.get_certificate(db, certificate_id)
    if held is None:
        raise ApiError(404, "not_found", "No such certificate.")
    await db.delete(held)
    await db.commit()
    await _trust_again(request, db)
    log.info("certificate_removed", subject=held.subject, by=principal.user.username)
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -47,6 +47,7 @@ from megooarti.security.bootstrap import ensure_initial_admin_password
 from megooarti.storage import blobs
 from megooarti.storage.api import router as blob_stores_router
 from megooarti.system import certificates
+from megooarti.system.certificates_api import router as certificates_router
 from megooarti.system.information_api import router as information_router
 from megooarti.system.settings_api import router as settings_router
 from megooarti.system.status import router as status_router
@@ -168,6 +169,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(sources_api.router, prefix=API_PREFIX)
     app.include_router(settings_router, prefix=API_PREFIX)
     app.include_router(information_router, prefix=API_PREFIX)
+    app.include_router(certificates_router, prefix=API_PREFIX)
     app.include_router(blob_stores_router, prefix=API_PREFIX)
     app.include_router(repositories_router, prefix=API_PREFIX)
     app.include_router(content_api_router, prefix=API_PREFIX)
```

Change `frontend/openapi.json`:

```diff
@@ -256,6 +256,106 @@
         "title": "BlobStoreOut",
         "type": "object"
       },
+      "CertificateIn": {
+        "properties": {
+          "pem": {
+            "maxLength": 65536,
+            "title": "Pem",
+            "type": "string"
+          }
+        },
+        "required": [
+          "pem"
+        ],
+        "title": "CertificateIn",
+        "type": "object"
+      },
+      "CertificateOut": {
+        "properties": {
+          "added_at": {
+            "format": "date-time",
+            "title": "Added At",
+            "type": "string"
+          },
+          "added_by": {
+            "title": "Added By",
+            "type": "string"
+          },
+          "fingerprint": {
+            "title": "Fingerprint",
+            "type": "string"
+          },
+          "id": {
+            "format": "uuid",
+            "title": "Id",
+            "type": "string"
+          },
+          "issuer": {
+            "title": "Issuer",
+            "type": "string"
+          },
+          "not_after": {
+            "format": "date-time",
+            "title": "Not After",
+            "type": "string"
+          },
+          "pem": {
+            "title": "Pem",
+            "type": "string"
+          },
+          "subject": {
+            "title": "Subject",
+            "type": "string"
+          }
+        },
+        "required": [
+          "subject",
+          "issuer",
+          "fingerprint",
+          "not_after",
+          "pem",
+          "id",
+          "added_by",
+          "added_at"
+        ],
+        "title": "CertificateOut",
+        "type": "object"
+      },
+      "CertificateView": {
+        "description": "A certificate as a person checks it: by its fingerprint, which its owner can tell.",
+        "properties": {
+          "fingerprint": {
+            "title": "Fingerprint",
+            "type": "string"
+          },
+          "issuer": {
+            "title": "Issuer",
+            "type": "string"
+          },
+          "not_after": {
+            "format": "date-time",
+            "title": "Not After",
+            "type": "string"
+          },
+          "pem": {
+            "title": "Pem",
+            "type": "string"
+          },
+          "subject": {
+            "title": "Subject",
+            "type": "string"
+          }
+        },
+        "required": [
+          "subject",
+          "issuer",
+          "fingerprint",
+          "not_after",
+          "pem"
+        ],
+        "title": "CertificateView",
+        "type": "object"
+      },
       "ComponentDetail": {
         "properties": {
           "created": {
@@ -631,6 +731,44 @@
         "title": "ErrorResponse",
         "type": "object"
       },
+      "FetchIn": {
+        "properties": {
+          "host": {
+            "pattern": "^[A-Za-z0-9.-]{1,253}$|^[0-9A-Fa-f:.]{2,45}$",
+            "title": "Host",
+            "type": "string"
+          },
+          "port": {
+            "default": 443,
+            "maximum": 65535.0,
+            "minimum": 1.0,
+            "title": "Port",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "host"
+        ],
+        "title": "FetchIn",
+        "type": "object"
+      },
+      "Fetched": {
+        "description": "What the host presented, its own certificate first. Nothing was added.",
+        "properties": {
+          "chain": {
+            "items": {
+              "$ref": "#/components/schemas/CertificateView"
+            },
+            "title": "Chain",
+            "type": "array"
+          }
+        },
+        "required": [
+          "chain"
+        ],
+        "title": "Fetched",
+        "type": "object"
+      },
       "FolderDeleted": {
         "properties": {
           "deleted": {
@@ -949,6 +1087,37 @@
         "title": "Page[BlobStoreOut]",
         "type": "object"
       },
+      "Page_CertificateOut_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/CertificateOut"
+            },
+            "title": "Items",
+            "type": "array"
+          },
+          "limit": {
+            "title": "Limit",
+            "type": "integer"
+          },
+          "offset": {
+            "title": "Offset",
+            "type": "integer"
+          },
+          "total": {
+            "title": "Total",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "items",
+          "total",
+          "limit",
+          "offset"
+        ],
+        "title": "Page[CertificateOut]",
+        "type": "object"
+      },
       "Page_ComponentView_": {
         "properties": {
           "items": {
@@ -3800,6 +3969,181 @@
         ]
       }
     },
+    "/api/v1/certificates": {
+      "get": {
+        "operationId": "list_certificates_api_v1_certificates_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "limit",
+            "required": false,
+            "schema": {
+              "default": 50,
+              "maximum": 200,
+              "minimum": 1,
+              "title": "Limit",
+              "type": "integer"
+            }
+          },
+          {
+            "in": "query",
+            "name": "offset",
+            "required": false,
+            "schema": {
+              "default": 0,
+              "minimum": 0,
+              "title": "Offset",
+              "type": "integer"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_CertificateOut_"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "List Certificates",
+        "tags": [
+          "certificates"
+        ]
+      },
+      "post": {
+        "description": "Trust a certificate: an authority's, or a server's own. Check its fingerprint first.",
+        "operationId": "add_certificate_api_v1_certificates_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/CertificateIn"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "201": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/CertificateOut"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Add Certificate",
+        "tags": [
+          "certificates"
+        ]
+      }
+    },
+    "/api/v1/certificates/fetch": {
+      "post": {
+        "description": "What a host presents over TLS at a port, trusted or not: to choose one to add,\nonce its fingerprint is checked. Nothing is added.",
+        "operationId": "fetch_certificates_api_v1_certificates_fetch_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/FetchIn"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Fetched"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Fetch Certificates",
+        "tags": [
+          "certificates"
+        ]
+      }
+    },
+    "/api/v1/certificates/{certificate_id}": {
+      "delete": {
+        "description": "Trust a certificate no more. Connections made with it are not undone.",
+        "operationId": "delete_certificate_api_v1_certificates__certificate_id__delete",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "certificate_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "Certificate Id",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "204": {
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Delete Certificate",
+        "tags": [
+          "certificates"
+        ]
+      }
+    },
     "/api/v1/content": {
       "get": {
         "description": "The repositories the caller may browse.",
```

Change `docs/administration.md`:

```diff
@@ -106,6 +106,32 @@ the code flow, then make the source under Authentication, New OIDC source, or at
   and give package clients an API token, which they make under Account. Their tokens
   work until an administrator disables them, or turns the source off.
 
+### Trusted certificates
+
+MegooArti trusts the usual public authorities when it connects out over TLS: to a
+proxy's remote, to an OIDC provider, to an LDAP server. An organisation's own
+authority, or a server's self-signed certificate, is added under Administration,
+Certificates, or at `/api/v1/certificates`, and is trusted by all of them at once.
+
+- **Adding one.** Paste the certificate in PEM (`POST /api/v1/certificates` with
+  `{"pem": ...}`), one at a time. Or ask what a host presents: Fetch
+  (`POST /api/v1/certificates/fetch` with `{"host": ..., "port": 443}`) lists the
+  certificates the host sent, its own first and its authorities after, and adds
+  nothing. Check the fingerprint (SHA-256) of the one you choose with whoever runs
+  the authority or the server before you add it: whoever sits between you and the
+  host could present anything. A host that cannot be reached over TLS is said with
+  `502 fetch_failed`; for a server that starts TLS only when asked (LDAP's StartTLS),
+  paste its authority's certificate.
+- **Which one to add.** The authority's (the last of what a host presents) when the
+  organisation's servers are signed by it: every one of them is then trusted. The
+  server's own when it signs itself.
+- **Removing one** stops new connections trusting it; connections already open are
+  not undone. A certificate past its date is kept, and shown as expired: a connection
+  it would vouch for is refused.
+- The authorities trusted already are those the server's image comes with (Mozilla's,
+  through `certifi`), or those of the file named by `SSL_CERT_FILE`, as for any
+  Python program.
+
 The full API is described at `/api/docs`. The page is served with its own script and
 stylesheet, and asks nothing of another host.
 
@@ -124,6 +150,7 @@ area's name alone gives both.
 | `admin:blobstores` | The blob stores |
 | `admin:settings` | The base URL and anonymous access; to read, also what is running (`/api/v1/system/information`) |
 | `admin:security` | How people sign in: the sign-in sources and their order, the default role, and whether MegooArti's own users sign in |
+| `admin:certificates` | The certificates outbound TLS trusts besides the usual authorities; to write, also fetching what a host presents |
 
 What a repository holds is not given by these, but by `repository:` permissions:
 see [Repositories](repositories.md). Whoever may change roles, or the roles a user
```

Then write the API's description: (in `backend/`) `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`. The guide's new row is what `tests/test_documents.py` asks for every area a permission names.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/test_certificates_api.py tests/test_trusted_certificates.py tests/test_openapi_snapshot.py tests/test_documents.py tests/test_route_guards.py`
Expected: 170 passed.

- [ ] **Step 5: Commit**

```bash
git add backend frontend/openapi.json docs/administration.md
git commit -m "feat: the trusted certificates' API: listed, pasted, fetched from a host to be checked, removed"
```

---

### Task 3: The Certificates screen, and what the plan settled

**Files:**
- Create: `frontend/src/screens/certificates.tsx`, `frontend/src/app/(shell)/admin/certificates/page.tsx`
- Modify: `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`), `frontend/src/lib/api/types.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/navigation.ts`, `frontend/src/lib/administration.ts`, `frontend/src/lib/format.ts`, `frontend/messages/en.json`, `docs/web-ui.md`, `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`
- Test: `frontend/src/screens/certificates.test.tsx`; modify `frontend/src/lib/navigation.test.ts`, `frontend/src/components/shell.test.tsx`, `frontend/src/lib/lib.test.ts`

**Interfaces:**
- Consumes: Task 2's routes and schemas; the UI's `Table`, `ConfirmDialog`, `Facts`, `Time`, `TextAreaField`, `Pager`, `useNotify`, `refusalsOf`.
- Produces: `CERTIFICATES`; the navigation item `certificates` (`admin:certificates:read`); `useCertificates`, `useAddCertificate`, `useFetchCertificates`, `useDeleteCertificate`; `formatFingerprint`, `shortFingerprint`; the types `CertificateOut`, `CertificateView`; `CertificatesScreen`; the messages `certificates.*`, `nav.items.certificates`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/certificates.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { CertificatesScreen } from "./certificates";

const page = (items: unknown[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const PEM = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIU\n-----END CERTIFICATE-----\n";
const view = (subject: string, fingerprint: string, more: Record<string, unknown> = {}) => ({
  subject,
  issuer: "CN=Corp Root CA,O=Corp",
  fingerprint,
  not_after: "2031-05-17T00:00:00Z",
  pem: PEM,
  ...more,
});
const ROOT = {
  ...view("CN=Corp Root CA,O=Corp", "0f".repeat(32)),
  id: "root",
  added_by: "admin",
  added_at: "2026-10-19T08:00:00Z",
};
const OLD = {
  ...view("CN=Old CA,O=Corp", "aa".repeat(32), { not_after: "2020-01-01T00:00:00Z" }),
  id: "old",
  added_by: "dana",
  added_at: "2019-01-01T08:00:00Z",
};

function certificatesScreen(more: Routes = {}, session = ADMIN) {
  const api = mockApi({ "GET /certificates": { json: page([ROOT, OLD]) }, ...more });
  navigation.at("/admin/certificates");
  return { ...renderUi(<CertificatesScreen />, { session }), ...api };
}

describe("the trusted certificates (spec 6)", () => {
  test("are listed with who they are, who vouches for them, their fingerprint and expiry", async () => {
    certificatesScreen();

    const table = await screen.findByRole("table", { name: "Certificates" });
    const rows = within(table).getAllByRole("row").slice(1);
    const cells = (row: Element | undefined) =>
      within(row as HTMLElement)
        .getAllByRole("cell")
        .slice(0, 3)
        .map((cell) => cell.textContent);
    expect(cells(rows[0])).toEqual([
      "CN=Corp Root CA,O=Corp",
      "CN=Corp Root CA,O=Corp",
      "0F:0F:0F:0F:0F:0F:0F:0F…",
    ]);
    expect(within(rows[0] as HTMLElement).queryByText("Expired")).toBeNull();
    expect(within(rows[1] as HTMLElement).getByText("Expired")).toBeVisible();
    await expectAccessible();
  });

  test("say so when there is none", async () => {
    certificatesScreen({ "GET /certificates": { json: page([]) } });

    expect(await screen.findByText(/No certificate is added/)).toBeVisible();
  });

  test("take one pasted, and say where the server refuses it", async () => {
    const user = userEvent.setup();
    let tries = 0;
    const { calls } = certificatesScreen({
      "POST /certificates": () =>
        (tries += 1) === 1
          ? failure(422, "validation_error", "The request is not valid.", [
              { field: "pem", message: "Paste one certificate at a time." },
            ])
          : { status: 201, json: ROOT },
    });

    await user.click(await screen.findByLabelText("Certificate (PEM)"));
    await user.paste(PEM);
    await user.click(screen.getByRole("button", { name: "Trust this certificate" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Certificate (PEM)")).toHaveAccessibleDescription(
        /one certificate at a time/,
      ),
    );
    await user.click(screen.getByRole("button", { name: "Trust this certificate" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Trusted CN=Corp Root CA,O=Corp."));
    expect(of(calls, "POST")[1]?.body).toEqual({ pem: PEM });
    expect(screen.getByLabelText("Certificate (PEM)")).toHaveValue("");
  });

  test("are fetched from a server, and one is trusted only after its fingerprint is shown", async () => {
    const user = userEvent.setup();
    const LEAF = view("CN=ldap.corp.example", "11".repeat(32));
    const CA = view("CN=Corp Root CA,O=Corp", "0f".repeat(32));
    const { calls } = certificatesScreen({
      "POST /certificates/fetch": { json: { chain: [LEAF, CA] } },
      "POST /certificates": { status: 201, json: ROOT },
    });

    await user.type(await screen.findByLabelText("Host"), "ldap.corp.example");
    await user.clear(screen.getByLabelText("Port"));
    await user.type(screen.getByLabelText("Port"), "636");
    await user.click(screen.getByRole("button", { name: "Fetch" }));
    const presented = await screen.findByRole("list", { name: "What the server presented" });
    const [own, authority] = within(presented).getAllByRole("listitem");
    expect(own).toHaveTextContent("The server's own");
    expect(authority).toHaveTextContent("Its authority 1");
    await user.click(
      within(authority as HTMLElement).getByRole("button", { name: "Trust this certificate" }),
    );

    const dialog = screen.getByRole("alertdialog", { name: "Trust this certificate?" });
    expect(dialog).toHaveTextContent(
      "0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F",
    );
    expect(dialog).toHaveTextContent("Check its fingerprint");
    expect(of(calls, "POST").map((call) => call.path)).toEqual(["/certificates/fetch"]);
    await user.click(within(dialog).getByRole("button", { name: "Trust it" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Trusted CN=Corp Root CA,O=Corp."));
    expect(of(calls, "POST")[0]?.body).toEqual({ host: "ldap.corp.example", port: 636 });
    expect(of(calls, "POST")[1]?.body).toEqual({ pem: PEM });
  });

  test("say why a server could not be asked", async () => {
    const user = userEvent.setup();
    certificatesScreen({
      "POST /certificates/fetch": failure(
        502,
        "fetch_failed",
        "ldap.corp.example:636 could not be reached over TLS.",
      ),
    });

    await user.type(await screen.findByLabelText("Host"), "ldap.corp.example");
    await user.click(screen.getByRole("button", { name: "Fetch" }));

    expect(await screen.findByText(/could not be reached over TLS/)).toBeVisible();
  });

  test("are removed after a question", async () => {
    const user = userEvent.setup();
    const { calls } = certificatesScreen({ "DELETE /certificates/old": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Remove CN=Old CA,O=Corp" }));
    const dialog = screen.getByRole("alertdialog", { name: "Trust CN=Old CA,O=Corp no more?" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("CN=Old CA,O=Corp is trusted no more."),
    );
    expect(of(calls, "DELETE")).toHaveLength(1);
  });

  test("are shown, and not changed or fetched, to whoever may only read them", async () => {
    certificatesScreen({}, holding("admin:certificates:read"));

    await screen.findByRole("table", { name: "Certificates" });
    expect(screen.queryByLabelText("Host")).toBeNull();
    expect(screen.queryByLabelText("Certificate (PEM)")).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  });
});
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -83,6 +83,7 @@ describe("the navigation as it is", () => {
       ["roles", "/admin/roles"],
       ["anonymousAccess", "/admin/anonymous-access"],
       ["authentication", "/admin/authentication"],
+      ["certificates", "/admin/certificates"],
       ["manageRepositories", "/admin/repositories"],
       ["blobStores", "/admin/blob-stores"],
       ["system", "/admin/system"],
@@ -91,6 +92,10 @@ describe("the navigation as it is", () => {
     expect(administration({ ...ADMIN, permissions: ["admin:security:read"] })).toEqual([
       ["authentication", "/admin/authentication"],
     ]);
+    // What outbound TLS trusts is an area of its own (spec 6).
+    expect(administration({ ...ADMIN, permissions: ["admin:certificates:read"] })).toEqual([
+      ["certificates", "/admin/certificates"],
+    ]);
     expect(administration({ ...ADMIN, permissions: ["admin:roles:read"] })).toEqual([
       ["roles", "/admin/roles"],
     ]);
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -77,6 +77,7 @@ describe("the shell", () => {
       ["Roles", "/admin/roles"],
       ["Anonymous access", "/admin/anonymous-access"],
       ["Authentication", "/admin/authentication"],
+      ["Certificates", "/admin/certificates"],
       // Not "Repositories": that is the list for browsing, in the same navigation (R14).
       ["Manage repositories", "/admin/repositories"],
       ["Blob stores", "/admin/blob-stores"],
@@ -91,6 +92,7 @@ describe("the shell", () => {
       null,
       null,
       null,
+      null,
     ]);
   });
 
```

Change `frontend/src/lib/lib.test.ts`:

```diff
@@ -9,7 +9,14 @@ import { ADMIN, NOBODY, VISITOR } from "@/test/render";
 import { mockUploads } from "@/test/xhr";
 
 import { deleteFolder, may, takesUploads } from "./content";
-import { exactTime, formatBytes, readChecksum, relativeTime } from "./format";
+import {
+  exactTime,
+  formatBytes,
+  formatFingerprint,
+  readChecksum,
+  relativeTime,
+  shortFingerprint,
+} from "./format";
 import {
   browseHref,
   componentHref,
@@ -24,6 +31,20 @@ import {
   uploadHref,
 } from "./paths";
 
+describe("a fingerprint", () => {
+  const SHA256 = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";
+
+  test("is read out in pairs, in capitals, as people compare them", () => {
+    expect(formatFingerprint(SHA256)).toBe(
+      "0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0:0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0",
+    );
+  });
+
+  test("is cut to its first eight pairs in a list", () => {
+    expect(shortFingerprint(SHA256)).toBe("0F:1E:2D:3C:4B:5A:69:78…");
+  });
+});
+
 describe("a size", () => {
   test.each([
     [0, "0 B"],
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/screens/certificates.test.tsx src/lib/navigation.test.ts src/components/shell.test.tsx src/lib/lib.test.ts`
Expected: `certificates.test.tsx` does not load (`./certificates` is not there), and 4 failed: the navigation has no Certificates, and there is no fingerprint to format: 4 failed, 103 passed.

- [ ] **Step 3: Write the code, the guide and the spec's rows**

First (in `frontend/`): `pnpm gen:api`, which writes `src/lib/api/schema.d.ts` from Task 2's `openapi.json`.

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -246,6 +246,68 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/certificates": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /** List Certificates */
+        get: operations["list_certificates_api_v1_certificates_get"];
+        put?: never;
+        /**
+         * Add Certificate
+         * @description Trust a certificate: an authority's, or a server's own. Check its fingerprint first.
+         */
+        post: operations["add_certificate_api_v1_certificates_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/certificates/fetch": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        /**
+         * Fetch Certificates
+         * @description What a host presents over TLS at a port, trusted or not: to choose one to add,
+         *     once its fingerprint is checked. Nothing is added.
+         */
+        post: operations["fetch_certificates_api_v1_certificates_fetch_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/certificates/{certificate_id}": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        post?: never;
+        /**
+         * Delete Certificate
+         * @description Trust a certificate no more. Connections made with it are not undone.
+         */
+        delete: operations["delete_certificate_api_v1_certificates__certificate_id__delete"];
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/content": {
         parameters: {
             query?: never;
@@ -1119,6 +1181,58 @@ export interface components {
             /** Type */
             type: string;
         };
+        /** CertificateIn */
+        CertificateIn: {
+            /** Pem */
+            pem: string;
+        };
+        /** CertificateOut */
+        CertificateOut: {
+            /**
+             * Added At
+             * Format: date-time
+             */
+            added_at: string;
+            /** Added By */
+            added_by: string;
+            /** Fingerprint */
+            fingerprint: string;
+            /**
+             * Id
+             * Format: uuid
+             */
+            id: string;
+            /** Issuer */
+            issuer: string;
+            /**
+             * Not After
+             * Format: date-time
+             */
+            not_after: string;
+            /** Pem */
+            pem: string;
+            /** Subject */
+            subject: string;
+        };
+        /**
+         * CertificateView
+         * @description A certificate as a person checks it: by its fingerprint, which its owner can tell.
+         */
+        CertificateView: {
+            /** Fingerprint */
+            fingerprint: string;
+            /** Issuer */
+            issuer: string;
+            /**
+             * Not After
+             * Format: date-time
+             */
+            not_after: string;
+            /** Pem */
+            pem: string;
+            /** Subject */
+            subject: string;
+        };
         /** ComponentDetail */
         ComponentDetail: {
             /**
@@ -1270,6 +1384,24 @@ export interface components {
         ErrorResponse: {
             error: components["schemas"]["ErrorBody"];
         };
+        /** FetchIn */
+        FetchIn: {
+            /** Host */
+            host: string;
+            /**
+             * Port
+             * @default 443
+             */
+            port: number;
+        };
+        /**
+         * Fetched
+         * @description What the host presented, its own certificate first. Nothing was added.
+         */
+        Fetched: {
+            /** Chain */
+            chain: components["schemas"]["CertificateView"][];
+        };
         /** FolderDeleted */
         FolderDeleted: {
             /** Deleted */
@@ -1389,6 +1521,17 @@ export interface components {
             /** Total */
             total: number;
         };
+        /** Page[CertificateOut] */
+        Page_CertificateOut_: {
+            /** Items */
+            items: components["schemas"]["CertificateOut"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
         /** Page[ComponentView] */
         Page_ComponentView_: {
             /** Items */
@@ -2708,6 +2851,133 @@ export interface operations {
             };
         };
     };
+    list_certificates_api_v1_certificates_get: {
+        parameters: {
+            query?: {
+                limit?: number;
+                offset?: number;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_CertificateOut_"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    add_certificate_api_v1_certificates_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["CertificateIn"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            201: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["CertificateOut"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    fetch_certificates_api_v1_certificates_fetch_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["FetchIn"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Fetched"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    delete_certificate_api_v1_certificates__certificate_id__delete: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                certificate_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            204: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content?: never;
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
     list_repositories_api_v1_content_get: {
         parameters: {
             query?: {
```

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -61,6 +61,10 @@ export type Redirect = Schemas["Redirect"];
 /** A format the server has: its types, and the public repository a new proxy is given. */
 export type FormatOut = Schemas["FormatOut"];
 export type BlobStoreCreate = Schemas["BlobStoreCreate"];
+/** A certificate outbound TLS trusts besides the usual authorities (spec 6). */
+export type CertificateOut = Schemas["CertificateOut"];
+/** A certificate as a person checks it: what a host presented, before it is trusted. */
+export type CertificateView = Schemas["CertificateView"];
 /** What is running: version, schema, runtime, database. */
 export type Information = Schemas["Information"];
 
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -30,6 +30,7 @@ export const MANAGE_REPOSITORIES = "/admin/repositories" as Route;
 // As for a role: a repository may be called "new", and has `~` in no name.
 export const NEW_REPOSITORY = "/admin/repositories/~new" as Route;
 export const BLOB_STORES = "/admin/blob-stores" as Route;
+export const CERTIFICATES = "/admin/certificates" as Route;
 export const SYSTEM = "/admin/system" as Route;
 
 const segments = (path: string) => path.split("/").filter((segment) => segment !== "");
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -3,6 +3,7 @@
  * with the permission its API needs: the item is then shown only to those who hold it.
  */
 import {
+  BadgeCheck,
   Boxes,
   HardDrive,
   KeyRound,
@@ -22,6 +23,7 @@ import {
   ANONYMOUS_ACCESS,
   AUTHENTICATION,
   BLOB_STORES,
+  CERTIFICATES,
   MANAGE_REPOSITORIES,
   ROLES,
   SYSTEM,
@@ -38,6 +40,7 @@ export type ItemKey =
   | "roles"
   | "anonymousAccess"
   | "authentication"
+  | "certificates"
   | "manageRepositories"
   | "blobStores"
   | "system";
@@ -97,6 +100,12 @@ export const NAVIGATION: readonly NavArea[] = [
         icon: KeyRound,
         permission: "admin:security:read",
       },
+      {
+        key: "certificates",
+        href: CERTIFICATES,
+        icon: BadgeCheck,
+        permission: "admin:certificates:read",
+      },
       {
         key: "manageRepositories",
         href: MANAGE_REPOSITORIES,
```

Change `frontend/src/lib/administration.ts`:

```diff
@@ -10,6 +10,8 @@ import { api } from "@/lib/api/client";
 import type {
   BlobStoreCreate,
   BlobStoreOut,
+  CertificateOut,
+  CertificateView,
   FormatOut,
   IndexRebuilt,
   Information,
@@ -31,6 +33,7 @@ const MOST = 200;
 
 const REPOSITORIES = "repositories";
 const BLOB_STORES = "blob-stores";
+const CERTIFICATES = "certificates";
 // What the browsing screens fetched (lib/content.ts): a repository that was made,
 // changed or deleted is another one there too.
 const CONTENT = "content";
@@ -208,6 +211,40 @@ export function useDeleteBlobStore() {
   });
 }
 
+// --- Trusted certificates -------------------------------------------------------------------
+
+export function useCertificates(page: number) {
+  return useQuery({
+    queryKey: [CERTIFICATES, "list", page],
+    queryFn: () => api.get<Page<CertificateOut>>("/certificates", { query: paged(page) }),
+  });
+}
+
+export function useAddCertificate() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (pem: string) => api.post<CertificateOut>("/certificates", { pem }),
+    onSuccess: () => client.invalidateQueries({ queryKey: [CERTIFICATES] }),
+  });
+}
+
+/** What a host presents over TLS, to choose one to trust. Nothing is kept of it. */
+export function useFetchCertificates() {
+  return useMutation({
+    mutationFn: (where: { host: string; port: number }) =>
+      api.post<{ chain: CertificateView[] }>("/certificates/fetch", where),
+    gcTime: 0,
+  });
+}
+
+export function useDeleteCertificate() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (id: string) => api.delete<void>(`/certificates/${encodeURIComponent(id)}`),
+    onSuccess: () => client.invalidateQueries({ queryKey: [CERTIFICATES] }),
+  });
+}
+
 // --- The installation -----------------------------------------------------------------------
 
 export function useInformation() {
```

Change `frontend/src/lib/format.ts`:

```diff
@@ -16,6 +16,16 @@ export function formatBytes(bytes: number): string {
   return `${value.toFixed(digits)} ${UNITS[unit]}`;
 }
 
+/** A SHA-256 fingerprint as people read it out to each other: `AB:CD:…`, in pairs. */
+export function formatFingerprint(hex: string): string {
+  return (hex.toUpperCase().match(/../g) ?? []).join(":");
+}
+
+/** Its first eight pairs, enough to tell certificates apart in a list. */
+export function shortFingerprint(hex: string): string {
+  return `${formatFingerprint(hex.slice(0, 16))}…`;
+}
+
 const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
   ["year", 365 * 24 * 3600],
   ["month", 30 * 24 * 3600],
```

Change `frontend/messages/en.json`:

```diff
@@ -22,6 +22,7 @@
       "roles": "Roles",
       "anonymousAccess": "Anonymous access",
       "authentication": "Authentication",
+      "certificates": "Certificates",
       "manageRepositories": "Manage repositories",
       "blobStores": "Blob stores",
       "system": "System"
@@ -747,6 +748,48 @@
     "noForm": "A source of the kind {kind} is set up through the API.",
     "rowIncomplete": "Each row needs a group and a role."
   },
+  "certificates": {
+    "title": "Certificates",
+    "intro": "What this server trusts when it connects out over TLS (to proxies' remotes, OIDC providers and LDAP servers), besides the usual public authorities.",
+    "fetchTitle": "Fetch from a server",
+    "fetchIntro": "Ask a server what it presents, then trust one of its certificates: its authority's, to trust every server it signed, or its own. Nothing is trusted until you choose.",
+    "pasteTitle": "Paste a certificate",
+    "fields": {
+      "pem": "Certificate (PEM)",
+      "host": "Host",
+      "port": "Port"
+    },
+    "hints": {
+      "pem": "One certificate: -----BEGIN CERTIFICATE----- and what follows."
+    },
+    "portRule": "A port is a number from 1 to 65535.",
+    "fetch": "Fetch",
+    "presented": "What the server presented",
+    "own": "The server's own",
+    "authority": "Its authority {number}",
+    "fingerprint": "Fingerprint (SHA-256)",
+    "trustThis": "Trust this certificate",
+    "trustAsk": "Trust this certificate?",
+    "trustBody": "Check its fingerprint with whoever runs the authority or the server, by another way than this connection: whoever sits between you and the server could present anything.",
+    "trust": "Trust it",
+    "trusted": "Trusted {subject}.",
+    "add": "Trust this certificate",
+    "none": "No certificate is added: the usual public authorities alone are trusted.",
+    "columns": {
+      "subject": "Subject",
+      "issuer": "Issuer",
+      "fingerprint": "Fingerprint",
+      "expires": "Expires",
+      "added": "Added",
+      "actions": "Actions"
+    },
+    "expired": "Expired",
+    "remove": "Remove",
+    "removeNamed": "Remove {subject}",
+    "removeAsk": "Trust {subject} no more?",
+    "removeBody": "New connections no longer trust it; connections already open are not undone.",
+    "removed": "{subject} is trusted no more."
+  },
   "members": {
     "none": "It has no member yet, and so answers nothing.",
     "up": "Move {name} up",
```

Create `frontend/src/screens/certificates.tsx`:

```tsx
"use client";

import { Download, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager, Time } from "@/components/ui/details";
import { TextAreaField, TextField } from "@/components/ui/field";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import {
  AT_ONCE,
  useAddCertificate,
  useCertificates,
  useDeleteCertificate,
  useFetchCertificates,
} from "@/lib/administration";
import type { CertificateOut, CertificateView } from "@/lib/api/types";
import { formatFingerprint, shortFingerprint } from "@/lib/format";
import { CERTIFICATES, pageHref, pageOf } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
const PORT = /^[0-9]{1,5}$/;

function expired(certificate: { not_after: string }): boolean {
  return new Date(certificate.not_after).getTime() < Date.now();
}

/** A certificate as it is checked before it is trusted: who it is, who vouches for it, its fingerprint. */
function Described({ certificate }: { certificate: CertificateView }) {
  const t = useTranslations("certificates");
  return (
    <Facts>
      <Fact name={t("columns.subject")} mono>
        {certificate.subject}
      </Fact>
      <Fact name={t("columns.issuer")} mono>
        {certificate.issuer}
      </Fact>
      <Fact name={t("fingerprint")} copy={formatFingerprint(certificate.fingerprint)} mono>
        {formatFingerprint(certificate.fingerprint)}
      </Fact>
      <Fact name={t("columns.expires")}>
        <Time value={certificate.not_after} />
        {expired(certificate) ? (
          <StatusTag tone="danger" className="ml-2">
            {t("expired")}
          </StatusTag>
        ) : null}
      </Fact>
    </Facts>
  );
}

/** Asks before a certificate is trusted, with its fingerprint to check (spec 6). */
function Trust({
  asked,
  onDone,
}: {
  asked: CertificateView | null;
  onDone: (added: boolean) => void;
}) {
  const t = useTranslations("certificates");
  const notify = useNotify();
  const add = useAddCertificate();
  return (
    <ConfirmDialog
      open={asked !== null}
      onOpenChange={(open) => {
        if (!open) onDone(false);
      }}
      title={t("trustAsk")}
      confirmLabel={t("trust")}
      busy={add.isPending}
      onConfirm={() => {
        if (asked === null) return;
        add.mutate(asked.pem, {
          onSuccess: () => {
            notify(t("trusted", { subject: asked.subject }));
            onDone(true);
          },
          onError: () => onDone(false),
        });
      }}
    >
      <p className="mb-3">{t("trustBody")}</p>
      {asked ? <Described certificate={asked} /> : null}
      {add.isError ? <ErrorState error={add.error} className="mt-3" /> : null}
    </ConfirmDialog>
  );
}

/** Paste one certificate in PEM. */
function Paste() {
  const t = useTranslations("certificates");
  const notify = useNotify();
  const add = useAddCertificate();
  const [pem, setPem] = useState("");
  const refused = refusalsOf(add.error, ["pem"]);

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate(pem, {
      onSuccess: (added) => {
        notify(t("trusted", { subject: added.subject }));
        setPem("");
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <TextAreaField
        label={t("fields.pem")}
        hint={t("hints.pem")}
        rows={6}
        spellCheck={false}
        className="font-mono text-xs"
        value={pem}
        error={refused.at.pem}
        onChange={(event) => setPem(event.target.value)}
      />
      {add.isError && refused.elsewhere ? <ErrorState error={add.error} /> : null}
      <div>
        <Button type="submit" variant="primary" busy={add.isPending} disabled={pem.trim() === ""}>
          <Plus aria-hidden="true" className="size-4" />
          {t("add")}
        </Button>
      </div>
    </form>
  );
}

/** Ask a host what it presents, and trust one of them once its fingerprint is checked. */
function Fetch() {
  const t = useTranslations("certificates");
  const fetched = useFetchCertificates();
  const [host, setHost] = useState("");
  const [port, setPort] = useState("443");
  const [asked, setAsked] = useState<CertificateView | null>(null);
  const portWrong =
    PORT.test(port) && Number(port) >= 1 && Number(port) <= 65535 ? undefined : t("portRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (host.trim() === "" || portWrong) return;
    fetched.mutate({ host: host.trim(), port: Number(port) });
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-4" noValidate>
        <TextField
          label={t("fields.host")}
          className="min-w-64 flex-1"
          spellCheck={false}
          autoComplete="off"
          value={host}
          onChange={(event) => setHost(event.target.value)}
        />
        <TextField
          label={t("fields.port")}
          className="w-28"
          inputMode="numeric"
          value={port}
          error={portWrong}
          onChange={(event) => setPort(event.target.value)}
        />
        <Button type="submit" busy={fetched.isPending} disabled={host.trim() === ""}>
          <Download aria-hidden="true" className="size-4" />
          {t("fetch")}
        </Button>
      </form>
      {fetched.isError ? <ErrorState error={fetched.error} /> : null}
      {fetched.data ? (
        <ol className="flex flex-col gap-4" aria-label={t("presented")}>
          {fetched.data.chain.map((certificate, index) => (
            <li key={certificate.fingerprint} className="rounded-sm border border-line p-4">
              <p className="label-caps mb-3 text-fg-subtle">
                {index === 0 ? t("own") : t("authority", { number: index })}
              </p>
              <Described certificate={certificate} />
              <Button size="sm" className="mt-3" onClick={() => setAsked(certificate)}>
                {t("trustThis")}
              </Button>
            </li>
          ))}
        </ol>
      ) : null}
      <Trust asked={asked} onDone={() => setAsked(null)} />
    </div>
  );
}

/** Trusted certificates (spec 6, SEC-18): what outbound TLS trusts besides the usual authorities. */
export function CertificatesScreen() {
  const t = useTranslations("certificates");
  const session = useSession();
  const notify = useNotify();
  const page = pageOf(useSearchParams());
  const listed = useCertificates(page);
  const remove = useDeleteCertificate();
  const [removing, setRemoving] = useState<CertificateOut | null>(null);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:certificates:write");
  const pages = listed.data === undefined ? undefined : Math.ceil(listed.data.total / AT_ONCE);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      {mayWrite ? (
        <>
          <Panel className="p-6">
            <h2 className={H2}>{t("fetchTitle")}</h2>
            <p className="mb-4 text-fg-muted">{t("fetchIntro")}</p>
            <Fetch />
          </Panel>
          <Panel className="p-6">
            <h2 className={H2}>{t("pasteTitle")}</h2>
            <Paste />
          </Panel>
        </>
      ) : null}
      <Panel>
        {listed.isError ? (
          <ErrorState error={listed.error} onRetry={() => void listed.refetch()} className="m-4" />
        ) : !listed.data ? (
          <LoadingState />
        ) : listed.data.items.length === 0 ? (
          <p className="p-6 text-fg-muted">{t("none")}</p>
        ) : (
          <>
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.subject")}</Th>
                  <Th>{t("columns.issuer")}</Th>
                  <Th>{t("columns.fingerprint")}</Th>
                  <Th>{t("columns.expires")}</Th>
                  <Th>{t("columns.added")}</Th>
                  {mayWrite ? <Th className="text-right">{t("columns.actions")}</Th> : null}
                </tr>
              </thead>
              <tbody>
                {listed.data.items.map((certificate) => (
                  <tr key={certificate.id} className="hover:bg-raised">
                    <Td className="font-mono text-xs break-all">{certificate.subject}</Td>
                    <Td className="font-mono text-xs break-all text-fg-muted">
                      {certificate.issuer}
                    </Td>
                    <Td
                      className="font-mono text-xs whitespace-nowrap"
                      title={formatFingerprint(certificate.fingerprint)}
                    >
                      {shortFingerprint(certificate.fingerprint)}
                    </Td>
                    <Td className="whitespace-nowrap">
                      <Time value={certificate.not_after} />
                      {expired(certificate) ? (
                        <StatusTag tone="danger" className="ml-2">
                          {t("expired")}
                        </StatusTag>
                      ) : null}
                    </Td>
                    <Td className="text-fg-muted">
                      <span className="block">{certificate.added_by}</span>
                      <Time value={certificate.added_at} />
                    </Td>
                    {mayWrite ? (
                      <Td className="text-right">
                        <Button
                          size="sm"
                          aria-label={t("removeNamed", { subject: certificate.subject })}
                          onClick={() => {
                            remove.reset();
                            setRemoving(certificate);
                          }}
                        >
                          {t("remove")}
                        </Button>
                      </Td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </Table>
            {remove.isError ? <ErrorState error={remove.error} className="m-4" /> : null}
            <Pager
              page={page}
              pages={pages ?? 1}
              hrefFor={(target) => pageHref(CERTIFICATES, target)}
            />
          </>
        )}
      </Panel>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("removeAsk", { subject: removing?.subject ?? "" })}
        confirmLabel={t("remove")}
        busy={remove.isPending}
        onConfirm={() => {
          if (removing === null) return;
          remove.mutate(removing.id, {
            onSuccess: () => notify(t("removed", { subject: removing.subject })),
            onSettled: () => setRemoving(null),
          });
        }}
      >
        {t("removeBody")}
      </ConfirmDialog>
    </div>
  );
}
```

Create `frontend/src/app/(shell)/admin/certificates/page.tsx`:

```tsx
import type { Metadata } from "next";

import { CertificatesScreen } from "@/screens/certificates";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.certificates.title };

export default function Page() {
  return <CertificatesScreen />;
}
```

Change `docs/web-ui.md`:

```diff
@@ -73,6 +73,11 @@ repositories, blob stores and the installation's own settings.
     settings are changed and the redirect address to register at the provider is
     shown, with a copy button; New OIDC source makes one, off until it is turned on.
     A group's roles are rows: a group, and the role its members are given.
+  - **Certificates** lists what the server trusts when it connects out over TLS,
+    besides the usual public authorities, with each one's fingerprint and expiry.
+    Fetch asks a server what it presents, its own certificate first; a certificate
+    is trusted after a question that shows its whole fingerprint, to check with
+    whoever runs the server. One can also be pasted in PEM, and removed.
   - **Manage repositories** lists every repository as it is set up. A new one is made
     on one page: choose the format and the type, and the page shows what that
     combination has. A hosted repository has a deployment policy; a proxy has its
```

Change `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`:

```diff
@@ -135,6 +135,17 @@ Settled here, by the designer:
 - The screen (Administration, Certificates): add one by pasting PEM, or by fetching what a host and port present (`POST /api/v1/certificates/fetch`, which adds nothing), then confirming its fingerprint; delete one. Permissions `admin:certificates:read` and `write`.
 - Every outbound TLS connection (proxies' remotes, OIDC providers, LDAP's `ldaps://` and StartTLS) trusts the system's authorities and these. The shared HTTP client is made again when the list changes.
 
+### Settled while building plan 15c
+
+| # | What | Why |
+| --- | --- | --- |
+| C1 | What outbound TLS trusts is one SSL context, `remote.tls_context(pems)`: httpx's own authorities (certifi's, or those of `SSL_CERT_FILE`) and the added certificates. The shared client is built with it, and `sources.Outbound.tls` gives it to what is not HTTP (LDAP, 15d). | Section 6: the system's authorities and these, for every outbound connection. |
+| C2 | The certificates are read at start, before anything goes out, and given anew when they change (`remote.trust`): new requests get a new client; the one in use is closed ten minutes after, or at shutdown. A list that did not change changes nothing. The server is one process, so this is the whole of it. | Section 6: the shared client is made again. Requests under way are not cut off. |
+| C3 | A certificate is pasted one at a time, in PEM: an authority's or a server's own, expired or not (an expired one is kept, and shown as such). Its fingerprint is SHA-256 of its DER bytes, one record each (`409`); subject and issuer are kept as RFC 4514 says them. Who added it is kept by name. | Section 6's record. A name outlives the user. |
+| C4 | Fetch connects over TLS directly (no StartTLS), without checking what is presented, for ten seconds, and answers the certificates the host sent, its own first (Python 3.13's unverified chain); a host that cannot be reached so is `502 fetch_failed`. It needs `admin:certificates:write`: it reaches out. | Section 6: fetch adds nothing; the fingerprint is checked by a person. A StartTLS server's authority is pasted. |
+| C5 | Removing a certificate stops new connections trusting it; connections open are not undone. | As C2. |
+| C6 | The screen is `/admin/certificates`: the list shows a fingerprint's first eight pairs; trusting a fetched certificate asks first, showing its whole fingerprint, in pairs. | Section 6: a fingerprint is confirmed before it is trusted. |
+
 ## 7. LDAP (plan 15d)
 
 - Settings: the server's address (`ldap://` or `ldaps://`), StartTLS, the bind DN and password (sealed; none for an anonymous bind), the users' base DN and filter (`(uid={username})`, `(sAMAccountName={username})`; `{username}` escaped as RFC 4515 has it), the attributes of the user name, display name and email; groups from an attribute of the user (`memberOf`) or from a search (base, filter with `{dn}` or `{username}`, the group's name attribute); the group mapping. Timeouts of ten seconds.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/screens/certificates.test.tsx src/lib/navigation.test.ts src/components/shell.test.tsx src/lib/lib.test.ts && pnpm lint && pnpm typecheck`; then (in `backend/`) `uv run pytest -q tests/test_documents.py`
Expected: 114 passed; `All matched files use Prettier code style!`; the types check; then 147 passed.

- [ ] **Step 5: Run every test**

Run (in `backend/`): `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; then (in `frontend/`): `pnpm vitest run`
Expected: `440 files already formatted`, `All checks passed!`, 4190 passed, 2 skipped, 114 deselected; then 911 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend docs
git commit -m "feat(ui): the Certificates screen: fetch what a server presents, trust one once its fingerprint is checked, paste, remove; what plan 15c settled"
```

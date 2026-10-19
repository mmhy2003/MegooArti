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
from sqlalchemy.exc import IntegrityError
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
        return _described(certificate)  # its names are read here, and may not be names
    except (ValueError, UnicodeEncodeError):
        raise _invalid("This is not a certificate that can be read.") from None


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


async def _held(db: AsyncSession, fingerprint: str) -> uuid.UUID | None:
    return await db.scalar(
        select(TrustedCertificate.id).where(TrustedCertificate.fingerprint == fingerprint)
    )


async def add(db: AsyncSession, described: Described, by: str) -> TrustedCertificate:
    trusted_already = ApiError(409, "conflict", "This certificate is trusted already.")
    if await _held(db, described.fingerprint) is not None:
        raise trusted_already
    record = TrustedCertificate(
        subject=described.subject,
        issuer=described.issuer,
        fingerprint=described.fingerprint,
        not_after=described.not_after,
        pem=described.pem,
        added_by=by,
    )
    try:
        async with db.begin_nested():
            db.add(record)
    except IntegrityError:  # added by another request a moment before
        raise trusted_already from None
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
    where = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            seconds,
        )
    except TimeoutError:
        raise FetchFailed(f"{where} gave no answer over TLS within {seconds:g} seconds.") from None
    except (OSError, ssl.SSLError) as error:
        raise FetchFailed(f"{where} could not be reached over TLS: {error}") from None
    except ValueError:  # UnicodeError among them: a host that is no name
        raise FetchFailed(f"{where} is not a host that can be asked.") from None
    try:
        # Each as DER, its own first (Python 3.13).
        presented = writer.get_extra_info("ssl_object").get_unverified_chain() or []
        chain = [_described(x509.load_der_x509_certificate(der)) for der in presented]
    except ValueError:
        raise FetchFailed(f"{where} presented a certificate that cannot be read.") from None
    finally:
        writer.close()
    if not chain:
        raise FetchFailed(f"{where} presented no certificate.")
    return chain

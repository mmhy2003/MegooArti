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

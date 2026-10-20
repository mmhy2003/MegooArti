"""Administration of repositories."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.names import NewName
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import service, signing
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Repository, SigningKey
from megooarti.repositories.service import RepositoryView
from megooarti.secrets_box import seal
from megooarti.security.authentication import Principal, require
from megooarti.system import audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/repositories", tags=["repositories"])

DeploymentPolicy = Literal["allow_redeploy", "disable_redeploy", "read_only"]


class HostedSettings(BaseModel):
    # Every repository this server made has one. A row that has none is answered with
    # what is enforced for it.
    deployment_policy: DeploymentPolicy = service.NO_POLICY


class HostedIn(BaseModel):
    # Left out of a repository that is made, the server chooses: a Maven repository for
    # releases refuses to replace what was deployed, and every other one allows it.
    # Left out of one that is replaced, the policy it has is kept.
    deployment_policy: DeploymentPolicy | None = None


class NegativeCache(BaseModel):
    enabled: bool = True
    ttl_minutes: int = Field(default=1440, ge=1)


class RemoteAuthIn(BaseModel):
    type: Literal["none", "basic", "bearer"] = "none"
    username: str = Field(default="", max_length=255)
    # Write-only. Leave it out on an update to keep the stored secret.
    secret: str | None = Field(default=None, min_length=1, max_length=4096)


class ProxyIn(BaseModel):
    remote_url: str = Field(min_length=1, max_length=2048)
    content_max_age_minutes: int = Field(default=1440, ge=-1)
    metadata_max_age_minutes: int = Field(default=1440, ge=-1)
    negative_cache: NegativeCache = NegativeCache()
    remote_auth: RemoteAuthIn = RemoteAuthIn()
    blocked: bool = False
    auto_block: bool = True


class RemoteAuthOut(BaseModel):
    type: str
    username: str
    has_secret: bool


class ProxyOut(BaseModel):
    remote_url: str
    content_max_age_minutes: int
    metadata_max_age_minutes: int
    negative_cache: NegativeCache
    remote_auth: RemoteAuthOut
    blocked: bool
    auto_block: bool


class GroupSettings(BaseModel):
    members: list[str] = []


class ProxyStatus(BaseModel):
    blocked: bool
    auto_blocked_until: datetime | None
    failures: int
    last_error: str | None


class RepositoryOut(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: HostedSettings | None
    format_config: dict[str, Any]
    proxy: ProxyOut | None
    group: GroupSettings | None
    status: ProxyStatus | None


class RepositoryCreate(BaseModel):
    name: NewName
    format: str
    type: Literal["hosted", "proxy", "group"]
    online: bool = True
    blob_store: str | None = None
    hosted: HostedIn | None = None
    proxy: ProxyIn | None = None
    group: GroupSettings | None = None
    format_config: dict[str, Any] = {}


class RepositoryUpdate(BaseModel):
    online: bool = True
    hosted: HostedIn | None = None
    proxy: ProxyIn | None = None
    group: GroupSettings | None = None
    format_config: dict[str, Any] = {}
    # Accepted so a client can send back what it read, but they cannot change.
    format: str | None = None
    type: str | None = None
    blob_store: str | None = None


def _plain(model: BaseModel | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump()


def _told(view: RepositoryView) -> dict[str, Any]:
    """A repository as its records tell it: its settings, not how its remote is doing."""
    return {name: value for name, value in asdict(view).items() if name != "status"}


def _given(proxy: ProxyIn | None) -> list[str]:
    """The remote's secret, by its name, when one is given anew: its value is not recorded."""
    return ["proxy.remote_auth.secret"] if proxy and proxy.remote_auth.secret else []


def _proxy(settings: Settings, proxy: ProxyIn | None) -> dict[str, Any] | None:
    """The proxy settings as the service takes them, with the secret sealed."""
    if proxy is None:
        return None
    values = proxy.model_dump()
    secret = values["remote_auth"]["secret"]
    if secret is not None:
        if values["remote_auth"]["type"] == "bearer" and not (
            secret.isascii() and secret.isprintable()
        ):
            # It becomes an HTTP header as it is, and a header cannot carry anything else.
            details = [
                {
                    "field": "proxy.remote_auth.secret",
                    "message": "A bearer token must be printable ASCII.",
                }
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        values["remote_auth"]["secret"] = seal(settings, secret)
    return values


async def _load(db: AsyncSession, name: str) -> Repository:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    return repository


@router.get("", response_model=Page[RepositoryOut])
async def list_repositories(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await service.list_repositories(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=RepositoryOut, status_code=201)
async def create_repository(
    body: RepositoryCreate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await service.create_repository(
        db,
        name=body.name,
        format=body.format,
        type=body.type,
        online=body.online,
        blob_store=body.blob_store,
        hosted=_plain(body.hosted),
        proxy=_proxy(request.app.state.settings, body.proxy),
        group=_plain(body.group),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    audit.record(
        db,
        "repository.created",
        ("repository", repository.name),
        audit.diff(None, _told(view), secrets=_given(body.proxy)),
    )
    await db.commit()
    log.info("repository_created", repository=repository.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=RepositoryOut)
async def get_repository(
    name: str,
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    return await service.describe(db, await _load(db, name))


@router.put("/{name}", response_model=RepositoryOut)
async def update_repository(
    name: str,
    body: RepositoryUpdate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await _load(db, name)
    current = await service.describe(db, repository)
    fixed = {"format": current.format, "type": current.type, "blob_store": current.blob_store}
    for field, value in fixed.items():
        sent = getattr(body, field)
        if sent is not None and sent != value:
            raise ApiError(409, "immutable", f"A repository's {field} cannot be changed.")
    await service.update_repository(
        db,
        repository,
        online=body.online,
        hosted=_plain(body.hosted),
        proxy=_proxy(request.app.state.settings, body.proxy),
        group=_plain(body.group),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    audit.record(
        db,
        "repository.updated",
        ("repository", repository.name),
        audit.diff(_told(current), _told(view), secrets=_given(body.proxy)),
    )
    await db.commit()
    log.info("repository_updated", repository=repository.name, by=principal.user.username)
    return view


@router.delete("/{name}", status_code=204)
async def delete_repository(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    before = await service.describe(db, repository)
    await service.delete_repository(db, repository, utcnow())
    audit.record(db, "repository.deleted", ("repository", name), audit.diff(_told(before), None))
    await db.commit()
    log.info("repository_deleted", repository=name, by=principal.user.username)


@router.post("/{name}/invalidate-cache", status_code=204)
async def invalidate_cache(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    await service.invalidate_cache(db, repository)
    audit.record(db, "repository.cache_invalidated", ("repository", name))
    await db.commit()
    log.info("repository_cache_invalidated", repository=name, by=principal.user.username)


class IndexRebuilt(BaseModel):
    files: int  # looked at
    moved: int  # given to another component than they had, or to one at all
    components: int  # looked at
    removed: int  # that had no file left


@router.post("/{name}/rebuild-index", response_model=IndexRebuilt)
async def rebuild_index(
    name: str,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> IndexRebuilt:
    """Go through a repository again: every file to its component, every component its words.

    It repairs what an older version stored differently. The work is done in this
    request, a piece at a time, each piece committed: it can be repeated or interrupted.
    """
    repository = await _load(db, name)
    done = IndexRebuilt(files=0, moved=0, components=0, removed=0)
    if repository.type != "group":  # a group holds nothing of its own
        # Nobody's permission on the content is involved: this is the administrator's.
        context = await build_context(db, request.app.state.settings, repository, None)
        after: str | None = ""
        while after is not None:
            seen, moved, after = await context.reindex(after=after)
            await db.commit()
            done.files, done.moved = done.files + seen, done.moved + moved
        following, first = None, True
        while first or following is not None:
            seen, removed, following = await context.redescribe(after=following)
            await db.commit()
            done.components, done.removed = done.components + seen, done.removed + removed
            first = False
    audit.record(db, "repository.index_rebuilt", ("repository", name), audit.diff(None, done))
    await db.commit()
    log.info(
        "repository_index_rebuilt",
        repository=name,
        by=principal.user.username,
        **done.model_dump(),
    )
    return done


class SigningKeyOut(BaseModel):
    kind: str  # openpgp, or rsa for apk
    algorithm: str
    fingerprint: str
    public_key: str  # what clients install; the private key is never shown
    created_at: datetime
    # False when the installation's secret key does not unseal it (spec 9): nothing can
    # be signed until another is generated or imported.
    readable: bool


class SigningKeyImport(BaseModel):
    # A private key without a passphrase: ASCII-armoured OpenPGP, or PEM RSA for apk.
    private_key: str = Field(min_length=1, max_length=65536)


class SigningKeyGenerate(BaseModel):
    # What an OpenPGP key is made with (ed25519 unless said); an apk key is rsa4096.
    algorithm: Literal["ed25519", "rsa4096"] | None = None


def _shown(settings: Settings, key: SigningKey) -> SigningKeyOut:
    return SigningKeyOut(
        kind=key.kind,
        algorithm=key.algorithm,
        fingerprint=key.fingerprint,
        public_key=key.public_key,
        created_at=key.created_at,
        readable=signing.readable(settings, key),
    )


@router.get("/{name}/signing-key", response_model=SigningKeyOut)
async def get_signing_key(
    name: str,
    request: Request,
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> SigningKeyOut:
    """The key a hosted repository signs its indexes with. It is made if it is not there yet."""
    key = await signing.key_of(db, request.app.state.settings, await _load(db, name))
    shown = _shown(request.app.state.settings, key)
    await db.commit()
    return shown


@router.put("/{name}/signing-key", response_model=SigningKeyOut)
async def import_signing_key(
    name: str,
    body: SigningKeyImport,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> SigningKeyOut:
    """Sign with an administrator's own key from now on. Every client must install it."""
    repository = await _load(db, name)
    try:
        key = await signing.import_key(db, request.app.state.settings, repository, body.private_key)
    except signing.KeyUnusable as error:
        details = [{"field": "body.private_key", "message": str(error)}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None
    shown = _shown(request.app.state.settings, key)
    audit.record(
        db,
        "signing_key.imported",
        ("repository", name),
        audit.diff(None, {"fingerprint": shown.fingerprint}, secrets=["private_key"]),
    )
    await db.commit()
    log.info(
        "signing_key_imported",
        repository=name,
        fingerprint=shown.fingerprint,
        by=principal.user.username,
    )
    return shown


@router.post("/{name}/signing-key/generate", response_model=SigningKeyOut)
async def generate_signing_key(
    name: str,
    body: SigningKeyGenerate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> SigningKeyOut:
    """Sign with a new key from now on. Every client must install it."""
    repository = await _load(db, name)
    try:
        key = await signing.generate(db, request.app.state.settings, repository, body.algorithm)
    except signing.KeyUnusable as error:
        details = [{"field": "body.algorithm", "message": str(error)}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None
    shown = _shown(request.app.state.settings, key)
    audit.record(
        db,
        "signing_key.generated",
        ("repository", name),
        audit.diff(None, {"algorithm": shown.algorithm, "fingerprint": shown.fingerprint}),
    )
    await db.commit()
    log.info(
        "signing_key_generated",
        repository=name,
        fingerprint=shown.fingerprint,
        by=principal.user.username,
    )
    return shown

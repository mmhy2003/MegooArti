"""The keys repositories sign their indexes with.

A hosted repository of a format that signs has one key. It is made the first time it
is needed, so that every repository has one however it was made; an administrator may
generate another, or import their own. The private key is sealed with the
installation's secret key, as a proxy's password is, and no answer ever carries it.
A new key is a new revision of the repository: its indexes are signed again with it.

OpenPGP is done by Sequoia (`pysequoia`), whose signatures apt and dnf verify.
"""

import asyncio
from dataclasses import dataclass

import pysequoia
import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Repository, SigningKey
from megooarti.secrets_box import SecretUnreadable, seal, unseal

log = structlog.get_logger(__name__)

OPENPGP = "openpgp"
# What an administrator may ask for when generating a key, and what it is made with.
GENERATED = {"ed25519": pysequoia.CipherSuite.Cv25519, "rsa4096": pysequoia.CipherSuite.RSA4k}
DEFAULT_ALGORITHM = "ed25519"
# What an imported key's algorithm is called, by what Sequoia calls it.
_IMPORTED = {"EdDSA": "ed25519", "Ed25519": "ed25519", "RSAEncryptSign": "rsa", "RSASign": "rsa"}


class KeyUnusable(ValueError):
    """Text that is not a private key this server can sign with."""


@dataclass(frozen=True)
class Material:
    """A key as it is stored, before its private part is sealed."""

    algorithm: str
    fingerprint: str
    public_key: str
    private_key: str


def _signer(private_key: str) -> object:
    return pysequoia.Tsk.from_bytes(private_key.encode()).signer()


def _algorithm(signer: object) -> str:
    detached = pysequoia.sign(signer, b"", mode=pysequoia.SignatureMode.DETACHED)
    named = str(pysequoia.Sig.from_bytes(detached).key_algorithm).rpartition(".")[2]
    return _IMPORTED.get(named, named.lower())


def generate_openpgp(user_id: str, algorithm: str = DEFAULT_ALGORITHM) -> Material:
    """A new key that never expires, with a subkey that signs."""
    secret = pysequoia.Tsk.generate(
        user_id, profile=pysequoia.Profile.RFC4880, cipher_suite=GENERATED[algorithm]
    )
    certificate = secret.extract_certificate()
    return Material(algorithm, certificate.fingerprint.upper(), str(certificate), str(secret))


def read_openpgp(private_key: str) -> Material:
    """An administrator's key, checked: it must be private, unprotected, and able to sign."""
    try:
        secret = pysequoia.Tsk.from_bytes(private_key.encode())
        signer = secret.signer()
    except RuntimeError as error:
        said = str(error)
        if "encrypted" in said:
            raise KeyUnusable(
                "The key is protected by a passphrase. Export it without one."
            ) from None
        if "signing" in said:
            raise KeyUnusable("This is not a private key that can sign.") from None
        raise KeyUnusable("This is not an OpenPGP private key.") from None
    certificate = secret.extract_certificate()
    return Material(
        _algorithm(signer), certificate.fingerprint.upper(), str(certificate), str(secret)
    )


class Signer:
    """Signs with one repository's key."""

    def __init__(self, private_key: str) -> None:
        self._signer = _signer(private_key)

    def clear(self, data: bytes) -> bytes:
        """`data` with a signature around it, as `InRelease` is.

        The line ending at the end of `data` becomes the one before the signature, as
        GnuPG writes it: what is signed is the text without it.
        """
        text = data.removesuffix(b"\n")
        return pysequoia.sign(self._signer, text, mode=pysequoia.SignatureMode.CLEAR)

    def detached(self, data: bytes) -> bytes:
        """A signature of `data` on its own, as `Release.gpg` is."""
        return pysequoia.sign(self._signer, data, mode=pysequoia.SignatureMode.DETACHED)


def signs(repository: Repository) -> str | None:
    """The kind of key this repository signs with, or None if it signs nothing."""
    format = get_format(repository.format)
    if format is None or repository.type != "hosted":
        return None
    return format.signs


def _user_id(repository: Repository) -> str:
    return f"MegooArti {repository.name}"


async def _keep(
    db: AsyncSession, settings: Settings, repository: Repository, material: Material, kind: str
) -> SigningKey:
    """Store a key in place of any the repository has, and make a new revision of it."""
    values = {
        "kind": kind,
        "algorithm": material.algorithm,
        "fingerprint": material.fingerprint,
        "public_key": material.public_key,
        "private_key": seal(settings, material.private_key),
        "created_at": utcnow(),
    }
    await db.execute(
        insert(SigningKey)
        .values(repository_id=repository.id, **values)
        .on_conflict_do_update(index_elements=[SigningKey.repository_id], set_=values)
    )
    await db.execute(
        update(Repository)
        .where(Repository.id == repository.id)
        .values(
            revision=Repository.revision + 1,
            changed_at=utcnow(),
            updated_at=Repository.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    return await _stored(db, repository)


async def _stored(db: AsyncSession, repository: Repository) -> SigningKey | None:
    return await db.scalar(
        select(SigningKey)
        .where(SigningKey.repository_id == repository.id)
        .execution_options(populate_existing=True)
    )


def _signs_nothing() -> ApiError:
    return ApiError(404, "not_found", "This repository signs nothing: it has no signing key.")


async def key_of(db: AsyncSession, settings: Settings, repository: Repository) -> SigningKey:
    """The repository's key, made now if it has none. The caller commits.

    Two requests that both find none make one each, and the first to be stored is kept.
    """
    kind = signs(repository)
    if kind is None:
        raise _signs_nothing()
    held = await _stored(db, repository)
    if held is not None:
        return held
    material = generate_openpgp(_user_id(repository))
    await db.execute(
        insert(SigningKey)
        .values(
            repository_id=repository.id,
            kind=kind,
            algorithm=material.algorithm,
            fingerprint=material.fingerprint,
            public_key=material.public_key,
            private_key=seal(settings, material.private_key),
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=[SigningKey.repository_id])
    )
    return await _stored(db, repository)


async def generate(
    db: AsyncSession, settings: Settings, repository: Repository, algorithm: str
) -> SigningKey:
    """A new key in place of the repository's. The caller commits."""
    kind = signs(repository)
    if kind is None:
        raise _signs_nothing()
    # An RSA key takes a second or more to make: not on the loop that serves everyone.
    material = await asyncio.to_thread(generate_openpgp, _user_id(repository), algorithm)
    return await _keep(db, settings, repository, material, kind)


async def import_key(
    db: AsyncSession, settings: Settings, repository: Repository, private_key: str
) -> SigningKey:
    """An administrator's key in place of the repository's. Raises KeyUnusable."""
    kind = signs(repository)
    if kind is None:
        raise _signs_nothing()
    material = read_openpgp(private_key)
    return await _keep(db, settings, repository, material, kind)


def signer(settings: Settings, key: SigningKey) -> Signer:
    """What signs with a stored key."""
    try:
        return Signer(unseal(settings, key.private_key))
    except SecretUnreadable:
        log.error("signing_key_unreadable", repository_id=str(key.repository_id))
        raise ApiError(
            500,
            "signing_key_unreadable",
            "This repository's signing key cannot be read with the installation's secret key. "
            "An administrator must generate or import another.",
        ) from None

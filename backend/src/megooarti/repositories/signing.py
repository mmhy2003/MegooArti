"""The keys repositories sign their indexes with.

A hosted repository of a format that signs has one key. It is made the first time it
is needed, so that every repository has one however it was made; an administrator may
generate another, or import their own. The private key is sealed with the
installation's secret key, as a proxy's password is, and no answer ever carries it.
A new key is a new revision of the repository: its indexes are signed again with it.

OpenPGP is done by Sequoia (`pysequoia`), whose signatures apt and dnf verify. apk
knows RSA keys alone: those are made and used with `cryptography`, as Alpine's
`abuild-sign` uses OpenSSL.
"""

import asyncio
import hashlib
from dataclasses import dataclass

import pysequoia
import structlog
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
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
RSA = "rsa"
RSA_ALGORITHM = "rsa4096"
# The largest RSA key taken, and the longest text of one: a larger key takes seconds
# to read and to sign with, for nothing apk needs.
RSA_MOST_BITS = 8192
RSA_TEXT_MOST = 12_000
# What an administrator may ask for when generating a key, and what it is made with.
GENERATED = {"ed25519": pysequoia.CipherSuite.Cv25519, "rsa4096": pysequoia.CipherSuite.RSA4k}
DEFAULT_ALGORITHM = "ed25519"
# What an imported key's algorithm is called, by what Sequoia calls it.
_IMPORTED = {"EdDSA": "ed25519", "Ed25519": "ed25519", "RSAEncryptSign": "rsa", "RSASign": "rsa"}


class KeyUnusable(ValueError):
    """Text that is not a private key this server can sign with."""


class KeysUnusable(ValueError):
    """Text that is not one or more OpenPGP public keys."""


class Unverified(ValueError):
    """A signature that none of the keys it was checked with made, or that is not one."""


# The most a remote's public keys may be: Debian's whole keyring is 56 KiB.
PUBLIC_KEYS_MOST = 1024 * 1024


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


def read_public_keys(text: str) -> list[object]:
    """The OpenPGP public keys in armoured text: a remote's, which a group checks it with.

    Raises KeysUnusable for text that has none, is too long, or holds a private key.
    """
    if len(text.encode()) > PUBLIC_KEYS_MOST:
        raise KeysUnusable("The keys are longer than this server keeps.")
    try:
        certificates = pysequoia.Cert.split_bytes(text.encode())
    except RuntimeError:
        certificates = []
    if not certificates:
        raise KeysUnusable("This is not one or more OpenPGP public keys, armoured.")
    if "PRIVATE KEY BLOCK" in text:
        raise KeysUnusable("This holds a private key. Give the public keys only.")
    return certificates


def verify_clear(signed: bytes, certificates: list[object]) -> bytes:
    """The text a clear-signed message (an `InRelease`) says, if one of the keys signed it.

    Raises Unverified otherwise.
    """
    try:
        return pysequoia.verify(bytes=signed, store=lambda _: certificates).bytes
    except RuntimeError as error:
        raise Unverified(str(error).splitlines()[0]) from None


def verify_detached(data: bytes, signature: bytes, certificates: list[object]) -> None:
    """Raise Unverified unless one of the keys made this signature of `data`.

    A detached signature, as a remote's `repomd.xml.asc` is.
    """
    try:
        pysequoia.verify(
            bytes=data,
            store=lambda _: certificates,
            signature=pysequoia.Sig.from_bytes(signature),
        )
    except (RuntimeError, ValueError) as error:
        raise Unverified(
            str(error).splitlines()[0] if str(error) else "it is not a signature"
        ) from None


def signs(repository: Repository) -> str | None:
    """The kind of key this repository signs with, or None if it signs nothing.

    A hosted repository signs the indexes it writes, and a group those it puts together
    from its members'. A proxy passes its remote's signatures on, and has none.
    """
    format = get_format(repository.format)
    if format is None or repository.type not in ("hosted", "group"):
        return None
    if repository.type == "group" and "group" not in format.types:
        return None
    return format.signs


def generate_rsa() -> Material:
    """A new RSA key of 4096 bits, as apk's keys are."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    return _rsa_material(private)


def read_rsa(private_key: str) -> Material:
    """An administrator's RSA key, PEM, checked: private, unprotected, and RSA."""
    if len(private_key) > RSA_TEXT_MOST:
        raise KeyUnusable(f"The key is longer than one of {RSA_MOST_BITS} bits.")
    try:
        private = serialization.load_pem_private_key(private_key.encode(), password=None)
    except TypeError:
        raise KeyUnusable("The key is protected by a passphrase. Export it without one.") from None
    except (ValueError, UnsupportedAlgorithm):
        raise KeyUnusable("This is not a PEM private key.") from None
    if not isinstance(private, rsa.RSAPrivateKey):
        raise KeyUnusable("apk signs with RSA keys only; this is another kind.")
    if private.key_size < 2048:
        raise KeyUnusable("The key has fewer than 2048 bits, which apk refuses.")
    if private.key_size > RSA_MOST_BITS:
        raise KeyUnusable(f"The key has more than {RSA_MOST_BITS} bits.")
    return _rsa_material(private)


def _rsa_material(private: rsa.RSAPrivateKey) -> Material:
    public = private.public_key()
    der = public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    pem = public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    secret = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return Material(
        f"rsa{private.key_size}",
        hashlib.sha256(der).hexdigest().upper(),
        pem.decode(),
        secret.decode(),
    )


class RsaSigner:
    """Signs with one repository's RSA key, as `abuild-sign` does: PKCS#1 v1.5, SHA-1.

    The key is read when it first signs, where that is done: in a worker thread, as the
    indexes are written. It is not checked again, as it was when it was kept: checking a
    key of 4096 bits takes a quarter of a second.
    """

    def __init__(self, private_key: str) -> None:
        self._text = private_key
        self._key: rsa.RSAPrivateKey | None = None

    def sign(self, data: bytes) -> bytes:
        if self._key is None:
            self._key = serialization.load_pem_private_key(
                self._text.encode(), password=None, unsafe_skip_rsa_key_validation=True
            )
        return self._key.sign(data, padding.PKCS1v15(), hashes.SHA1())


def _made(kind: str, user_id: str, algorithm: str | None) -> Material:
    """A new key of a kind: OpenPGP of the algorithm asked for, or RSA 4096."""
    if kind == RSA:
        if algorithm not in (None, RSA_ALGORITHM):
            raise KeyUnusable("An apk repository's key is RSA of 4096 bits (rsa4096).")
        return generate_rsa()
    return generate_openpgp(user_id, algorithm or DEFAULT_ALGORITHM)


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
    material = await asyncio.to_thread(_made, kind, _user_id(repository), None)
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
    db: AsyncSession, settings: Settings, repository: Repository, algorithm: str | None
) -> SigningKey:
    """A new key in place of the repository's. The caller commits.

    Raises KeyUnusable for an algorithm the repository's kind of key cannot have.
    """
    kind = signs(repository)
    if kind is None:
        raise _signs_nothing()
    # An RSA key takes a second or more to make: not on the loop that serves everyone.
    material = await asyncio.to_thread(_made, kind, _user_id(repository), algorithm)
    return await _keep(db, settings, repository, material, kind)


async def import_key(
    db: AsyncSession, settings: Settings, repository: Repository, private_key: str
) -> SigningKey:
    """An administrator's key in place of the repository's. Raises KeyUnusable."""
    kind = signs(repository)
    if kind is None:
        raise _signs_nothing()
    read = read_rsa if kind == RSA else read_openpgp
    material = await asyncio.to_thread(read, private_key)  # checking a key takes time
    return await _keep(db, settings, repository, material, kind)


def signer(settings: Settings, key: SigningKey) -> Signer | RsaSigner:
    """What signs with a stored key: a Signer of OpenPGP, or an RsaSigner."""
    try:
        private = unseal(settings, key.private_key)
    except SecretUnreadable:
        log.error("signing_key_unreadable", repository_id=str(key.repository_id))
        raise ApiError(
            500,
            "signing_key_unreadable",
            "This repository's signing key cannot be read with the installation's secret key. "
            "An administrator must generate or import another.",
        ) from None
    return RsaSigner(private) if key.kind == RSA else Signer(private)

"""The keys a repository signs its indexes with: made, replaced, sealed, and signing."""

import pysequoia
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from sqlalchemy import select

from megooarti.errors import ApiError
from megooarti.repositories import signing
from megooarti.repositories.models import Repository, SigningKey
from megooarti.repositories.raw import RawFormat
from megooarti.secrets_box import forget_keys
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.apt.packages import DATA
from tests.repositories.yum.packages import DATA as YUM_DATA

KEYS = "/api/v1/repositories/files/signing-key"


class Signing(RawFormat):
    """Raw, as a format whose hosted repositories sign."""

    signs = signing.OPENPGP


@pytest.fixture
def signs(monkeypatch):
    """Raw repositories sign, for these tests."""
    monkeypatch.setattr(signing, "get_format", lambda name: Signing())


def verified(data: bytes, signature: bytes, public_key: str) -> bool:
    certificate = pysequoia.Cert.from_bytes(public_key.encode())
    try:
        pysequoia.verify(
            bytes=data,
            store=lambda _: [certificate],
            signature=pysequoia.Sig.from_bytes(signature),
        )
    except RuntimeError:
        return False
    return True


async def revision_of(db, repository_id) -> int:
    return await db.scalar(
        select(Repository.revision)
        .where(Repository.id == repository_id)
        .execution_options(populate_existing=True)
    )


@pytest.mark.parametrize("algorithm", ["ed25519", "rsa4096"])
def test_a_generated_key_signs_what_its_public_key_verifies(algorithm):
    material = signing.generate_openpgp("MegooArti files", algorithm)
    signer = signing.Signer(material.private_key)

    assert material.algorithm == algorithm
    assert material.public_key.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
    assert "PRIVATE" not in material.public_key
    assert verified(
        b"Origin: MegooArti\n", signer.detached(b"Origin: MegooArti\n"), material.public_key
    )
    assert not verified(
        b"Origin: Other\n", signer.detached(b"Origin: MegooArti\n"), material.public_key
    )


def test_a_generated_key_never_expires():
    material = signing.generate_openpgp("MegooArti files")

    assert pysequoia.Cert.from_bytes(material.public_key.encode()).expiration is None


def test_a_clear_signature_holds_the_text_it_signs():
    material = signing.generate_openpgp("MegooArti files")

    signed = signing.Signer(material.private_key).clear(b"Origin: MegooArti\nSuite: stable\n")

    assert signed.startswith(b"-----BEGIN PGP SIGNED MESSAGE-----\n")
    assert b"\n\nOrigin: MegooArti\nSuite: stable\n-----BEGIN PGP SIGNATURE-----" in signed
    certificate = pysequoia.Cert.from_bytes(material.public_key.encode())
    said = pysequoia.verify(bytes=signed, store=lambda _: [certificate])
    assert said.bytes == b"Origin: MegooArti\nSuite: stable"  # the last line ending is not signed


def test_an_administrators_key_without_a_passphrase_is_taken():
    material = signing.read_openpgp((DATA / "plain-rsa.asc").read_text(encoding="utf-8"))

    assert material.algorithm == "rsa"
    assert material.fingerprint == "AEB16C233E235E56B1B5D3A5AE7BA4F3CDD5118B"
    assert material.public_key.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ((DATA / "protected.asc").read_text(encoding="utf-8"), "protected by a passphrase"),
        ((DATA / "plain-rsa.pub.asc").read_text(encoding="utf-8"), "not a private key"),
        ("-----BEGIN PGP PRIVATE KEY BLOCK-----\nnonsense\n", "not an OpenPGP private key"),
        ("a password", "not an OpenPGP private key"),
    ],
    ids=["protected", "public", "broken", "text"],
)
def test_a_key_the_server_cannot_sign_with_is_refused(text, said):
    with pytest.raises(signing.KeyUnusable, match=said):
        signing.read_openpgp(text)


async def test_a_repository_is_given_a_key_the_first_time_one_is_needed(db, settings, files, signs):
    key = await signing.key_of(db, settings, files)
    await db.commit()

    again = await signing.key_of(db, settings, files)

    assert (key.kind, key.algorithm) == ("openpgp", "ed25519")
    assert again.fingerprint == key.fingerprint
    assert key.private_key.startswith("enc:v1:")
    assert "PRIVATE KEY" not in key.private_key
    assert await revision_of(db, files.id) == 0  # nothing was signed before it


async def test_of_two_requests_that_found_no_key_the_first_keeps_its_own(
    db, settings, files, signs, monkeypatch
):
    first = await signing.key_of(db, settings, files)
    await db.commit()
    stored = signing._stored
    looked = []

    async def found_none_the_first_time(session, repository):
        looked.append(1)
        return None if len(looked) == 1 else await stored(session, repository)

    monkeypatch.setattr(signing, "_stored", found_none_the_first_time)

    second = await signing.key_of(db, settings, files)

    assert second.fingerprint == first.fingerprint


async def test_a_new_key_takes_the_place_of_the_old_and_is_a_new_revision(
    db, settings, files, signs
):
    old = (await signing.key_of(db, settings, files)).fingerprint
    await db.commit()

    new = await signing.generate(db, settings, files, "ed25519")
    await db.commit()

    assert new.fingerprint != old
    assert await revision_of(db, files.id) == 1
    assert len((await db.scalars(select(SigningKey))).all()) == 1


async def test_an_imported_key_takes_the_place_of_the_old(db, settings, files, signs):
    await signing.key_of(db, settings, files)

    key = await signing.import_key(
        db, settings, files, (DATA / "plain-rsa.asc").read_text(encoding="utf-8")
    )

    assert (key.algorithm, key.fingerprint) == ("rsa", "AEB16C233E235E56B1B5D3A5AE7BA4F3CDD5118B")
    assert await revision_of(db, files.id) == 1


async def test_a_repository_whose_format_signs_nothing_has_no_key(db, settings, files):
    with pytest.raises(ApiError) as refused:
        await signing.key_of(db, settings, files)

    assert (refused.value.status_code, refused.value.code) == (404, "not_found")


async def test_a_key_sealed_with_another_secret_key_is_said_to_be_unreadable(
    db, settings, files, signs
):
    key = await signing.key_of(db, settings, files)
    other = settings.model_copy(update={"secret_key": "another installation's key"})
    forget_keys()

    with pytest.raises(ApiError) as refused:
        signing.signer(other, key)

    assert (refused.value.status_code, refused.value.code) == (500, "signing_key_unreadable")
    forget_keys()


async def test_the_api_shows_the_public_key_and_never_the_private_one(admin_client, signs):
    await admin_client.post(
        "/api/v1/repositories", json={"name": "files", "format": "raw", "type": "hosted"}
    )

    shown = await admin_client.get(KEYS)

    assert shown.status_code == 200
    body = shown.json()
    assert set(body) == {"kind", "algorithm", "fingerprint", "public_key", "created_at"}
    assert (body["kind"], body["algorithm"]) == ("openpgp", "ed25519")
    assert "PRIVATE" not in shown.text
    assert (await admin_client.get(KEYS)).json()["fingerprint"] == body["fingerprint"]


async def test_the_api_generates_and_imports_keys(admin_client, signs):
    await admin_client.post(
        "/api/v1/repositories", json={"name": "files", "format": "raw", "type": "hosted"}
    )

    generated = await admin_client.post(f"{KEYS}/generate", json={"algorithm": "rsa4096"})
    imported = await admin_client.put(
        KEYS, json={"private_key": (DATA / "plain-rsa.asc").read_text(encoding="utf-8")}
    )
    refused = await admin_client.put(
        KEYS, json={"private_key": (DATA / "protected.asc").read_text(encoding="utf-8")}
    )

    assert (generated.status_code, generated.json()["algorithm"]) == (200, "rsa4096")
    assert imported.json()["fingerprint"] == "AEB16C233E235E56B1B5D3A5AE7BA4F3CDD5118B"
    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "body.private_key"
    assert (await admin_client.get(KEYS)).json()["algorithm"] == "rsa"


async def test_the_api_needs_the_permissions_of_repositories(
    admin_client, other_client, db, make_user, signs
):
    await admin_client.post(
        "/api/v1/repositories", json={"name": "files", "format": "raw", "type": "hosted"}
    )
    await roles.create_role(db, "repository-readers", "", ["admin:repositories:read"], [])
    await db.commit()
    await make_user("dana", roles=["repository-readers"])
    dana = basic("dana", PASSWORD)

    assert (await other_client.get(KEYS)).status_code == 401
    assert (await other_client.get(KEYS, headers=dana)).status_code == 200
    assert (await other_client.post(f"{KEYS}/generate", json={}, headers=dana)).status_code == 403
    assert (
        await other_client.put(KEYS, json={"private_key": "x"}, headers=dana)
    ).status_code == 403


async def test_the_api_says_a_repository_that_signs_nothing_has_no_key(admin_client):
    await admin_client.post(
        "/api/v1/repositories", json={"name": "files", "format": "raw", "type": "hosted"}
    )

    answer = await admin_client.get(KEYS)

    assert (answer.status_code, error_code(answer)) == (404, "not_found")


def test_a_remotes_public_keys_are_read_from_armoured_text():
    keys = signing.read_public_keys(
        (DATA / "debian-archive-keyring.asc").read_text(encoding="utf-8")
    )

    assert len(keys) == 9


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("not a key", "not one or more OpenPGP public keys"),
        ((DATA / "plain-rsa.asc").read_text(encoding="utf-8"), "holds a private key"),
        ("x" * (signing.PUBLIC_KEYS_MOST + 1), "longer than this server keeps"),
    ],
    ids=["text", "private", "long"],
)
def test_text_that_is_not_public_keys_is_refused(text, said):
    with pytest.raises(signing.KeysUnusable, match=said):
        signing.read_public_keys(text)


def test_a_clear_signed_message_is_read_if_one_of_the_keys_signed_it():
    keys = signing.read_public_keys(
        (DATA / "debian-archive-keyring.asc").read_text(encoding="utf-8")
    )
    signed = (DATA / "debian-trixie-InRelease").read_bytes()

    text = signing.verify_clear(signed, keys)

    assert text.startswith(b"Origin: Debian\nLabel: Debian\n")


def test_a_clear_signed_message_none_of_the_keys_signed_is_refused():
    other = signing.read_public_keys(signing.generate_openpgp("Someone else").public_key)
    signed = (DATA / "debian-trixie-InRelease").read_bytes()
    altered = signed.replace(b"Origin: Debian", b"Origin: Debiam")
    debian = signing.read_public_keys(
        (DATA / "debian-archive-keyring.asc").read_text(encoding="utf-8")
    )

    with pytest.raises(signing.Unverified):
        signing.verify_clear(signed, other)
    with pytest.raises(signing.Unverified):
        signing.verify_clear(altered, debian)
    with pytest.raises(signing.Unverified):
        signing.verify_clear(b"Origin: Debian\n", debian)


def test_a_detached_signature_one_of_the_keys_made_is_taken():
    keys = signing.read_public_keys((YUM_DATA / "RPM-GPG-KEY-Rocky-10").read_text(encoding="utf-8"))
    repomd = (YUM_DATA / "rocky-10-baseos-repomd.xml").read_bytes()

    signing.verify_detached(
        repomd, (YUM_DATA / "rocky-10-baseos-repomd.xml.asc").read_bytes(), keys
    )


def test_a_detached_signature_none_of_the_keys_made_is_refused():
    rocky = signing.read_public_keys(
        (YUM_DATA / "RPM-GPG-KEY-Rocky-10").read_text(encoding="utf-8")
    )
    other = signing.read_public_keys(signing.generate_openpgp("Someone else").public_key)
    repomd = (YUM_DATA / "rocky-10-baseos-repomd.xml").read_bytes()
    signature = (YUM_DATA / "rocky-10-baseos-repomd.xml.asc").read_bytes()

    with pytest.raises(signing.Unverified):
        signing.verify_detached(repomd, signature, other)
    with pytest.raises(signing.Unverified):
        signing.verify_detached(repomd.replace(b"primary", b"primarx"), signature, rocky)
    with pytest.raises(signing.Unverified):
        signing.verify_detached(repomd, b"not a signature", rocky)


# --- RSA keys, for apk ----------------------------------------------------------------

APK_KEYS = "/api/v1/repositories/apk-hosted/signing-key"


def test_an_rsa_key_signs_what_its_public_key_verifies():
    key = signing.generate_rsa()

    signature = signing.RsaSigner(key.private_key).sign(b"an index")

    public = serialization.load_pem_public_key(key.public_key.encode())
    public.verify(signature, b"an index", padding.PKCS1v15(), hashes.SHA1())
    assert key.algorithm == "rsa4096" and len(key.fingerprint) == 64
    assert key.public_key.startswith("-----BEGIN PUBLIC KEY-----")


def test_an_administrators_rsa_key_is_taken_as_abuild_keygen_makes_one():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    traditional = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    material = signing.read_rsa(traditional)

    assert material.algorithm == "rsa2048"


@pytest.mark.parametrize(
    ("make", "said"),
    [
        (lambda: "not a key", "not a PEM private key"),
        (
            lambda: (
                rsa.generate_private_key(public_exponent=65537, key_size=2048)
                .private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.BestAvailableEncryption(b"secret"),
                )
                .decode()
            ),
            "passphrase",
        ),
        (
            lambda: (
                ec.generate_private_key(ec.SECP256R1())
                .private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                .decode()
            ),
            "RSA keys only",
        ),
        (
            lambda: (
                rsa.generate_private_key(public_exponent=65537, key_size=1024)
                .private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                .decode()
            ),
            "fewer than 2048 bits",
        ),
    ],
)
def test_an_rsa_key_the_server_cannot_sign_with_is_refused(make, said):
    with pytest.raises(signing.KeyUnusable, match=said):
        signing.read_rsa(make())


async def test_an_apk_repository_has_an_rsa_key_and_never_an_openpgp_one(admin_client):
    await admin_client.post(
        "/api/v1/repositories", json={"name": "apk-hosted", "format": "apk", "type": "hosted"}
    )

    shown = (await admin_client.get(APK_KEYS)).json()
    generated = await admin_client.post(f"{APK_KEYS}/generate", json={})
    openpgp = await admin_client.post(f"{APK_KEYS}/generate", json={"algorithm": "ed25519"})
    imported = await admin_client.put(
        APK_KEYS, json={"private_key": (DATA / "plain-rsa.asc").read_text(encoding="utf-8")}
    )

    assert (shown["kind"], shown["algorithm"]) == ("rsa", "rsa4096")
    assert (generated.status_code, generated.json()["algorithm"]) == (200, "rsa4096")
    assert generated.json()["fingerprint"] != shown["fingerprint"]
    assert (openpgp.status_code, openpgp.json()["error"]["details"][0]["field"]) == (
        422,
        "body.algorithm",
    )
    assert (imported.status_code, imported.json()["error"]["details"][0]["field"]) == (
        422,
        "body.private_key",
    )


async def test_an_openpgp_key_is_ed25519_unless_another_is_asked_for(admin_client, signs):
    await admin_client.post(
        "/api/v1/repositories", json={"name": "files", "format": "raw", "type": "hosted"}
    )

    generated = await admin_client.post(f"{KEYS}/generate", json={})

    assert generated.json()["algorithm"] == "ed25519"

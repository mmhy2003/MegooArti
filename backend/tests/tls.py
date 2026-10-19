"""An authority and an HTTPS server of the tests' own (spec 12): certificates made here,
signed by a CA nobody else trusts, served on 127.0.0.1 from this process."""

import asyncio
import base64
import datetime
import ssl
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, getcontext
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
    legacy: bool = False

    @property
    def pem(self) -> str:
        return self.certificate.public_bytes(serialization.Encoding.PEM).decode()

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint(hashes.SHA256()).hex()


def authority(common_name: str = "Corp Root CA", *, legacy: bool = False) -> Issued:
    """A CA. `legacy`, as older private authorities are: BasicConstraints not critical,
    and the certificates it signs with no Authority Key Identifier."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(_name(common_name))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=not legacy)
    )
    if legacy:
        return Issued(builder.sign(key, hashes.SHA256()), key, legacy=True)
    certificate = (
        builder
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


def _alternative(host: str) -> x509.GeneralName:
    """A host as a certificate names it: an address, or a DNS name."""
    try:
        return x509.IPAddress(IPv4Address(host))
    except ValueError:
        return x509.DNSName(host)


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
        .add_extension(x509.SubjectAlternativeName([_alternative(host)]), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    )  # fmt: skip
    if not ca.legacy:
        certificate = certificate.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.key.public_key()), critical=False
        )
    return Issued(certificate.sign(ca.key, hashes.SHA256()), key)


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


def unreadable_name() -> str:
    """A certificate, in PEM, whose issuer's name is not one: read only when it is asked for."""
    der = bytearray(authority("ZZZZ-name").certificate.public_bytes(serialization.Encoding.DER))
    at = der.find(b"ZZZZ-name")  # the issuer's, which comes first
    der[at - 2] = 0x01  # its string's type made a BOOLEAN
    return (
        x509.load_der_x509_certificate(bytes(der)).public_bytes(serialization.Encoding.PEM).decode()
    )


@asynccontextmanager
async def silent_server() -> AsyncIterator[int]:
    """A server that takes a connection and never says a word: its port."""
    held: list[asyncio.StreamWriter] = []

    async def hold(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        held.append(writer)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        for writer in held:
            writer.close()
        server.close()
        await server.wait_closed()


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


def _der_integer(value: int) -> bytes:
    body = value.to_bytes((value.bit_length() + 8) // 8, "big")  # a leading 0: positive
    return b"\x02" + _der_length(len(body)) + body


def _der_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    size = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(size)]) + size


def ffdhe2048() -> bytes:
    """RFC 7919's ffdhe2048 group as PKCS #3 DH parameters, in PEM: how a TLS server is
    given them. Computed from the RFC's definition, at once, where generating some takes
    minutes."""
    getcontext().prec = 800
    e, term = Decimal(0), Decimal(1)
    for k in range(1, 400):
        e += term
        term /= k
    p = 2**2048 - 2**1984 + (int(Decimal(2) ** 1918 * e) + 560316) * 2**64 - 1
    body = _der_integer(p) + _der_integer(2)
    der = b"\x30" + _der_length(len(body)) + body
    text = base64.b64encode(der).decode()
    lines = [text[at : at + 64] for at in range(0, len(text), 64)]
    pem = ["-----BEGIN DH PARAMETERS-----", *lines, "-----END DH PARAMETERS-----", ""]
    return "\n".join(pem).encode()

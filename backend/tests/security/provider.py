"""An OIDC provider that exists only in the tests' process (spec 12): its metadata, its
keys, made here, and its token endpoint, which checks what a real one does (the code,
the redirect address, PKCE, the client's secret) and signs ID tokens with those keys."""

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from megooarti.repositories.remote import new_client

ISSUER = "https://sso.example/realms/corp"
CLIENT_ID = "megooarti"
CLIENT_SECRET = "the client's secret: with a colon"


def query_of(address: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(address).query).items()}


class Key:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def public_jwk(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key()))
        return {**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}

    def sign(self, claims: dict[str, Any], **header: Any) -> str:
        return jwt.encode(
            claims, self.private, algorithm="RS256", headers={"kid": self.kid, **header}
        )


class FakeProvider:
    def __init__(self) -> None:
        self.keys = [Key("key-1")]
        self.people: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.asked: list[str] = []  # the paths asked of it, in order
        self.down = False
        self.issuer_said = ISSUER  # what its metadata calls it
        # Changes to the next ID token's claims, or how it is signed, as a test wants.
        self.claims_changed: dict[str, Any] = {}
        self.signer: Key | None = None
        self.token_error: str | None = None

    def person(self, login: str, **claims: Any) -> None:
        self.people[login] = {"sub": f"subject-of-{login}", "preferred_username": login, **claims}

    def client(self) -> httpx.AsyncClient:
        return new_client(httpx.MockTransport(self._answer))

    # --- what a browser does there -------------------------------------------------------

    def authorize(self, address: str, login: str) -> str:
        """The person signs in at the provider: a code for the client's redirect address."""
        asked = query_of(address)
        assert address.startswith(f"{ISSUER}/protocol/openid-connect/auth?"), address
        assert asked["response_type"] == "code" and asked["client_id"] == CLIENT_ID
        assert asked["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        self.codes[code] = {
            "login": login,
            "nonce": asked["nonce"],
            "challenge": asked["code_challenge"],
            "redirect_uri": asked["redirect_uri"],
        }
        return code

    def rotate(self) -> None:
        """Sign with a new key from now on, as providers do now and then."""
        self.keys = [Key(f"key-{len(self.keys) + 1}")]

    # --- the provider's own addresses ------------------------------------------------------

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("the provider is down", request=request)
        path = request.url.path
        if path == "/realms/corp/.well-known/openid-configuration":
            return httpx.Response(200, json=self._metadata())
        if path == "/realms/corp/protocol/openid-connect/certs":
            return httpx.Response(200, json={"keys": [key.public_jwk() for key in self.keys]})
        if path == "/realms/corp/protocol/openid-connect/token" and request.method == "POST":
            return self._token(request)
        return httpx.Response(404)

    def _metadata(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer_said,
            "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
            "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
            "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        }

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {name: values[0] for name, values in parse_qs(request.content.decode()).items()}
        expected = base64.b64encode(
            b"megooarti:the%20client%27s%20secret%3A%20with%20a%20colon"
        ).decode()
        if request.headers.get("Authorization") != f"Basic {expected}":
            return httpx.Response(401, json={"error": "invalid_client"})
        given = self.codes.pop(form.get("code", ""), None)
        if self.token_error or given is None:
            return httpx.Response(400, json={"error": self.token_error or "invalid_grant"})
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if challenge != given["challenge"] or form.get("redirect_uri") != given["redirect_uri"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "nonce": given["nonce"],
            **self.people[given["login"]],
            **self.claims_changed,
        }
        claims = {name: value for name, value in claims.items() if value is not None}
        token = (self.signer or self.keys[0]).sign(claims)
        return httpx.Response(
            200, json={"id_token": token, "access_token": "x", "token_type": "Bearer"}
        )

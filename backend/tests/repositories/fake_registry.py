"""An in-process stand-in for a container registry. No test touches the network.

It behaves as public registries do where a proxy has to cope: it wants a token from a
service on another host, it may keep its blobs on a third, and it lists tags a page at
a time. Every host name reaches it; what was asked of which host is recorded.
"""

import base64
import hashlib
import json
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from megooarti.repositories.remote import new_client

REGISTRY = "https://registry.test"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def basic(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, registry: "FakeRegistry") -> None:
        self._registry = registry
        self._inner = httpx.ASGITransport(app=registry.app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._registry.down:
            raise httpx.ConnectError("connection refused", request=request)
        return await self._inner.handle_async_request(request)


class FakeRegistry:
    def __init__(self) -> None:
        self.manifests: dict[tuple[str, str], tuple[bytes, str]] = {}  # (image, tag or digest)
        self.blobs: dict[tuple[str, str], bytes] = {}  # (image, digest)
        self.requests: list[dict] = []
        # Signing in: where the token service is, and who may sign in.
        self.wants_token = True
        self.realm = "https://auth.registry.test/token"
        self.service = "registry.test"
        self.accounts: dict[str, str] = {}
        self.private: set[str] = set()  # images only an account may read
        self.token_seconds: int | None = 300
        self.token_answer: bytes | None = None  # what the token service says instead
        self.challenge: str | None = None  # what a refusal says instead of where to sign in
        self.issued: dict[str, tuple[str | None, str]] = {}  # token -> (account, scope)
        # How it serves.
        self.digest_header = True
        self.blobs_at: str | None = None  # another host that holds the blobs
        self.page_size: int | None = None
        self.down = False
        self.status: int | None = None
        self.status_of: dict[str, int] = {}  # "GET /v2/..." -> what that one request gets
        self.token_headers: dict[str, str] = {}  # sent with the token service's answer
        routes = [
            Route("/token", self._token, methods=["GET"]),
            Route("/cdn/{digest}", self._cdn, methods=["GET", "HEAD"]),
            Route("/v2/{rest:path}", self._serve, methods=["GET", "HEAD"]),
            Route("/{rest:path}", self._nothing, methods=["GET", "HEAD"]),
        ]
        self.app = Starlette(routes=routes)

    def client(self) -> httpx.AsyncClient:
        return new_client(transport=_Transport(self))

    # --- What it holds -----------------------------------------------------------------

    def add_blob(self, image: str, data: bytes) -> str:
        self.blobs[(image, digest_of(data))] = data
        return digest_of(data)

    def add_manifest(self, image: str, tag: str | None, manifest: bytes, media_type: str) -> str:
        digest = digest_of(manifest)
        self.manifests[(image, digest)] = (manifest, media_type)
        if tag is not None:
            self.manifests[(image, tag)] = (manifest, media_type)
        return digest

    def add_image(self, image: str, tag: str, *layers: bytes) -> bytes:
        """An image with these layers under a tag. Returns its manifest."""
        config = json.dumps({"architecture": "amd64", "os": "linux", "of": image}).encode()
        described = [
            {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": d, "size": s}
            for d, s in ((self.add_blob(image, layer), len(layer)) for layer in layers)
        ]
        document = {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": self.add_blob(image, config),
                "size": len(config),
            },
            "layers": described,
        }
        manifest = json.dumps(document).encode()
        self.add_manifest(image, tag, manifest, OCI_MANIFEST)
        return manifest

    # --- What was asked ----------------------------------------------------------------

    def asked(self, method: str | None = None, host: str | None = None) -> list[str]:
        """The paths asked for, in order, of one method or one host if given."""
        return [
            seen["path"]
            for seen in self.requests
            if method in (None, seen["method"]) and host in (None, seen["host"])
        ]

    def _note(self, request: Request) -> dict:
        seen = {
            "method": request.method,
            "host": request.url.hostname,
            "path": request.url.path,
            "query": dict(request.query_params),
            "headers": dict(request.headers),
        }
        self.requests.append(seen)
        return seen

    async def _nothing(self, request: Request) -> Response:
        self._note(request)
        return Response(status_code=404)

    # --- Signing in --------------------------------------------------------------------

    async def _token(self, request: Request) -> Response:
        self._note(request)
        if self.token_answer is not None:
            return Response(
                self.token_answer, media_type="application/json", headers=self.token_headers
            )
        account = None
        presented = request.headers.get("authorization")
        if presented is not None:
            known = {basic(name, password): name for name, password in self.accounts.items()}
            account = known.get(presented)
            if account is None:
                return JSONResponse({"details": "incorrect username or password"}, 401)
        token = f"token-{len(self.issued) + 1}"
        self.issued[token] = (account, request.query_params.get("scope", ""))
        answer: dict = {"token": token, "access_token": token}
        if self.token_seconds is not None:
            answer["expires_in"] = self.token_seconds
        return JSONResponse(answer)

    def _refusal(self, request: Request, image: str) -> Response | None:
        """A `401` that says where to sign in, unless the request carries a token for the image."""
        scope = f"repository:{image}:pull"
        presented = request.headers.get("authorization", "")
        account, granted = self.issued.get(presented.removeprefix("Bearer "), (None, None))
        if granted == scope and (image not in self.private or account is not None):
            return None
        challenge = f'Bearer realm="{self.realm}",service="{self.service}",scope="{scope}"'
        if self.challenge is not None:
            challenge = self.challenge
        body = {"errors": [{"code": "UNAUTHORIZED", "message": "authentication required"}]}
        return JSONResponse(body, 401, headers={"WWW-Authenticate": challenge} if challenge else {})

    # --- Serving -----------------------------------------------------------------------

    async def _serve(self, request: Request) -> Response:
        self._note(request)
        if self.status is not None:
            return Response(status_code=self.status)
        if (only := self.status_of.get(f"{request.method} {request.url.path}")) is not None:
            return Response(status_code=only)
        rest = request.path_params["rest"]
        if rest.endswith("/tags/list"):
            image, kind, reference = rest.removesuffix("/tags/list"), "tags", ""
        else:
            for kind in ("manifests", "blobs"):
                image, found, reference = rest.rpartition(f"/{kind}/")
                if found:
                    break
            else:
                return Response(status_code=200 if rest == "" else 404)
        if self.wants_token and (refused := self._refusal(request, image)) is not None:
            return refused
        if kind == "tags":
            return self._tags(request, image)
        if kind == "blobs":
            return self._blob(request, image, reference)
        held = self.manifests.get((image, reference))
        if held is None:
            return JSONResponse({"errors": [{"code": "MANIFEST_UNKNOWN"}]}, 404)
        manifest, media_type = held
        headers = {"Content-Type": media_type, "Content-Length": str(len(manifest))}
        if self.digest_header:
            headers["Docker-Content-Digest"] = digest_of(manifest)
        return Response(b"" if request.method == "HEAD" else manifest, headers=headers)

    def _blob(self, request: Request, image: str, digest: str) -> Response:
        data = self.blobs.get((image, digest))
        if data is None:
            return JSONResponse({"errors": [{"code": "BLOB_UNKNOWN"}]}, 404)
        if self.blobs_at and request.url.hostname != urlsplit(self.blobs_at).hostname:
            return RedirectResponse(f"{self.blobs_at}/cdn/{digest}", status_code=307)
        headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(data))}
        return Response(b"" if request.method == "HEAD" else data, headers=headers)

    async def _cdn(self, request: Request) -> Response:
        self._note(request)
        digest = request.path_params["digest"]
        for (_, held), data in self.blobs.items():
            if held == digest:
                headers = {"Content-Length": str(len(data))}
                return Response(b"" if request.method == "HEAD" else data, headers=headers)
        return Response(status_code=404)

    def _tags(self, request: Request, image: str) -> Response:
        tags = sorted(tag for (name, tag) in self.manifests if name == image and ":" not in tag)
        if not tags:
            return JSONResponse({"errors": [{"code": "NAME_UNKNOWN"}]}, 404)
        after = [tag for tag in tags if tag > request.query_params.get("last", "")]
        asked = request.query_params.get("n", "")
        count = min(int(asked) if asked.isdigit() else len(after), self.page_size or len(after))
        page, headers = after[:count], {}
        if len(after) > count:
            more = f"/v2/{image}/tags/list?n={count}&last={page[-1]}"
            headers["Link"] = f'<{more}>; rel="next"'
        return JSONResponse({"name": image, "tags": page}, headers=headers)


class _ByHost(httpx.AsyncBaseTransport):
    def __init__(self, registries: dict[str, FakeRegistry]) -> None:
        self._registries = registries
        self._otherwise = next(iter(registries.values()))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        registry = self._registries.get(request.url.host, self._otherwise)
        return await _Transport(registry).handle_async_request(request)


def client_for(registries: dict[str, FakeRegistry]) -> httpx.AsyncClient:
    """One client for several registries, each at its own host name.

    Any other host, such as the sign-in address, reaches the first of them.
    """
    return new_client(transport=_ByHost(registries))

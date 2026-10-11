# Docker Proxy Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docker pull repo.example.com/<proxy>/<image>` fetches an image from Docker Hub or another registry the first time and serves it from the cache afterwards, with the remote's own token sign-in done for the client.

**Architecture:** The remote client learns to answer a registry's `401`: it fetches a token from the address the remote names, under rules about where that address may be and what it may be shown, remembers the token in memory until it runs out, and sends the request again. The proxy engine gains a way to fetch a small document into memory, or only ask about one, with all of its bookkeeping and no caching, so that a format can read what a remote sent before it keeps it. The Docker format uses that for manifests, tags and tag lists, which it validates and stores in the hosted layout with what they refer to, and uses the engine's ordinary cached download for blobs, checked against their digest.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, httpx, pytest + pytest-asyncio, Docker (the daemon and client of the machine, Docker Hub and registry.k8s.io, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-11-docker-format-design.md](../specs/2026-10-11-docker-format-design.md), sections 4.2, 8 and the plan 7b part of 12; D10, D11 and D13. Business requirements: [docs/BRD.md](../../BRD.md) FMT-4 (proxy), NFR-1. Task 4 amends the spec where this plan settles something the spec left open.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | Signing in belongs to the remote client and is used only for a format that says its remotes hand out tokens (`Format.remote_signs_in`). It answers a `401` whose `WWW-Authenticate` is `Bearer` with a `realm` that is an HTTP address. | Elsewhere a `Bearer` realm is a label, and a `401` from a Maven or PyPI remote must stay a failure. |
| P2 | The sign-in address is held to `remote.refusal` against the remote as configured, and must use HTTPS if the remote does. It is shown the repository's credential only if that is a user name and password. A stored bearer token is sent to the remote alone. The host a blob is redirected to is shown nothing. | The spec applies the PyPI design's D8 to the realm and also says the credential goes there; this is how both hold. The remote already receives the credential, so naming where its users sign in gives it nothing new; an internal or plain-HTTP address would. |
| P3 | Tokens are kept in memory, for each outbound client, under the challenge and a mark of the credential they were obtained with. They last as long as their issuer says (60 seconds if it says nothing, an hour at most), less ten seconds. What the remote asked for the last time is remembered under the remote and a subject the caller names (the image), so the next request sends its token at once. | A token is a secret that lasts minutes: nothing to store, and nothing to share between repositories with different credentials. One sign-in serves a whole pull. |
| P4 | `remote.Failed` gains `status`. The Docker format answers `404` for an image the remote refuses with `401` or `403`. | A registry says the same of an image it does not have as of one it will not show. Calling that an outage (`502`) would send an administrator looking for one. |
| P5 | The engine gains `ask` (fetch into memory, with a size limit), `probe` (`HEAD`), `refuse` (record that what was sent cannot be used) and `still_current`. None of them caches. `Source` gains `accept`, `subject` and `remember_missing`. | A manifest must be read before it is kept. The bookkeeping (blocked remotes, remembered misses, recorded failures, commits) stays in one place. |
| P6 | A manifest is kept only if it is one of the four kinds and, when asked for by digest, has that digest. It is stored with what it refers to, before any of that has been fetched. | D13. What is in the cache under a digest must be that content; what refers to what must be known for maintenance. |
| P7 | A tag that is older than `metadata_max_age_minutes` is asked about with `HEAD`. If the digest reported is the one held, nothing is fetched; otherwise the manifest is fetched by that digest. A remote that reports no digest is asked for the manifest by its tag. A remote that cannot be asked, or has dropped the tag, leaves what is held in place. | Spec section 8. Docker Hub does not count a `HEAD` as a pull. |
| P8 | A blob is fetched by the engine's cached download, with its digest as the hash it must have, and is not remembered as missing. `HEAD` for a blob that is not held asks the remote and fetches nothing. | A remembered miss is kept under the path, and a blob's path has no image in it: asking for a layer under the wrong image would hide it from the right one. A `HEAD` must not download gigabytes. |
| P9 | An image with a one-part name is asked for under `library/` only when the remote's host is `registry-1.docker.io`. | Docker's own rule, for the one registry that has it. |
| P10 | A tag list is read from the remote page by page (`Link: rel="next"`), up to 100 pages and 100,000 tags, keeping only what can be a tag, and is stored as one JSON file at `lists/<image>`. | Registries page their lists. What a remote writes is not repeated unless it is a tag. |
| P11 | Maintenance treats a proxy as a hosted repository: a blob no kept manifest refers to is removed after a day. | It is fetched again when asked for. A manifest by digest is never removed, so an image that was pulled keeps its layers. |
| P12 | The format offers `hosted` and `proxy`. `group` comes with plan 7c. | The generic group engine does not know which member answers for an image. |
| P13 | The real-client test pulls `hello-world` through a proxy of Docker Hub and runs it, and `pause` through a proxy of registry.k8s.io. | Docker Hub exercises the sign-in at another host and `library/`; registry.k8s.io redirects every request to another host. Both images are a few kilobytes. |

**Changed after the whole-branch review.** The task bodies below show the code as first written. The branch differs from them as follows.

| # | Decision | Reason |
| --- | --- | --- |
| P14 | When a tag that is held is said to name another manifest and that manifest cannot be had (the remote fails, refuses, has lost it, or sends something that is not a manifest), what is held is served. A manifest fetched for a tag is not remembered as missing. | The review showed the held tag answered `502` or `404`, for a day in one case. This is the case of a registry that counts pulls: asking about a tag still works after fetching has stopped. |
| P15 | A sign-in address that refuses the credential is a failure without a status, so it is answered `502` with its reason, not `404`. | P4 is about one image a remote will not show. A credential that is no longer good is a fault of the whole proxy, and every image was reported as unknown. |
| P16 | The token request asks for an answer that is not compressed, and an encoded answer is refused. | The answer is read as it arrives. The request invited compression it could not read. |
| P17 | A token is kept for the remote it was fetched for, besides the challenge and the credential. | Two remotes that named the same sign-in address shared a token, so the second never had the rules about that address applied to it. |
| P18 | A manifest type that is not taken is not named in the error. | On a proxy it is text the remote wrote, of any length, and it reached the client, the log and the repository's status. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves or a remote is asked; only the security package reads `Principal.patterns`; formats do not commit, the route does, and the proxy engine commits what it must; errors under `/v2/` have the registry's shape; only `docker/format.py` touches the repository context; remote secrets are never returned or logged; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration, no setting and no dependency.**
- **A token from a remote is never stored and never logged.** Neither is the credential it was obtained with.
- **The repository's credential goes to the remote's own origin and to the sign-in address the remote names, and nowhere else.** That address is never internal unless the remote is at that host, and never plain HTTP if the remote is HTTPS.
- **Nothing a remote sent is kept before it has been checked:** a manifest is one, and is the one asked for; a blob has its digest; a tag in a list can be a tag.
- **Everything that changes a repository answers `405` on a proxy.**
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **Where a remote can send the proxy, and its credential.** A sign-in address on another host, on an internal address, or over plain HTTP; a blob redirected to another host; a tag list whose next page is elsewhere; a file address on another origin. The credential reaches the remote and a permitted sign-in address only (Tasks 1, 2, 3).
2. **What a remote sends.** Something that is not a manifest, a manifest of schema 1, one with another digest than was asked for, a blob that is not its digest, a tag list that is not a list or holds things that are not tags, a token answer that is not JSON or is very long. None of it is kept or repeated (Tasks 1, 3).
3. **A remote that fails or refuses.** Down, with and without something held; an image it will not show; a tag it has dropped; a blocked remote; a sign-in address that refuses the credential (Tasks 2, 3).
4. **Tokens over time.** One that has run out, one the remote no longer takes, two images, two credentials, two clients; one sign-in for a whole pull (Tasks 1, 3).
5. **Names and addresses.** `library/` on Docker Hub and nowhere else; a remote address with a path; a layer asked for under the wrong image; a push to a proxy (Task 3).

---

### Task 1: Core: a remote that wants a token

**Files:**
- Modify: `backend/src/megooarti/repositories/remote.py`
- Create: `backend/tests/repositories/fake_registry.py`
- Test: `backend/tests/repositories/test_remote_sign_in.py`

**Interfaces:**
- Consumes: `remote.refusal`, `remote.new_client`, `remote._unexpected`, `remote._unrequestable`.
- Produces:
  - `remote.SignIn(remote_url: str, subject: str = "")`.
  - `remote.Document(body: bytes, headers: Mapping[str, str])`.
  - `remote.Failed` gains `status: int | None = None`; `remote.Exists` gains `every: Mapping[str, str]`, all the answer's headers.
  - `await remote.fetch(client, url, *, authorization, limit, accept=None, sign_in=None) -> Document | Missing | Failed`.
  - `remote.download` and `remote.head` gain `accept: str | None = None` and `sign_in: SignIn | None = None`.
  - `remote._now()`, which tests replace to move time.
  - `tests/repositories/fake_registry.py`: `FakeRegistry` (`add_image`, `add_manifest`, `add_blob`, `client`, `asked`, `requests`, and the switches `wants_token`, `realm`, `accounts`, `private`, `token_seconds`, `token_answer`, `challenge`, `issued`, `digest_header`, `blobs_at`, `page_size`, `down`, `status`), `REGISTRY`, `digest_of`, `basic`.

- [ ] **Step 1: Write the fake registry and the failing tests**

`backend/tests/repositories/fake_registry.py`:

```python
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
            return Response(self.token_answer, media_type="application/json")
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
```

`backend/tests/repositories/test_remote_sign_in.py`:

```python
"""A remote that wants a token before it serves anything, as container registries do."""

from collections.abc import AsyncIterator

import pytest

from megooarti.repositories import remote
from megooarti.repositories.remote import Document, Exists, Failed, Fetched, Missing, SignIn
from megooarti.storage.backends import FileBlobBackend
from tests.repositories.fake_registry import REGISTRY, FakeRegistry, basic, digest_of

MANIFEST = f"{REGISTRY}/v2/team/app/manifests/1.0"
SIGN_IN = SignIn(REGISTRY, "team/app")
LAYER = b"a layer" * 1000


@pytest.fixture
def registry() -> FakeRegistry:
    registry = FakeRegistry()
    registry.add_image("team/app", "1.0", LAYER)
    registry.add_image("team/other", "1.0", b"another layer")
    return registry


@pytest.fixture
async def client(registry) -> AsyncIterator:
    async with registry.client() as client:
        yield client


async def get(client, url: str = MANIFEST, sign_in: SignIn | None = SIGN_IN, **options):
    options.setdefault("authorization", None)
    return await remote.fetch(client, url, limit=1024 * 1024, sign_in=sign_in, **options)


def tokens_asked(registry: FakeRegistry) -> list[dict]:
    return [seen for seen in registry.requests if seen["path"] == "/token"]


async def test_a_remote_that_wants_a_token_is_given_one(registry, client):
    answer = await get(client)

    assert isinstance(answer, Document)
    assert digest_of(answer.body) == answer.headers["Docker-Content-Digest"]
    (asked,) = tokens_asked(registry)
    assert asked["host"] == "auth.registry.test"
    assert asked["query"] == {"service": "registry.test", "scope": "repository:team/app:pull"}
    assert "authorization" not in asked["headers"]  # there is no credential to present
    sent = [seen["headers"].get("authorization") for seen in registry.requests]
    assert sent == [None, None, "Bearer token-1"]  # refused, signed in, served


async def test_a_token_is_used_until_it_runs_out(registry, client, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(remote, "_now", lambda: clock[0])
    await get(client)
    registry.requests.clear()

    await get(client)
    at_once = [seen["headers"].get("authorization") for seen in registry.requests]
    clock[0] += 300 - 10  # its five minutes, less the margin
    registry.requests.clear()
    await get(client)

    assert at_once == ["Bearer token-1"]  # no refusal first, and no sign-in
    assert len(tokens_asked(registry)) == 1
    assert registry.requests[-1]["headers"]["authorization"] == "Bearer token-2"


@pytest.mark.parametrize(("seconds", "kept"), [(None, True), (5, False), (10**9, True)])
async def test_how_long_a_token_is_kept(registry, client, monkeypatch, seconds, kept):
    clock = [1000.0]
    monkeypatch.setattr(remote, "_now", lambda: clock[0])
    registry.token_seconds = seconds
    await get(client)

    clock[0] += 45  # under the minute a token is good for if nothing says otherwise
    await get(client)
    clock[0] += 3600  # nobody's word keeps one longer than an hour
    await get(client)

    assert len(tokens_asked(registry)) == (2 if kept else 3)


async def test_a_token_is_for_one_thing_and_one_credential(registry, client):
    registry.accounts["ci"] = "secret"
    await get(client)

    other = await get(
        client, f"{REGISTRY}/v2/team/other/manifests/1.0", SignIn(REGISTRY, "team/other")
    )
    as_ci = await get(client, authorization=basic("ci", "secret"))

    assert isinstance(other, Document) and isinstance(as_ci, Document)
    scopes = [asked["query"]["scope"] for asked in tokens_asked(registry)]
    assert scopes == ["repository:team/app:pull", "repository:team/other:pull", scopes[0]]
    assert [account for account, _ in registry.issued.values()] == [None, None, "ci"]


async def test_a_token_the_remote_no_longer_takes_is_replaced(registry, client):
    await get(client)
    registry.issued.clear()  # revoked, or the registry restarted

    answer = await get(client)

    assert isinstance(answer, Document)
    assert len(tokens_asked(registry)) == 2


async def test_the_credential_goes_to_the_sign_in_address_and_the_token_to_the_remote(
    registry, client
):
    registry.accounts["ci"] = "secret"
    registry.private.add("team/app")
    registry.blobs_at = "https://cdn.registry.test"
    credential = basic("ci", "secret")
    blob = f"{REGISTRY}/v2/team/app/blobs/{digest_of(LAYER)}"

    async def stage(chunks, size):
        return b"".join([chunk async for chunk in chunks])

    fetched = await remote.download(
        client, blob, authorization=credential, stage=stage, sign_in=SIGN_IN
    )

    assert isinstance(fetched, Fetched) and fetched.staged == LAYER
    by_host = {seen["host"]: seen["headers"].get("authorization") for seen in registry.requests}
    assert by_host == {
        "registry.test": "Bearer token-1",  # after the first attempt, which sent the credential
        "auth.registry.test": credential,
        "cdn.registry.test": None,  # where the blob is kept learns nothing
    }
    assert registry.requests[0]["headers"]["authorization"] == credential


async def test_a_wrong_credential_is_a_failure_that_does_not_block(registry, client):
    registry.accounts["ci"] = "secret"

    answer = await get(client, authorization=basic("ci", "wrong"))

    assert answer == Failed("its sign-in address refused the credential", False, 401)


async def test_an_image_the_token_does_not_open_is_refused_by_the_remote(registry, client):
    registry.private.add("team/app")

    answer = await get(client)

    assert answer == Failed("the remote answered 401", blockable=False, status=401)
    assert len(tokens_asked(registry)) == 1  # asked once, not in a loop


async def test_a_token_that_is_not_a_basic_credential_is_not_shown_to_the_sign_in_address(
    registry, client
):
    await get(client, authorization="Bearer a-static-token")

    assert "authorization" not in tokens_asked(registry)[0]["headers"]


@pytest.mark.parametrize(
    ("realm", "reason"),
    [
        ("http://auth.registry.test/token", "it asks for sign-in over plain HTTP"),
        ("https://127.0.0.1/token", "it points at an internal address"),
        ("https://169.254.169.254/latest/meta-data", "it points at an internal address"),
        ("https://localhost:8443/token", "it points at an internal address"),
    ],
)
async def test_where_a_remote_may_send_us_to_sign_in(registry, client, realm, reason):
    registry.accounts["ci"] = "secret"
    registry.realm = realm

    answer = await get(client, authorization=basic("ci", "secret"))

    assert isinstance(answer, Failed) and answer.reason.endswith(reason)
    assert answer.blockable is False
    assert tokens_asked(registry) == []  # nothing was sent there, the credential least of all


async def test_a_remote_on_an_internal_address_may_name_its_own(registry, client):
    registry.realm = "http://10.0.0.5:5001/token"
    here = "http://10.0.0.5:5000"

    answer = await get(client, f"{here}/v2/team/app/manifests/1.0", SignIn(here, "team/app"))

    assert isinstance(answer, Document)


@pytest.mark.parametrize("challenge", ['Bearer realm="registry"', 'Basic realm="registry"', ""])
async def test_a_refusal_that_names_no_address_is_only_a_refusal(registry, client, challenge):
    registry.challenge = challenge

    answer = await get(client)

    assert answer == Failed("the remote answered 401", blockable=False, status=401)
    assert tokens_asked(registry) == []


@pytest.mark.parametrize(
    "answer",
    [b"not json", b"[]", b"{}", b'{"token": 7}', b'{"token": "line\\nbreak"}', b" " * 70_000],
    ids=["text", "a list", "empty", "a number", "a line break", "too long"],
)
async def test_a_sign_in_answer_that_cannot_be_used(registry, client, answer):
    registry.token_answer = answer

    result = await get(client)

    assert result == Failed("its sign-in address gave no usable token", blockable=False)


async def test_a_sign_in_address_that_answers_something_else_is_a_failure(registry, client):
    registry.realm = "https://auth.registry.test/missing"

    answer = await get(client)

    assert answer == Failed("its sign-in address answered 404", blockable=False, status=404)


async def test_without_being_told_to_sign_in_a_refusal_stays_one(registry, client):
    answer = await get(client, sign_in=None)
    asked = await remote.head(client, MANIFEST, authorization=None)

    assert answer == asked == Failed("the remote answered 401", blockable=False, status=401)
    assert tokens_asked(registry) == []


async def test_asking_about_a_file_signs_in_too_and_gives_every_header(registry, client):
    answer = await remote.head(client, MANIFEST, authorization=None, sign_in=SIGN_IN)
    missing = await remote.head(
        client, f"{REGISTRY}/v2/team/app/manifests/2.0", authorization=None, sign_in=SIGN_IN
    )

    assert isinstance(answer, Exists)
    assert answer.every["docker-content-digest"].startswith("sha256:")
    assert "Docker-Content-Digest" not in answer.headers  # not what a client is passed
    assert missing == Missing()
    assert registry.asked("HEAD") == ["/v2/team/app/manifests/1.0"] * 2 + [
        "/v2/team/app/manifests/2.0"
    ]


async def test_what_is_accepted_is_said(registry, client):
    await get(client, accept="application/vnd.oci.image.index.v1+json, */*")

    assert registry.requests[-1]["headers"]["accept"] == (
        "application/vnd.oci.image.index.v1+json, */*"
    )
    assert registry.requests[-1]["headers"]["accept-encoding"] == "identity"


async def test_a_document_has_a_limit(registry, client):
    registry.wants_token = False

    whole = await remote.fetch(client, MANIFEST, authorization=None, limit=100_000)
    cut = await remote.fetch(client, MANIFEST, authorization=None, limit=100)
    missing = await remote.fetch(client, MANIFEST + "0", authorization=None, limit=100)

    assert isinstance(whole, Document)
    assert cut == Failed("the remote sent more than a document may hold", blockable=False)
    assert missing == Missing()


async def test_a_remote_that_is_down_is_a_failure_that_blocks(registry, client):
    registry.down = True

    answer = await get(client)

    assert answer == Failed("ConnectError", blockable=True)


async def test_what_one_client_learned_another_does_not_know(registry, client):
    await get(client)
    registry.requests.clear()

    async with registry.client() as other:
        await get(other)

    assert len(tokens_asked(registry)) == 1


async def test_a_whole_file_is_staged_through_a_sign_in(registry, client, tmp_path):
    backend = FileBlobBackend(tmp_path)

    async def stage(chunks, size):
        return await backend.stage(chunks)

    blob = f"{REGISTRY}/v2/team/app/blobs/{digest_of(LAYER)}"
    fetched = await remote.download(client, blob, authorization=None, stage=stage, sign_in=SIGN_IN)

    assert isinstance(fetched, Fetched)
    assert "sha256:" + fetched.staged.sha256 == digest_of(LAYER)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_remote_sign_in.py -q`
Expected: collection error, `cannot import name 'Document' from 'megooarti.repositories.remote'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/remote.py`:

Replace

```python
import base64
import ipaddress
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
```

with

```python
import base64
import hashlib
import ipaddress
import json
import re
import socket
import time
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from typing import Any
```

Replace

```python
@dataclass(frozen=True)
class Failed:
    reason: str
    blockable: bool  # counts towards blocking the remote


@dataclass(frozen=True)
class Exists:
    headers: dict[str, str]
```

with

```python
@dataclass(frozen=True)
class Failed:
    reason: str
    blockable: bool  # counts towards blocking the remote
    status: int | None = None  # what the remote answered, if it did answer


@dataclass(frozen=True)
class Exists:
    headers: dict[str, str]  # what a HEAD answer passes on to the client
    # Every header of the answer, for a caller that knows which one it needs.
    every: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Document:
    """A small answer, read into memory."""

    body: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True)
class SignIn:
    """How to answer a remote that wants a token before it serves anything.

    A container registry answers a request with `401` and the address of a token
    service. That address is one the remote names, so it is held to the rules of
    `refusal`, and `remote_url` is the remote as configured, to hold it against.
    `subject` is what a token would be for, as the caller knows it (an image), so that
    the next request for the same thing can send its token at once.
    """

    remote_url: str
    subject: str = ""
```

Replace

```python
def _request_headers(
    authorization: str | None, etag: str | None = None, last_modified: str | None = None
) -> dict[str, str]:
    # identity: store the bytes the remote holds, not a transfer encoding of them.
    headers = {"Accept-Encoding": "identity"}
    if authorization:
        headers["Authorization"] = authorization
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers
```

with

```python
def _request_headers(
    accept: str | None = None, etag: str | None = None, last_modified: str | None = None
) -> dict[str, str]:
    # identity: store the bytes the remote holds, not a transfer encoding of them.
    headers = {"Accept-Encoding": "identity"}
    if accept:
        headers["Accept"] = accept
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers
```

Replace

```python
def _unexpected(status: int) -> Failed:
    return Failed(f"the remote answered {status}", blockable=status in _REMOTE_IN_TROUBLE)
```

with

```python
def _unexpected(status: int) -> Failed:
    return Failed(
        f"the remote answered {status}", blockable=status in _REMOTE_IN_TROUBLE, status=status
    )
```

Before

```python
def _declared_size(response: httpx.Response) -> int | None:
```

add

```python
# --- Signing in to a remote that issues tokens ----------------------------------------

# A token is used for as long as its issuer says, within these bounds, less a margin.
_TOKEN_DEFAULT_SECONDS = 60
_TOKEN_MOST_SECONDS = 3600
_TOKEN_MARGIN_SECONDS = 10
_TOKEN_ANSWER_LIMIT = 64 * 1024
_REMEMBERED_MOST = 1000
_PARAMETER = re.compile(r'([A-Za-z_]+)="([^"]*)"')


@dataclass(frozen=True)
class _Challenge:
    realm: str
    service: str
    scope: str


class _SignInFailed(Exception):
    def __init__(self, failed: Failed) -> None:
        super().__init__(failed.reason)
        self.failed = failed


class _Memory:
    """What one client has learned about signing in.

    Kept in memory and never stored: a token is a secret, and lasts minutes. What a
    token is kept under includes a mark of the credential it was obtained with, so a
    repository whose credential changes, or two with different ones, never share one.
    """

    def __init__(self) -> None:
        self.challenges: dict[tuple[str, str, str], _Challenge] = {}
        self.tokens: dict[tuple[_Challenge, str], tuple[str, float]] = {}

    def token(self, challenge: _Challenge, mark: str) -> str | None:
        held = self.tokens.get((challenge, mark))
        if held is None or held[1] <= _now():
            self.tokens.pop((challenge, mark), None)
            return None
        return held[0]

    def keep(self, challenge: _Challenge, mark: str, token: str, seconds: float) -> None:
        if len(self.tokens) >= _REMEMBERED_MOST:
            self.tokens.clear()
        if seconds > 0:
            self.tokens[(challenge, mark)] = (token, _now() + seconds)

    def expect(self, key: tuple[str, str, str], challenge: _Challenge) -> None:
        if len(self.challenges) >= _REMEMBERED_MOST:
            self.challenges.clear()
        self.challenges[key] = challenge


_memories: "weakref.WeakKeyDictionary[httpx.AsyncClient, _Memory]" = weakref.WeakKeyDictionary()


def _now() -> float:
    return time.monotonic()


def _mark(authorization: str | None) -> str:
    return hashlib.sha256((authorization or "").encode()).hexdigest()


def _challenge_of(response: httpx.Response) -> _Challenge | None:
    """The token service a `401` names, if it names one."""
    scheme, _, rest = response.headers.get("WWW-Authenticate", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    given = {name.lower(): value for name, value in _PARAMETER.findall(rest)}
    realm = given.get("realm", "")
    if not realm.lower().startswith(("http://", "https://")):
        return None  # elsewhere a realm is a label, not an address
    return _Challenge(realm, given.get("service", ""), given.get("scope", ""))


async def _token(
    client: httpx.AsyncClient, sign_in: SignIn, challenge: _Challenge, authorization: str | None
) -> tuple[str, float]:
    """Fetch a token from the service a remote named. Raises _SignInFailed."""
    refused = refusal(sign_in.remote_url, challenge.realm)
    if refused is not None:
        reason = f"it names an address to sign in at, and {refused}"
        raise _SignInFailed(Failed(reason, blockable=False))
    if sign_in.remote_url.lower().startswith("https:") and not challenge.realm.lower().startswith(
        "https:"
    ):
        # The credential would cross the network in the clear, for a remote that was
        # configured not to.
        raise _SignInFailed(Failed("it asks for sign-in over plain HTTP", blockable=False))
    wanted = {"service": challenge.service, "scope": challenge.scope}
    headers = {"Accept": "application/json"}
    if authorization and authorization.startswith("Basic "):
        # The remote named this address as the place its users sign in.
        headers["Authorization"] = authorization
    request = client.build_request(
        "GET",
        challenge.realm,
        params={name: value for name, value in wanted.items() if value},
        headers=headers,
    )
    response = await client.send(request, stream=True)
    try:
        if response.status_code in (401, 403):
            reason = "its sign-in address refused the credential"
            raise _SignInFailed(Failed(reason, blockable=False, status=response.status_code))
        if response.status_code != 200:
            failed = _unexpected(response.status_code)
            reason = f"its sign-in address answered {response.status_code}"
            raise _SignInFailed(Failed(reason, failed.blockable, failed.status))
        body = await _read(response, _TOKEN_ANSWER_LIMIT)
    finally:
        await response.aclose()
    unusable = _SignInFailed(Failed("its sign-in address gave no usable token", blockable=False))
    try:
        answer = json.loads(body) if body is not None else None
    except ValueError:
        raise unusable from None
    if not isinstance(answer, dict):
        raise unusable
    token = answer.get("token") or answer.get("access_token")
    if not isinstance(token, str) or not token.isascii() or not token.isprintable():
        raise unusable
    stated = answer.get("expires_in")
    seconds = stated if isinstance(stated, int | float) and stated > 0 else _TOKEN_DEFAULT_SECONDS
    return token, min(seconds, _TOKEN_MOST_SECONDS) - _TOKEN_MARGIN_SECONDS


async def _read(response: httpx.Response, limit: int) -> bytes | None:
    """The body, or None if it is longer than `limit`."""
    received = bytearray()
    async for chunk in response.aiter_raw():
        received += chunk
        if len(received) > limit:
            return None
    return bytes(received)


async def _open(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    authorization: str | None,
    headers: dict[str, str],
    sign_in: SignIn | None,
) -> httpx.Response:
    """Send a request and return the answer with its body unread. The caller closes it.

    With `sign_in`, a `401` that names a token service is answered: a token is fetched,
    or one that is remembered is used, and the request is sent once more with it.
    Raises _SignInFailed if no token could be had.
    """

    async def send(credential: str | None) -> httpx.Response:
        sent = {**headers, "Authorization": credential} if credential else headers
        return await client.send(client.build_request(method, url, headers=sent), stream=True)

    if sign_in is None:
        return await send(authorization)
    memory = _memories.setdefault(client, _Memory())
    mark = _mark(authorization)
    key = (sign_in.remote_url, sign_in.subject, mark)
    expected = memory.challenges.get(key)
    token = memory.token(expected, mark) if expected is not None else None
    response = await send(f"Bearer {token}" if token else authorization)
    if response.status_code != 401:
        return response
    challenge = _challenge_of(response)
    if challenge is None:
        return response
    await response.aclose()
    if expected is not None and token is not None:
        memory.tokens.pop((expected, mark), None)  # refused: revoked, or expired early
    memory.expect(key, challenge)
    token = memory.token(challenge, mark)
    if token is None:
        token, seconds = await _token(client, sign_in, challenge, authorization)
        memory.keep(challenge, mark, token, seconds)
    response = await send(f"Bearer {token}")
    if response.status_code == 401:
        memory.tokens.pop((challenge, mark), None)
    return response
```

Replace

```python
    stage: Stage,
    etag: str | None = None,
    last_modified: str | None = None,
) -> Fetched | NotModified | Missing | Failed:
    """Fetch a file completely, or learn that it is unchanged, absent or unavailable."""
    headers = _request_headers(authorization, etag, last_modified)
    try:
        async with client.stream("GET", url, headers=headers) as response:
            status = response.status_code
```

with

```python
    stage: Stage,
    etag: str | None = None,
    last_modified: str | None = None,
    accept: str | None = None,
    sign_in: SignIn | None = None,
) -> Fetched | NotModified | Missing | Failed:
    """Fetch a file completely, or learn that it is unchanged, absent or unavailable."""
    headers = _request_headers(accept, etag, last_modified)
    try:
        response = await _open(
            client, "GET", url, authorization=authorization, headers=headers, sign_in=sign_in
        )
        try:
            status = response.status_code
```

Replace

```python
            return Fetched(
                staged=staged,
                content_type=response.headers.get("Content-Type"),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except (InwardRedirect, httpx.InvalidURL, ValueError, UnicodeError) as error:
        return _unrequestable(error)
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)


async def head(
    client: httpx.AsyncClient, url: str, *, authorization: str | None
) -> Exists | Missing | Failed:
    """Ask whether the remote has a file, without fetching it."""
    try:
        response = await client.head(url, headers=_request_headers(authorization))
    except (InwardRedirect, httpx.InvalidURL, ValueError, UnicodeError) as error:
        return _unrequestable(error)
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)
    if response.status_code in (404, 410):
        return Missing()
    if response.status_code != 200:
        return _unexpected(response.status_code)
    passed_on = {name: response.headers[name] for name in _HEAD_HEADERS if name in response.headers}
    return Exists(headers=passed_on)
```

with

```python
            return Fetched(
                staged=staged,
                content_type=response.headers.get("Content-Type"),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
        finally:
            await response.aclose()
    except _SignInFailed as error:
        return error.failed
    except (InwardRedirect, httpx.InvalidURL, ValueError, UnicodeError) as error:
        return _unrequestable(error)
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    authorization: str | None,
    limit: int,
    accept: str | None = None,
    sign_in: SignIn | None = None,
) -> Document | Missing | Failed:
    """Fetch a small document into memory. One longer than `limit` is a failure."""
    try:
        response = await _open(
            client,
            "GET",
            url,
            authorization=authorization,
            headers=_request_headers(accept),
            sign_in=sign_in,
        )
        try:
            if response.status_code in (404, 410):
                return Missing()
            if response.status_code != 200:
                return _unexpected(response.status_code)
            encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
            if encoding != "identity":
                return Failed("the remote sent an encoded body", blockable=False)
            body = await _read(response, limit)
            if body is None:
                return Failed("the remote sent more than a document may hold", blockable=False)
            return Document(body=body, headers=response.headers)
        finally:
            await response.aclose()
    except _SignInFailed as error:
        return error.failed
    except (InwardRedirect, httpx.InvalidURL, ValueError, UnicodeError) as error:
        return _unrequestable(error)
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)


async def head(
    client: httpx.AsyncClient,
    url: str,
    *,
    authorization: str | None,
    accept: str | None = None,
    sign_in: SignIn | None = None,
) -> Exists | Missing | Failed:
    """Ask whether the remote has a file, without fetching it."""
    try:
        response = await _open(
            client,
            "HEAD",
            url,
            authorization=authorization,
            headers=_request_headers(accept),
            sign_in=sign_in,
        )
        await response.aclose()
    except _SignInFailed as error:
        return error.failed
    except (InwardRedirect, httpx.InvalidURL, ValueError, UnicodeError) as error:
        return _unrequestable(error)
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)
    if response.status_code in (404, 410):
        return Missing()
    if response.status_code != 200:
        return _unexpected(response.status_code)
    passed_on = {name: response.headers[name] for name in _HEAD_HEADERS if name in response.headers}
    return Exists(headers=passed_on, every=response.headers)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_remote_sign_in.py tests/repositories/test_remote.py tests/repositories/test_proxy.py -q`
Expected: all pass. The proxy engine's own tests still pass: nothing signs in unless it is told to.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/remote.py backend/tests/repositories/fake_registry.py backend/tests/repositories/test_remote_sign_in.py
git commit -m "feat(repositories): sign in to a remote that hands out tokens"
```

---

### Task 2: Core: asking a remote without caching

**Files:**
- Modify: `backend/src/megooarti/repositories/proxy.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/formats.py`
- Test: `backend/tests/repositories/test_proxy_asking.py`

**Interfaces:**
- Consumes: `remote.fetch`, `remote.head`, `remote.SignIn`, `remote.Failed.status`, `remote.Exists.every` (Task 1); `proxy._target`, `proxy._fail`, `proxy._unavailable`, `proxy_state`; `RepositoryContext._record`; `FakeRegistry` (Task 1).
- Produces:
  - `Format.remote_signs_in: bool = False`.
  - `proxy.Source` gains `accept: str | None = None`, `subject: str = ""` and `remember_missing: bool = True`. `ensure_cached` sends `accept`, signs in if the format says so, and neither looks up nor records a miss when `remember_missing` is false.
  - `proxy.Answer(headers: Mapping[str, str], body: bytes = b"")`, `proxy.Absent()`, `proxy.Unavailable(error: ApiError, status: int | None = None)`.
  - `await proxy.ask(context, path, source, *, limit: int) -> Answer | Absent | Unavailable` and `await proxy.probe(context, path, source) -> Answer | Absent | Unavailable`. Both commit, before asking and after.
  - `await proxy.refuse(context, path, reason: str) -> ApiError`: records the failure and returns the `502` to raise.
  - `await proxy.still_current(context, path) -> None`.
  - `await context.cache(..., references: Collection[str] | None = None)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_proxy_asking.py`:

```python
"""What the proxy engine offers a format that reads what it fetches."""

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from megooarti import secrets_box
from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy, service
from megooarti.repositories.models import NegativeCacheEntry, ProxyState, Repository
from megooarti.repositories.proxy import Absent, Answer, Source, Unavailable
from tests.repositories.fake_registry import REGISTRY, FakeRegistry, basic, digest_of

MANIFEST = f"{REGISTRY}/v2/team/app/manifests/1.0"
LAYER = b"a layer" * 1000
BLOB = f"{REGISTRY}/v2/team/app/blobs/{digest_of(LAYER)}"
ACCEPT = "application/vnd.oci.image.manifest.v1+json"


@pytest.fixture
def registry(app) -> FakeRegistry:
    fake = FakeRegistry()
    fake.add_image("team/app", "1.0", LAYER)
    fake.accounts["ci"] = "secret"
    app.state.http = fake.client()
    return fake


@pytest.fixture
async def upstream(db, settings) -> Repository:
    auth = {"type": "basic", "username": "ci", "secret": secrets_box.seal(settings, "secret")}
    repository = await service.create_repository(
        db,
        name="upstream",
        format="raw",
        type="proxy",
        online=True,
        blob_store=None,
        proxy={"remote_url": REGISTRY, "remote_auth": auth},
    )
    await db.commit()
    return repository


@pytest.fixture
async def context(upstream, context_for, registry, app, monkeypatch):
    context = await context_for(upstream, None, outbound=lambda: app.state.http)
    monkeypatch.setattr(context.format, "remote_signs_in", True)
    return context


def source(url: str = MANIFEST, **options) -> Source:
    return Source(url, accept=ACCEPT, subject="team/app", **options)


async def state(db, repository) -> ProxyState | None:
    return await db.scalar(select(ProxyState).where(ProxyState.repository_id == repository.id))


async def test_a_document_is_fetched_into_memory_with_its_headers(context, registry, db, upstream):
    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=100_000)

    assert not db.in_transaction()  # committed: nothing of the caller's may be pending
    assert isinstance(answer, Answer)
    assert digest_of(answer.body) == answer.headers["Docker-Content-Digest"]
    assert registry.requests[-1]["headers"]["accept"] == ACCEPT
    recorded = await state(db, upstream)
    assert recorded is None or recorded.failures == 0


async def test_asking_signs_in_with_the_repositorys_credential(context, registry):
    await proxy.ask(context, "manifests/app/1.0", source(), limit=100_000)
    registry.requests.clear()
    await proxy.probe(context, "manifests/app/1.0", source())

    assert [account for account, _ in registry.issued.values()] == ["ci"]
    # The next request for the same image sends its token at once.
    assert [seen["headers"]["authorization"] for seen in registry.requests] == ["Bearer token-1"]


async def test_a_format_whose_remotes_issue_no_tokens_does_not_sign_in(
    context, registry, monkeypatch
):
    monkeypatch.setattr(context.format, "remote_signs_in", False)

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=100_000)

    assert isinstance(answer, Unavailable) and answer.status == 401
    assert registry.issued == {}


async def test_asking_about_a_document_fetches_nothing(context, registry):
    answer = await proxy.probe(context, "manifests/app/1.0", source())

    assert isinstance(answer, Answer)
    assert answer.body == b""
    assert answer.headers["docker-content-digest"].startswith("sha256:")
    assert {seen["method"] for seen in registry.requests if seen["path"] != "/token"} == {"HEAD"}


async def test_what_the_remote_does_not_have_is_remembered(context, registry, db):
    missing = f"{REGISTRY}/v2/team/app/manifests/2.0"

    first = await proxy.ask(context, "manifests/app/2.0", source(missing), limit=1000)
    asked = len(registry.requests)
    again = await proxy.probe(context, "manifests/app/2.0", source(missing))

    assert first == again == Absent()
    assert len(registry.requests) == asked  # the second answer came from memory
    assert list(await db.scalars(select(NegativeCacheEntry.path))) == ["manifests/app/2.0"]


async def test_a_miss_is_not_remembered_where_the_path_has_other_addresses(context, registry, db):
    missing = f"{REGISTRY}/v2/team/app/manifests/2.0"
    unremembered = source(missing, remember_missing=False)

    first = await proxy.ask(context, "manifests/app/2.0", unremembered, limit=1000)
    asked = len(registry.requests)
    again = await proxy.ask(context, "manifests/app/2.0", unremembered, limit=1000)

    assert first == again == Absent()
    assert len(registry.requests) > asked
    assert list(await db.scalars(select(NegativeCacheEntry))) == []


async def test_a_remote_that_fails_is_recorded_and_says_what_it_answered(
    context, registry, db, upstream
):
    registry.status = 503

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)

    assert isinstance(answer, Unavailable)
    assert (answer.error.status_code, answer.error.code) == (502, "remote_unavailable")
    assert answer.status == 503
    recorded = await state(db, upstream)
    assert (recorded.failures, recorded.last_error) == (1, "the remote answered 503")


async def test_a_refusal_is_told_apart_from_a_failure(context, registry):
    registry.private.add("team/app")
    registry.accounts.clear()  # the credential is no longer good: sign-in itself is refused

    refused = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)

    assert isinstance(refused, Unavailable) and refused.status == 401


async def test_a_blocked_remote_is_not_asked(context, registry, db, upstream):
    upstream.config = {**upstream.config, "proxy": {**upstream.config["proxy"], "blocked": True}}
    await db.commit()

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)
    asked = await proxy.probe(context, "manifests/app/1.0", source())

    assert isinstance(answer, Unavailable) and isinstance(asked, Unavailable)
    assert "blocked" in answer.error.message
    assert registry.requests == []


async def test_a_document_longer_than_its_limit_is_not_read(context, registry, db, upstream):
    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=10)

    assert isinstance(answer, Unavailable) and answer.status is None
    assert (await state(db, upstream)).blocked_until is None


@pytest.mark.parametrize("address", ["https://127.0.0.1/v2/x", "file:///etc/passwd", "https://"])
async def test_an_address_that_must_not_be_fetched_is_not(context, registry, address):
    answer = await proxy.ask(context, "manifests/app/1.0", source(address), limit=1000)

    assert isinstance(answer, Unavailable)
    assert registry.requests == []


async def test_the_credential_stays_with_the_remotes_own_origin(context, registry):
    elsewhere = "https://mirror.registry.test/v2/team/app/manifests/1.0"

    answer = await proxy.ask(context, "manifests/app/1.0", source(elsewhere), limit=100_000)

    assert isinstance(answer, Answer)
    presented = [seen["headers"].get("authorization") for seen in registry.requests]
    assert basic("ci", "secret") not in presented
    assert [account for account, _ in registry.issued.values()] == [None]


async def test_what_cannot_be_used_is_recorded_against_the_remote(context, db, upstream):
    error = await proxy.refuse(context, "manifests/app/1.0", "it sent something else")

    assert isinstance(error, ApiError) and error.status_code == 502
    assert "it sent something else" in error.message
    assert (await state(db, upstream)).last_error == "it sent something else"


async def test_a_whole_file_is_fetched_with_a_sign_in_and_checked(context, registry, db):
    sha256 = hashlib.sha256(LAYER).hexdigest()
    registry.blobs_at = "https://cdn.registry.test"

    await proxy.ensure_cached(context, "blobs/one", source=source(BLOB, digests={"sha256": sha256}))
    await db.commit()

    assert await context.read("blobs/one", limit=len(LAYER)) == LAYER
    assert registry.asked(host="cdn.registry.test") == [f"/cdn/{digest_of(LAYER)}"]


async def test_a_whole_file_that_is_missing_need_not_be_remembered(context, registry, db):
    data = b"pushed a moment later"
    address = f"{REGISTRY}/v2/team/app/blobs/{digest_of(data)}"
    wanted = source(address, remember_missing=False)

    with pytest.raises(ApiError) as missing:
        await proxy.ensure_cached(context, "blobs/two", source=wanted)
    registry.add_blob("team/app", data)
    await proxy.ensure_cached(context, "blobs/two", source=wanted)

    assert missing.value.status_code == 404
    assert await context.read("blobs/two", limit=100) == data


async def test_a_cached_file_records_what_it_refers_to(context, db):
    staged = await context.stage_bytes(b"a manifest")
    await context.cache(
        "manifests/app/one",
        staged,
        content_type=ACCEPT,
        attributes={},
        now=utcnow(),
        references=["blobs/not-fetched-yet", "blobs/another"],
    )
    again = await context.stage_bytes(b"a manifest")
    await context.cache(
        "manifests/app/one", again, content_type=ACCEPT, attributes={}, now=utcnow()
    )

    # Nothing said the second time: what was recorded stands.
    assert await context.references("manifests/app/one") == [
        "blobs/another",
        "blobs/not-fetched-yet",
    ]
    assert await context.referenced(["blobs/another", "blobs/x"]) == {"blobs/another"}


async def test_what_is_held_can_be_marked_as_still_what_the_remote_has(context, db):
    long_ago = utcnow() - timedelta(days=3)
    staged = await context.stage_bytes(b"a tag")
    await context.cache("tags/app/1.0", staged, content_type=None, attributes={}, now=long_ago)

    await proxy.still_current(context, "tags/app/1.0")
    await proxy.still_current(context, "tags/app/none")  # nothing held: nothing to mark

    assert (await context.stat("tags/app/1.0")).verified > long_ago + timedelta(days=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_proxy_asking.py -q`
Expected: collection error, `cannot import name 'Absent' from 'megooarti.repositories.proxy'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`:

After

```python
    # through a protocol with an address of its own, which then has its own routes.
    served_at: str = "repository"
```

add

```python
    # Whether this format's remotes hand out tokens: answer a request with `401` and
    # the address of a token service, as container registries do. A proxy then signs in.
    remote_signs_in: bool = False
```

In `backend/src/megooarti/repositories/content.py`:

Replace

```python
        attributes: dict[str, Any],
        now: datetime,
    ) -> Asset:
        """Record content a proxy repository fetched from its remote.

        No permission or policy check: a reader triggered this, and their `read` on the
        proxy (or on the group in front of it) has already been checked. For that reason
        it works only on a proxy repository.
        """
```

with

```python
        attributes: dict[str, Any],
        now: datetime,
        references: Collection[str] | None = None,
    ) -> Asset:
        """Record content a proxy repository fetched from its remote.

        No permission or policy check: a reader triggered this, and their `read` on the
        proxy (or on the group in front of it) has already been checked. For that reason
        it works only on a proxy repository. `references` are as for `store`; what they
        name need not have been fetched yet.
        """
```

Replace

```python
            created_by=PROXY_CREATOR,
            attributes=attributes,
            verified_at=now,
        )
        return asset
```

with

```python
            created_by=PROXY_CREATOR,
            attributes=attributes,
            verified_at=now,
        )
        await self._refer(asset, references)
        return asset
```

Replace

```python
        if references is not None:
            await self.db.execute(delete(AssetReference).where(AssetReference.asset_id == asset.id))
            targets = sorted(set(references))
            if targets:
                await self.db.execute(
                    insert(AssetReference),
                    [{"asset_id": asset.id, "target": target} for target in targets],
                )
        return asset, created
```

with

```python
        await self._refer(asset, references)
        return asset, created

    async def _refer(self, asset: Asset, references: Collection[str] | None) -> None:
        """Record what a file refers to, in place of what was recorded. None changes nothing."""
        if references is None:
            return
        await self.db.execute(delete(AssetReference).where(AssetReference.asset_id == asset.id))
        targets = sorted(set(references))
        if targets:
            await self.db.execute(
                insert(AssetReference),
                [{"asset_id": asset.id, "target": target} for target in targets],
            )
```

In `backend/src/megooarti/repositories/proxy.py`:

After

```python
    host, and the hash each must have. `digests` maps an algorithm the blob store
    computes to lower-case hex.
    """

    url: str
    digests: Mapping[str, str] = field(default_factory=dict)
```

add

```python
    # The media types to ask for, where a remote serves one address in several forms.
    accept: str | None = None
    # What the address is part of, for a remote that issues a token for each thing it
    # serves: a container image. See `remote.SignIn`.
    subject: str = ""
    # Whether a miss is remembered under the path. Not if the same path can be found
    # at another address, as a blob that several images share can.
    remember_missing: bool = True


@dataclass(frozen=True)
class Answer:
    """What a remote said when asked for a small document, or about one."""

    headers: Mapping[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class Absent:
    """The remote has no such thing."""


@dataclass(frozen=True)
class Unavailable:
    """The remote could not be asked, or did not help. `error` is what to answer with."""

    error: ApiError
    status: int | None = None  # what the remote answered, if it answered
```

After

```python
    await context.db.commit()
    log.warning("remote_failed", repository=context.repository.name, path=path, reason=reason)
    return reason
```

add

```python
def _sign_in(context: RepositoryContext, source: Source | None) -> remote.SignIn | None:
    """How to sign in to this repository's remote, if its format's remotes want that."""
    if not context.format.remote_signs_in:
        return None
    remote_url = context.repository.config["proxy"]["remote_url"]
    return remote.SignIn(remote_url, "" if source is None else source.subject)


async def refuse(context: RepositoryContext, path: str, reason: str) -> ApiError:
    """Record that what the remote sent for a path cannot be used. Returns the 502 to raise.

    For a format that reads what it fetched and finds it is not what it should be.
    """
    return _unavailable(await _fail(context, path, remote.Failed(reason, blockable=False)))


async def _consult(
    context: RepositoryContext, path: str, source: Source, limit: int | None
) -> Answer | Absent | Unavailable:
    db, repository = context.db, context.repository
    now = utcnow()
    if source.remember_missing and await proxy_state.known_missing(db, repository, path, now):
        return Absent()
    if await proxy_state.blocked(db, repository, now):
        return Unavailable(_unavailable("it is blocked"))
    try:
        url, credential = await _target(context, path, source)
    except ApiError as error:  # recorded already
        return Unavailable(error)
    await db.commit()  # give the connection back while the remote is asked

    sign_in = _sign_in(context, source)
    http = context.http()
    if limit is None:
        outcome = await remote.head(
            http, url, authorization=credential, accept=source.accept, sign_in=sign_in
        )
    else:
        outcome = await remote.fetch(
            http, url, authorization=credential, limit=limit, accept=source.accept, sign_in=sign_in
        )
    now = utcnow()
    if isinstance(outcome, remote.Exists | remote.Document):
        await proxy_state.record_success(db, repository, now)
        await db.commit()
        if isinstance(outcome, remote.Exists):
            return Answer(outcome.every)
        return Answer(outcome.headers, outcome.body)
    if isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if source.remember_missing:
            await proxy_state.remember_missing(db, repository, path, now)
        await db.commit()
        return Absent()
    reason = await _fail(context, path, outcome)
    return Unavailable(_unavailable(reason), getattr(outcome, "status", None))


async def ask(
    context: RepositoryContext, path: str, source: Source, *, limit: int
) -> Answer | Absent | Unavailable:
    """Fetch a small document from the remote into memory, for a format that reads it.

    `path` is what the document would be cached under: a miss is remembered under it,
    and a failure is recorded against it. Nothing is cached here; the caller knows
    what the document is and how to store it. The remote is not asked while it is
    blocked, and what comes of asking is recorded as for any fetch.

    This commits, before asking and after. A caller must have no uncommitted work.
    """
    return await _consult(context, normalise_path(path), source, limit)


async def probe(
    context: RepositoryContext, path: str, source: Source
) -> Answer | Absent | Unavailable:
    """Ask the remote about a path without fetching it. The answer has headers and no body.

    As `ask` in every other way.
    """
    return await _consult(context, normalise_path(path), source, None)


async def still_current(context: RepositoryContext, path: str) -> None:
    """Record that the remote was asked just now, and what is held is still what it has."""
    asset = await context.get(normalise_path(path))
    if asset is not None:
        asset.last_verified_at = utcnow()
```

Replace

```python
    db, repository = context.db, context.repository
    now = utcnow()
    if asset is None and await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        if asset is None:
            raise _unavailable("it is blocked")
        return
```

with

```python
    db, repository = context.db, context.repository
    now = utcnow()
    remember = source is None or source.remember_missing
    if asset is None and remember and await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        if asset is None:
            raise _unavailable("it is blocked")
        return
```

Replace

```python
        stage=stage,
        etag=known.get("remote_etag"),
        last_modified=known.get("remote_last_modified"),
    )
    now = utcnow()
```

with

```python
        stage=stage,
        etag=known.get("remote_etag"),
        last_modified=known.get("remote_last_modified"),
        accept=None if source is None else source.accept,
        sign_in=_sign_in(context, source),
    )
    now = utcnow()
```

Replace

```python
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if asset is None:
            await proxy_state.remember_missing(db, repository, path, now)
            await db.commit()
            raise _not_found()
```

with

```python
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if asset is None:
            if remember:
                await proxy_state.remember_missing(db, repository, path, now)
            await db.commit()
            raise _not_found()
```

Replace

```python
    outcome = await remote.head(context.http(), url, authorization=credential)
```

with

```python
    outcome = await remote.head(
        context.http(), url, authorization=credential, sign_in=_sign_in(context, None)
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_proxy_asking.py tests/repositories/test_proxy.py tests/repositories/test_content_references.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories/test_proxy_asking.py
git commit -m "feat(repositories): ask a remote for a document, or about one, without caching it"
```

---

### Task 3: Docker proxy repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Modify: `backend/src/megooarti/repositories/docker/names.py`
- Modify: `backend/tests/repositories/docker/conftest.py`
- Modify: `backend/tests/repositories/docker/test_registry.py`
- Test: `backend/tests/repositories/docker/test_proxy.py`

**Interfaces:**
- Consumes: `proxy.ask`, `proxy.probe`, `proxy.refuse`, `proxy.still_current`, `proxy.ensure_cached`, `proxy.Source`, `proxy.Answer`, `proxy.Absent`, `proxy.Unavailable`, `proxy.is_fresh`, `context.cache(..., references=)`, `Format.remote_signs_in` (Task 2); `FakeRegistry` (Task 1); `manifests.read`, `names`, `_blob`, `_read_manifest`, `_tags`, `_not_allowed`, `unknown` from plan 7a.
- Produces:
  - `names.list_path(image: str) -> str`: `lists/<image>`.
  - `DockerFormat.types` is `{"hosted", "proxy"}`; `remote_signs_in = True`; `is_metadata` is true for `tags/` and `lists/`; `content_type` is `application/octet-stream` for `blobs/`; `handle_proxy`.
  - `_tag_page(context, request, image, held: list[str]) -> Response`, shared by hosted and proxy tag lists.
  - In the tests' `conftest.py`, `create(db, name, *, hosted=None, proxy=None)` makes a proxy when `proxy` is given.

- [ ] **Step 1: Write the failing tests**

The helper that creates a repository learns to make a proxy, and the test that said a Docker repository can only be hosted now says it can be hosted or a proxy.

`backend/tests/repositories/docker/test_proxy.py`:

```python
"""A Docker proxy: a pull-through cache of another registry."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from starlette.responses import JSONResponse, Response

from megooarti import secrets_box
from megooarti.clock import utcnow
from megooarti.repositories.content import build_context
from megooarti.repositories.docker.manifests import DOCKER_MANIFEST, OCI_INDEX, OCI_MANIFEST
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Asset, AssetReference, ProxyState
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import create, digest_of, error_code, index_manifest
from tests.repositories.fake_registry import REGISTRY, FakeRegistry
from tests.repositories.fake_registry import basic as remote_basic

HUB = "/v2/hub"
LAYER = b"\x1f\x8b the first layer " * 500
OTHER = b"\x1f\x8b another layer"
TAG = f"{HUB}/team/app/manifests/1.0"


@pytest.fixture
def registry(app) -> FakeRegistry:
    fake = FakeRegistry()
    app.state.http = fake.client()
    return fake


@pytest.fixture
async def hub(db, registry):
    return await create(db, "hub", proxy={"remote_url": REGISTRY})


@pytest.fixture
def manifest(registry) -> bytes:
    """The image `team/app:1.0` at the remote."""
    return registry.add_image("team/app", "1.0", LAYER, OTHER)


async def make_stale(db) -> None:
    long_ago = utcnow() - timedelta(days=3)
    await db.execute(update(Asset).values(last_verified_at=long_ago))
    await db.commit()


def manifest_requests(registry: FakeRegistry) -> list[tuple[str, str]]:
    return [
        (seen["method"], seen["path"].rpartition("/")[2][:12])
        for seen in registry.requests
        if "/manifests/" in seen["path"] and "authorization" in seen["headers"]
    ]


async def test_an_image_is_pulled_through_the_proxy_and_kept(client, hub, root, registry, manifest):
    digest = digest_of(manifest)

    by_tag = await client.get(TAG, headers=root)
    by_digest = await client.get(f"{HUB}/team/app/manifests/{digest}", headers=root)
    layer = await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)
    asked = len(registry.requests)
    again = [
        await client.get(TAG, headers=root),
        await client.head(TAG, headers=root),
        await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root),
    ]

    assert (by_tag.status_code, by_tag.content) == (200, manifest)
    assert by_tag.headers["Content-Type"] == OCI_MANIFEST
    assert by_tag.headers["Docker-Content-Digest"] == digest
    assert by_digest.content == manifest
    assert (layer.content, layer.headers["Docker-Content-Digest"]) == (LAYER, digest_of(LAYER))
    assert layer.headers["Content-Type"] == "application/octet-stream"
    assert [response.status_code for response in again] == [200, 200, 200]
    assert len(registry.requests) == asked  # all of it from what was kept


async def test_what_is_kept_is_laid_out_as_in_a_hosted_repository(
    client, hub, root, registry, manifest, db
):
    digest = digest_of(manifest)
    await client.get(TAG, headers=root)
    await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)

    paths = sorted(await db.scalars(select(Asset.path)))
    referred = sorted(await db.scalars(select(AssetReference.target)))
    catalog = await client.get("/v2/_catalog", headers=root)
    tags = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert paths == sorted(
        [f"blobs/{digest_of(LAYER)}", f"manifests/team/app/{digest}", "tags/team/app/1.0"]
    )
    # What the manifest refers to is recorded before any of it has been fetched.
    assert len(referred) == 3 and f"blobs/{digest_of(OTHER)}" in referred
    assert catalog.json() == {"repositories": ["hub/team/app"]}
    assert tags.json() == {"name": "hub/team/app", "tags": ["1.0"]}


async def test_the_remote_is_asked_for_every_kind_of_manifest(
    client, hub, root, registry, manifest
):
    await client.get(TAG, headers=root)

    accepted = registry.requests[-1]["headers"]["accept"]
    assert all(kind in accepted for kind in (OCI_MANIFEST, OCI_INDEX, DOCKER_MANIFEST))


async def test_one_sign_in_serves_a_whole_pull(client, hub, root, registry, manifest):
    await client.get(TAG, headers=root)
    for layer in (LAYER, OTHER):
        await client.get(f"{HUB}/team/app/blobs/{digest_of(layer)}", headers=root)

    assert registry.asked(host="auth.registry.test") == ["/token"]


async def test_a_tag_is_only_asked_about_until_it_names_something_else(
    client, hub, root, registry, manifest, db
):
    await client.get(TAG, headers=root)
    registry.requests.clear()

    fresh = await client.get(TAG, headers=root)
    nothing_asked = list(registry.requests)
    await make_stale(db)
    unchanged = await client.get(TAG, headers=root)
    only_asked = manifest_requests(registry)
    moved = registry.add_image("team/app", "1.0", LAYER, b"a new layer")
    await make_stale(db)
    registry.requests.clear()
    changed = await client.get(TAG, headers=root)
    old = await client.get(f"{HUB}/team/app/manifests/{digest_of(manifest)}", headers=root)

    assert (fresh.content, nothing_asked) == (manifest, [])
    assert (unchanged.content, only_asked) == (manifest, [("HEAD", "1.0")])
    assert changed.content == moved
    assert manifest_requests(registry) == [("HEAD", "1.0"), ("GET", digest_of(moved)[:12])]
    assert old.content == manifest  # what a deployment pinned is still here


async def test_a_remote_that_does_not_say_what_a_tag_names_is_asked_for_the_manifest(
    client, hub, root, registry, manifest, db
):
    registry.digest_header = False

    first = await client.get(TAG, headers=root)
    by_digest = await client.get(f"{HUB}/team/app/manifests/{digest_of(manifest)}", headers=root)
    await make_stale(db)
    registry.requests.clear()
    again = await client.get(TAG, headers=root)

    assert first.content == by_digest.content == again.content == manifest
    assert manifest_requests(registry) == [("HEAD", "1.0"), ("GET", "1.0")]
    assert (
        await db.scalar(select(Asset).where(Asset.path == "tags/team/app/1.0"))
    ).last_verified_at > (utcnow() - timedelta(minutes=1))


async def test_what_is_kept_is_served_while_the_remote_is_down(
    client, hub, root, registry, manifest, db
):
    await client.get(TAG, headers=root)
    await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)
    await make_stale(db)
    registry.down = True

    kept = await client.get(TAG, headers=root)
    layer = await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)
    never_fetched = await client.get(f"{HUB}/team/app/blobs/{digest_of(OTHER)}", headers=root)
    other_tag = await client.get(f"{HUB}/team/app/manifests/2.0", headers=root)

    assert (kept.content, layer.content) == (manifest, LAYER)
    for response in (never_fetched, other_tag):
        assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert (await db.scalar(select(ProxyState.failures))) >= 1


async def test_a_tag_the_remote_dropped_is_kept(client, hub, root, registry, manifest, db):
    await client.get(TAG, headers=root)
    del registry.manifests[("team/app", "1.0")]
    await make_stale(db)

    response = await client.get(TAG, headers=root)

    assert response.content == manifest


async def test_what_the_remote_does_not_have_is_unknown(client, hub, root, registry, manifest):
    absent = "sha256:" + "0" * 64

    tag = await client.get(f"{HUB}/team/app/manifests/2.0", headers=root)
    by_digest = await client.get(f"{HUB}/team/app/manifests/{absent}", headers=root)
    blob = await client.get(f"{HUB}/team/app/blobs/{absent}", headers=root)
    asked = await client.head(f"{HUB}/team/app/blobs/{absent}", headers=root)
    tags = await client.get(f"{HUB}/team/nothing/tags/list", headers=root)

    assert (tag.status_code, error_code(tag)) == (404, "MANIFEST_UNKNOWN")
    assert (by_digest.status_code, error_code(by_digest)) == (404, "MANIFEST_UNKNOWN")
    assert (blob.status_code, error_code(blob)) == (404, "BLOB_UNKNOWN")
    assert asked.status_code == 404
    assert (tags.status_code, error_code(tags)) == (404, "NAME_UNKNOWN")


async def test_an_image_the_remote_will_not_show_is_unknown_not_an_outage(
    client, hub, root, registry, manifest, db
):
    registry.private.add("team/app")

    response = await client.get(TAG, headers=root)
    tags = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert (response.status_code, error_code(response)) == (404, "MANIFEST_UNKNOWN")
    assert "does not let this proxy read it" in response.json()["errors"][0]["message"]
    assert (tags.status_code, error_code(tags)) == (404, "NAME_UNKNOWN")
    assert await db.scalar(select(ProxyState.blocked_until)) is None


async def test_a_private_image_is_pulled_with_the_proxys_credential(
    client, db, root, registry, manifest, settings
):
    registry.accounts["ci"] = "secret"
    registry.private.add("team/app")
    registry.blobs_at = "https://cdn.registry.test"
    auth = {"type": "basic", "username": "ci", "secret": secrets_box.seal(settings, "secret")}
    await create(db, "private", proxy={"remote_url": REGISTRY, "remote_auth": auth})

    pulled = await client.get("/v2/private/team/app/manifests/1.0", headers=root)
    layer = await client.get(f"/v2/private/team/app/blobs/{digest_of(LAYER)}", headers=root)

    assert (pulled.content, layer.content) == (manifest, LAYER)
    credential = remote_basic("ci", "secret")
    shown_to = {
        seen["host"]
        for seen in registry.requests
        if seen["headers"].get("authorization") == credential
    }
    assert shown_to == {"registry.test", "auth.registry.test"}  # never where the blobs are kept
    assert "secret" not in pulled.text + layer.headers.get("WWW-Authenticate", "")


@pytest.mark.parametrize(
    ("remote", "image", "asked"),
    [
        ("https://registry-1.docker.io", "alpine", "/v2/library/alpine/manifests/3"),
        ("https://registry-1.docker.io/", "team/app", "/v2/team/app/manifests/3"),
        ("https://ghcr.io", "alpine", "/v2/alpine/manifests/3"),
        ("https://registry.test/mirror", "team/app", "/mirror/v2/team/app/manifests/3"),
    ],
)
async def test_where_an_image_is_at_the_remote(client, db, root, registry, remote, image, asked):
    registry.wants_token = False
    await create(db, "public", proxy={"remote_url": remote})

    await client.get(f"/v2/public/{image}/manifests/3", headers=root)

    assert [seen["path"] for seen in registry.requests] == [asked]


async def test_content_that_is_not_what_its_digest_says_is_not_kept(
    client, hub, root, registry, manifest, db
):
    digest, layer = digest_of(manifest), digest_of(LAYER)
    registry.manifests[("team/app", digest)] = (manifest + b" ", OCI_MANIFEST)  # a manifest still
    registry.blobs[("team/app", layer)] = b"not that layer"

    by_digest = await client.get(f"{HUB}/team/app/manifests/{digest}", headers=root)
    blob = await client.get(f"{HUB}/team/app/blobs/{layer}", headers=root)

    for response in (by_digest, blob):
        assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert "not the one asked for" in by_digest.json()["errors"][0]["message"]
    assert list(await db.scalars(select(Asset.path))) == []


@pytest.mark.parametrize(
    "sent",
    [
        b"<html>not a manifest</html>",
        json.dumps({"schemaVersion": 1, "name": "team/app", "fsLayers": []}).encode(),
        json.dumps({"schemaVersion": 2, "mediaType": "text/html", "layers": []}).encode(),
        b"[" * 100_000,
    ],
    ids=["html", "schema 1", "another type", "deeply nested"],
)
async def test_what_is_not_a_manifest_is_not_kept(client, hub, root, registry, db, sent):
    registry.add_manifest("team/app", "1.0", sent, "application/json")

    response = await client.get(TAG, headers=root)

    assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert "cannot be used" in response.json()["errors"][0]["message"]
    assert list(await db.scalars(select(Asset.path))) == []


async def test_blobs_come_from_where_the_remote_keeps_them(client, hub, root, registry, manifest):
    registry.blobs_at = "https://cdn.registry.test"

    layer = await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)

    assert layer.content == LAYER
    (from_cdn,) = [seen for seen in registry.requests if seen["host"] == "cdn.registry.test"]
    assert "authorization" not in from_cdn["headers"]


async def test_asking_about_a_layer_does_not_fetch_it(client, hub, root, registry, manifest, db):
    address = f"{HUB}/team/app/blobs/{digest_of(LAYER)}"

    asked = await client.head(address, headers=root)

    assert asked.status_code == 200
    assert asked.headers["Content-Length"] == str(len(LAYER))
    assert asked.headers["Docker-Content-Digest"] == digest_of(LAYER)
    assert "GET" not in {seen["method"] for seen in registry.requests if "/blobs/" in seen["path"]}
    assert list(await db.scalars(select(Asset.path))) == []


async def test_a_layer_asked_for_under_the_wrong_image_does_not_hide_it_from_the_right_one(
    client, hub, root, registry, manifest
):
    layer = digest_of(LAYER)

    wrong = await client.get(f"{HUB}/team/unrelated/blobs/{layer}", headers=root)
    right = await client.get(f"{HUB}/team/app/blobs/{layer}", headers=root)
    shared = await client.get(f"{HUB}/team/unrelated/blobs/{layer}", headers=root)

    assert (wrong.status_code, error_code(wrong)) == (404, "BLOB_UNKNOWN")
    assert right.content == LAYER
    assert shared.content == LAYER  # once kept, a layer is the repository's


async def test_an_image_for_several_platforms_is_fetched_piece_by_piece(
    client, hub, root, registry, db
):
    platforms = [registry.add_image("team/multi", f"only-{arch}", arch.encode()) for arch in "ab"]
    del registry.manifests[("team/multi", "only-a")], registry.manifests[("team/multi", "only-b")]
    index = index_manifest(*platforms)
    registry.add_manifest("team/multi", "1.0", index, OCI_INDEX)

    pulled = await client.get(f"{HUB}/team/multi/manifests/1.0", headers=root)
    before = sorted(await db.scalars(select(Asset.path)))
    one = await client.get(f"{HUB}/team/multi/manifests/{digest_of(platforms[0])}", headers=root)

    assert (pulled.content, pulled.headers["Content-Type"]) == (index, OCI_INDEX)
    assert before == sorted([f"manifests/team/multi/{digest_of(index)}", "tags/team/multi/1.0"])
    assert one.content == platforms[0]
    referred = set(await db.scalars(select(AssetReference.target)))
    assert {f"manifests/team/multi/{digest_of(platform)}" for platform in platforms} <= referred


async def test_the_tags_of_an_image_are_the_remotes_read_page_by_page(
    client, hub, root, registry, db
):
    for number in range(7):
        registry.add_image("team/app", f"1.{number}", LAYER)
    registry.page_size = 3

    listed = await client.get(f"{HUB}/team/app/tags/list", headers=root)
    asked = [seen["query"] for seen in registry.requests if seen["path"].endswith("/tags/list")]
    page = await client.get(f"{HUB}/team/app/tags/list?n=2&last=1.1", headers=root)
    requests = len(registry.requests)
    await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert listed.json() == {"name": "hub/team/app", "tags": [f"1.{n}" for n in range(7)]}
    assert {query.get("last") for query in asked} == {None, "1.2", "1.5"}  # three pages
    assert page.json()["tags"] == ["1.2", "1.3"]
    assert page.headers["Link"] == f'<{HUB}/team/app/tags/list?n=2&last=1.3>; rel="next"'
    assert len(registry.requests) == requests  # the list is kept for a while, like a tag


async def test_a_list_of_tags_is_renewed_when_it_is_old_and_kept_if_it_cannot_be(
    client, hub, root, registry, manifest, db
):
    await client.get(f"{HUB}/team/app/tags/list", headers=root)
    registry.add_image("team/app", "2.0", LAYER)

    still = await client.get(f"{HUB}/team/app/tags/list", headers=root)
    await make_stale(db)
    renewed = await client.get(f"{HUB}/team/app/tags/list", headers=root)
    await make_stale(db)
    registry.down = True
    kept = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert still.json()["tags"] == ["1.0"]
    assert renewed.json()["tags"] == kept.json()["tags"] == ["1.0", "2.0"]


@pytest.mark.parametrize("sent", [b"not json", b'{"tags": "1.0"}', b'["1.0"]'])
async def test_a_list_of_tags_that_cannot_be_read_is_not_kept(
    client, hub, root, registry, db, monkeypatch, sent
):
    monkeypatch.setattr(registry, "_tags", lambda request, image: Response(sent))

    response = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert list(await db.scalars(select(Asset.path))) == []


async def test_a_list_of_tags_does_not_lead_the_proxy_to_an_internal_address(
    client, hub, root, registry, monkeypatch
):
    link = {"Link": '<https://169.254.169.254/latest/meta-data>; rel="next"'}
    page = JSONResponse({"tags": ["1.0"]}, headers=link)
    monkeypatch.setattr(registry, "_tags", lambda request, image: page)

    response = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert {seen["host"] for seen in registry.requests} == {"registry.test", "auth.registry.test"}


async def test_only_tags_that_can_be_tags_are_listed(client, hub, root, registry, monkeypatch):
    sent = {"tags": ["1.0", "", "../../etc", 7, None, "ok_tag", "x" * 200, "1.0"]}
    monkeypatch.setattr(registry, "_tags", lambda request, image: JSONResponse(sent))

    response = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert response.json()["tags"] == ["1.0", "ok_tag"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "team/app/blobs/uploads/"),
        ("PUT", "team/app/manifests/1.0"),
        ("DELETE", "team/app/manifests/1.0"),
        ("PATCH", "team/app/blobs/uploads/" + "0" * 32),
        ("DELETE", "team/app/blobs/sha256:" + "0" * 64),
    ],
)
async def test_nothing_is_pushed_to_a_proxy_or_deleted_from_it(
    client, hub, root, registry, method, path
):
    response = await client.request(method, f"{HUB}/{path}", content=b"{}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
    assert response.headers["Allow"] == "GET, HEAD"
    assert registry.requests == []


async def test_pulling_through_a_proxy_needs_read_on_it(
    client, hub, root, registry, manifest, make_user, db
):
    await roles.create_role(db, "pullers", "", ["repository:docker:hub:read"], [])
    await roles.create_role(db, "others", "", ["repository:docker:elsewhere"], [])
    await db.commit()
    await make_user("puller", roles=["pullers"])
    await make_user("other", roles=["others"])

    allowed = await client.get(TAG, headers=basic("puller", PASSWORD))
    denied = await client.get(TAG, headers=basic("other", PASSWORD))
    nobody = await client.get(TAG)

    assert allowed.content == manifest
    assert (denied.status_code, error_code(denied)) == (403, "DENIED")
    assert nobody.status_code == 401
    assert "repository:hub/team/app:pull" in nobody.headers["WWW-Authenticate"]


async def test_maintenance_removes_layers_no_kept_manifest_refers_to(
    client, hub, root, registry, manifest, db, settings
):
    stray = registry.add_blob("team/app", b"fetched by its digest alone")
    await client.get(TAG, headers=root)
    for digest in (digest_of(LAYER), stray):
        await client.get(f"{HUB}/team/app/blobs/{digest}", headers=root)
    await db.execute(update(Asset).values(updated_at=utcnow() - timedelta(days=2)))
    await db.commit()

    context = await build_context(db, settings, hub, None)
    await get_format("docker").maintain(context, utcnow())
    await db.commit()

    held = set(await db.scalars(select(Asset.path)))
    assert f"blobs/{digest_of(LAYER)}" in held
    assert f"blobs/{stray}" not in held
```

In `backend/tests/repositories/docker/conftest.py`:

Replace

```python
async def create(db, name: str, *, hosted: dict | None = None) -> Repository:
    """A hosted Docker repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="docker",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config={},
    )
```

with

```python
async def create(
    db, name: str, *, hosted: dict | None = None, proxy: dict | None = None
) -> Repository:
    """A Docker repository, committed: hosted, or a proxy if its settings are given."""
    repository = await service.create_repository(
        db,
        name=name,
        format="docker",
        type="hosted" if proxy is None else "proxy",
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        format_config={},
    )
```

In `backend/tests/repositories/docker/test_registry.py`:

Replace

```python
async def test_a_format_can_only_be_hosted_for_now(admin_client):
    for kind, extra in (
        ("proxy", {"proxy": {"remote_url": "https://registry-1.docker.io"}}),
        ("group", {"group": {"members": []}}),
    ):
        body = {"name": f"docker-{kind}", "format": "docker", "type": kind, **extra}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == 422, kind
```

with

```python
async def test_a_repository_is_hosted_or_a_proxy_for_now(admin_client):
    proxy = {"proxy": {"remote_url": "https://registry-1.docker.io"}}
    group = {"group": {"members": []}}
    for kind, extra, status in (("proxy", proxy, 201), ("group", group, 422)):
        body = {"name": f"docker-{kind}", "format": "docker", "type": kind, **extra}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == status, kind
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/docker -q`
Expected: 6 failed, 33 errors, all in `test_proxy.py` and the changed test in `test_registry.py`: `proxy repositories are not available for this format`. The tests of plan 7a pass.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/docker/names.py`:

Before

```python
def tag_of(path: str) -> tuple[str, str] | None:
```

add

```python
def list_path(image: str) -> str:
    """Where a proxy keeps the list of an image's tags, as its remote gave it."""
    return f"lists/{image}"
```

In `backend/src/megooarti/repositories/docker/format.py`:

Replace

```python
Deleting a manifest removes what only it used. Pushing a manifest and deleting one take
the same lock, so a push never ends up referring to a blob a delete has just removed.
"""

from datetime import datetime, timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from megooarti.errors import ApiError
from megooarti.repositories import uploads
```

with

```python
Deleting a manifest removes what only it used. Pushing a manifest and deleting one take
the same lock, so a push never ends up referring to a blob a delete has just removed.

A proxy keeps what it fetches in the same layout. A manifest is read before it is kept,
so what is stored is a manifest, is the one that was asked for, and records what it
refers to. A tag is asked about again when it is old, and only asked about: the remote
says which manifest the tag names, and that is fetched only if it is another one.
"""

import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy, uploads
```

Replace

```python
    held = sorted(await context.versions("", parsed.image))
    if not held:
        raise unknown("NAME_UNKNOWN", "No such image.")
    count, last = _page(request, _TAGS_DEFAULT, _CATALOG_MOST)
    after = [tag for tag in held if tag > last]
    page = after[:count]
    headers = {}
    if count and len(after) > count:
        more = _address(context, parsed.image, f"tags/list?n={count}&last={page[-1]}")
        headers["Link"] = f'<{more}>; rel="next"'
    name = f"{context.repository.name}/{parsed.image}"
    return JSONResponse({"name": name, "tags": page}, headers=headers)
```

with

```python
    held = sorted(await context.versions("", parsed.image))
    if not held:
        raise unknown("NAME_UNKNOWN", "No such image.")
    return _tag_page(context, request, parsed.image, held)


def _tag_page(
    context: RepositoryContext, request: Request, image: str, held: list[str]
) -> Response:
    """A page of an image's tags, which are in order, with where the next page is."""
    count, last = _page(request, _TAGS_DEFAULT, _CATALOG_MOST)
    after = [tag for tag in held if tag > last]
    page = after[:count]
    headers = {}
    if count and len(after) > count:
        more = _address(context, image, f"tags/list?n={count}&last={page[-1]}")
        headers["Link"] = f'<{more}>; rel="next"'
    name = f"{context.repository.name}/{image}"
    return JSONResponse({"name": name, "tags": page}, headers=headers)
```

Replace

```python
class DockerFormat(Format):
    name = FORMAT
    served_at = "registry"
    # Proxy and group repositories need the registry's own handling.
    types = frozenset({"hosted"})
```

with

```python
# --- A proxy: what its remote has, fetched when it is asked for -----------------------

# Every kind of manifest this registry keeps, so that the remote sends the one it has
# and does not convert it: a converted manifest has another digest.
_ACCEPT = ", ".join(
    (manifests.OCI_INDEX, manifests.DOCKER_LIST, manifests.OCI_MANIFEST, manifests.DOCKER_MANIFEST)
)
# Docker Hub keeps its official images under `library/`, and Docker leaves that out.
_HUB = "registry-1.docker.io"
_LIST_PAGE_BYTES = 4 * 1024 * 1024
_LIST_PAGES_MOST = 100
_LIST_TAGS_MOST = 100_000
_LIST_BYTES_MOST = 16 * 1024 * 1024
_NEXT = re.compile(r'<([^>]*)>\s*;\s*rel="?next"?')


def _remote_address(context: RepositoryContext, image: str, rest: str) -> str:
    """Where the remote has something of an image."""
    base = context.repository.config["proxy"]["remote_url"].rstrip("/")
    official = (urlsplit(base).hostname or "").lower() == _HUB and "/" not in image
    name = f"library/{image}" if official else image
    return f"{base}/v2/{quote(name, safe='/')}/{rest}"


def _unhelped(found: proxy.Unavailable, code: str) -> ApiError:
    """What to answer when the remote did not help and nothing is held."""
    if found.status in (401, 403):
        # A registry says this of an image it does not have as of one it will not show.
        message = "The remote has no such image, or does not let this proxy read it."
        return unknown(code, message)
    return found.error


async def _keep_manifest(
    context: RepositoryContext, image: str, raw: bytes, *, asked: str, expected: str | None
) -> manifests.Manifest:
    """Keep a manifest the remote sent, under its digest, with what it refers to.

    `asked` is the path it was fetched for, and `expected` the digest it must have if
    it was asked for by one. What is not a manifest, or not that one, is not kept.
    """
    try:
        manifest = manifests.read(raw, None)
    except manifests.InvalidManifest as error:
        reason = f"it sent a manifest that cannot be used: {error}"
        raise await proxy.refuse(context, asked, reason) from None
    if expected is not None and manifest.digest != expected:
        reason = "it sent a manifest that is not the one asked for"
        raise await proxy.refuse(context, asked, reason)
    needed = [names.blob_path(digest) for digest in manifest.blobs]
    needed += [names.manifest_path(image, digest) for digest in manifest.manifests]
    await context.cache(
        names.manifest_path(image, manifest.digest),
        await context.stage_bytes(raw),
        content_type=manifest.media_type,
        attributes={},
        now=utcnow(),
        references=needed,  # what they name is fetched when it is asked for
    )
    return manifest


async def _fetch_manifest(
    context: RepositoryContext, image: str, digest: str
) -> tuple[bytes, manifests.Manifest]:
    """Fetch the manifest with this digest from the remote, and keep it."""
    path = names.manifest_path(image, digest)
    source = proxy.Source(
        _remote_address(context, image, f"manifests/{digest}"), accept=_ACCEPT, subject=image
    )
    found = await proxy.ask(context, path, source, limit=manifests.MAX_BYTES)
    if isinstance(found, proxy.Absent):
        raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
    if isinstance(found, proxy.Unavailable):
        raise _unhelped(found, "MANIFEST_UNKNOWN")
    kept = await _keep_manifest(context, image, found.body, asked=path, expected=digest)
    return found.body, kept


async def _refresh_tag(context: RepositoryContext, image: str, tag: str) -> None:
    """Make what is held for a tag what the remote has now, if the remote can be asked.

    Returning means there is a manifest to serve: a new one, the old one confirmed, or
    the old one kept because the remote could not be asked or has dropped the tag.
    """
    path = names.tag_path(image, tag)
    held = await context.stat(path)
    by_tag = proxy.Source(
        _remote_address(context, image, f"manifests/{tag}"), accept=_ACCEPT, subject=image
    )
    # Only asking is cheap, and a registry that counts pulls does not count it.
    found = await proxy.probe(context, path, by_tag)
    digest = ""
    if isinstance(found, proxy.Answer):
        digest = found.headers.get("Docker-Content-Digest", "")
    if isinstance(found, proxy.Answer) and not names.is_digest(digest):
        # The remote does not say which manifest the tag names until it is fetched.
        found = await proxy.ask(context, path, by_tag, limit=manifests.MAX_BYTES)
    if isinstance(found, proxy.Unavailable):
        if held is None:
            raise _unhelped(found, "MANIFEST_UNKNOWN")
        return
    if isinstance(found, proxy.Absent):
        if held is None:
            raise unknown("MANIFEST_UNKNOWN", "No such manifest.")
        # The remote dropped a tag we hold. An artifact manager keeps it.
        await proxy.still_current(context, path)
        return
    if held is not None and names.is_digest(digest) and held.sha256 == names.hex_of(digest):
        await proxy.still_current(context, path)
        return
    if names.is_digest(digest):
        by_digest = names.manifest_path(image, digest)
        raw = await context.read(by_digest, limit=manifests.MAX_BYTES)
        if raw is None:
            raw, manifest = await _fetch_manifest(context, image, digest)
        else:
            manifest = manifests.read(raw, None)  # it was read when it was kept
    else:
        raw = found.body
        manifest = await _keep_manifest(context, image, raw, asked=path, expected=None)
    await context.cache(
        path,
        await context.stage_bytes(raw),
        content_type=manifest.media_type,
        attributes={},
        now=utcnow(),
    )


def _is_stale(context: RepositoryContext, asset: object, path: str) -> bool:
    settings = context.repository.config["proxy"]
    return asset is None or not proxy.is_fresh(settings, context.format, asset, path, utcnow())


async def _proxied_manifest(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    image, reference = parsed.image, parsed.reference
    if names.is_digest(reference):
        # A digest names content: once held, it is never asked about again.
        if await context.stat(names.manifest_path(image, reference)) is None:
            await _fetch_manifest(context, image, reference)
    else:
        path = names.tag_path(image, reference)
        if _is_stale(context, await context.get(path), path):
            await _refresh_tag(context, image, reference)
    return await _read_manifest(context, request, parsed)


async def _proxied_blob(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    digest = parsed.reference
    path = names.blob_path(digest)
    if await context.stat(path) is None:
        source = proxy.Source(
            _remote_address(context, parsed.image, f"blobs/{digest}"),
            digests={"sha256": names.hex_of(digest)},
            subject=parsed.image,
            # Another image of the remote may have the blob that this one has not.
            remember_missing=False,
        )
        if request.method == "HEAD":
            # Asking about a layer must not fetch it: it may be gigabytes.
            found = await proxy.probe(context, path, source)
            if isinstance(found, proxy.Absent):
                raise unknown("BLOB_UNKNOWN", "No such blob.")
            if isinstance(found, proxy.Unavailable):
                raise _unhelped(found, "BLOB_UNKNOWN")
            headers = {"Docker-Content-Digest": digest, "Content-Type": _BLOB}
            length = found.headers.get("Content-Length", "")
            if length.isascii() and length.isdigit():
                headers["Content-Length"] = length
            return Response(status_code=200, headers=headers)
        try:
            await proxy.ensure_cached(context, path, source=source)
        except ApiError as error:
            if error.status_code != 404:
                raise
            raise unknown("BLOB_UNKNOWN", "No such blob.") from None
    return await _blob(context, request, parsed)


def _next_page(link: str, current: str) -> str | None:
    """The address of the next page of a list, from the `Link` header of this one."""
    found = _NEXT.search(link)
    if found is None:
        return None
    try:
        return urljoin(current, found[1])
    except ValueError:
        return None


async def _refresh_list(context: RepositoryContext, image: str, *, held: bool) -> None:
    """Fetch every page of the remote's list of an image's tags, and keep it as one."""
    path = names.list_path(image)
    address = _remote_address(context, image, "tags/list?n=1000")
    tags: set[str] = set()
    for _ in range(_LIST_PAGES_MOST):
        # A page that is missing is the end of the list, not a thing to remember.
        source = proxy.Source(
            address, accept="application/json", subject=image, remember_missing=False
        )
        found = await proxy.ask(context, path, source, limit=_LIST_PAGE_BYTES)
        if isinstance(found, proxy.Unavailable):
            if not held:
                raise _unhelped(found, "NAME_UNKNOWN")
            return
        if isinstance(found, proxy.Absent):
            if tags:
                break
            if not held:
                raise unknown("NAME_UNKNOWN", "No such image.")
            await proxy.still_current(context, path)
            return
        try:
            listed = json.loads(found.body).get("tags") or []
        except (ValueError, AttributeError, RecursionError):
            listed = None
        if not isinstance(listed, list):
            raise await proxy.refuse(context, path, "it sent a list of tags that cannot be read")
        tags.update(tag for tag in listed if isinstance(tag, str) and names.is_tag(tag))
        following = _next_page(found.headers.get("Link", ""), address)
        if following is None or len(tags) >= _LIST_TAGS_MOST:
            break
        address = following
    document = json.dumps({"tags": sorted(tags)}).encode()
    await context.cache(
        path,
        await context.stage_bytes(document),
        content_type="application/json",
        attributes={},
        now=utcnow(),
    )


async def _proxied_tags(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    path = names.list_path(parsed.image)
    asset = await context.get(path)
    if _is_stale(context, asset, path):
        await _refresh_list(context, parsed.image, held=asset is not None)
    raw = await context.read(path, limit=_LIST_BYTES_MOST)
    held = json.loads(raw)["tags"] if raw is not None else []
    return _tag_page(context, request, parsed.image, held)


class DockerFormat(Format):
    name = FORMAT
    served_at = "registry"
    # A group needs the registry's own handling, which is not written yet.
    types = frozenset({"hosted", "proxy"})
    remote_signs_in = True

    def content_type(self, path: str, declared: str | None) -> str | None:
        """What a proxy records for a file its engine fetched, which is only ever a blob."""
        return _BLOB if path.startswith("blobs/") else declared

    def is_metadata(self, path: str) -> bool:
        """A tag and a list of tags change at the remote. What a digest names does not."""
        return path.startswith(("tags/", "lists/"))
```

After

```python
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")
```

add

```python
    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        if not _is_read(request):
            # Whatever the address: nothing can be pushed to a proxy, or deleted from it.
            raise _not_allowed("GET, HEAD")
        parsed = names.classify(path)
        if parsed.kind == "blob":
            return await _proxied_blob(context, request, parsed)
        if parsed.kind == "manifest":
            return await _proxied_manifest(context, request, parsed)
        if parsed.kind == "tags":
            return await _proxied_tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/docker -q`
Expected: 266 passed.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2279 passed, 1 skipped; no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/docker backend/tests/repositories/docker
git commit -m "feat(docker): proxy repositories, a pull-through cache that signs in to its remote"
```

---

### Task 4: Real clients and documentation

**Files:**
- Modify: `backend/tests/test_docker_client.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-11-docker-format-design.md`

**Interfaces:**
- Consumes: Docker proxy repositories; the helpers and fixtures of `tests/test_docker_client.py` from plan 7a (`docker`, `registry`, `said`, `call`, `signed_in`, `administrator`, `REGISTRY`).
- Produces: a Docker-marked test in which the Docker client pulls through proxies of Docker Hub and registry.k8s.io.

This test runs only with `pytest -m docker`. It needs internet access: the backend container fetches from `registry-1.docker.io`, `auth.docker.io`, `registry.k8s.io` and the hosts they redirect to. Docker Hub limits pulls without an account to 100 in six hours for an address; one run makes a handful.

- [ ] **Step 1: Write the real-client test**

In `backend/tests/test_docker_client.py`:

Replace

```python
its images in containerd uses containerd's own registry client for that. The last
test uses skopeo, which is built on the image library Podman uses; its image is pulled
from quay.io, so that test needs internet access.
```

with

```python
its images in containerd uses containerd's own registry client for that. The last
test uses skopeo, which is built on the image library Podman uses; its image is pulled
from quay.io, so that test needs internet access. So does the test of proxies: the
backend container fetches from Docker Hub and from registry.k8s.io.
```

Replace

```python
    held = docker(config, "image", "ls", "--quiet", "--filter", f"reference={REGISTRY}/*/*/*")
    for image in set(held.stdout.split()):
        docker(config, "rmi", "--force", image)
```

with

```python
    for depth in ("*/*", "*/*/*"):
        held = docker(config, "image", "ls", "--quiet", "--filter", f"reference={REGISTRY}/{depth}")
        for image in set(held.stdout.split()):
            docker(config, "rmi", "--force", image)
```

Before

```python
def layer_holding(text: str) -> tuple[bytes, str]:
```

add

```python
def test_images_are_pulled_through_proxies_of_public_registries(signed_in, administrator, tmp_path):
    config = signed_in
    # Docker Hub signs a proxy in at another host and keeps its official images under
    # `library/`. registry.k8s.io asks for no sign-in and sends every request elsewhere.
    remotes = {"docker-hub": "https://registry-1.docker.io", "k8s": "https://registry.k8s.io"}
    for name, remote in remotes.items():
        body = {"name": name, "format": "docker", "type": "proxy", "proxy": {"remote_url": remote}}
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    hello = f"{REGISTRY}/docker-hub/hello-world:latest"
    pause = f"{REGISTRY}/k8s/pause:3.10"

    for image in (hello, pause):
        pulled = docker(config, "pull", image)
        assert pulled.returncode == 0, said(pulled)
    ran = docker(config, "run", "--rm", hello)
    assert ran.returncode == 0 and "Hello from Docker!" in ran.stdout, said(ran)

    # What was pulled is listed, with the tags the remote has.
    status, _, catalog = registry("GET", "_catalog")
    assert {"docker-hub/hello-world", "k8s/pause"} <= set(json.loads(catalog)["repositories"])
    status, _, tags = registry("GET", "docker-hub/hello-world/tags/list")
    assert status == 200 and "latest" in json.loads(tags)["tags"], tags

    # It is kept: with the remote blocked, the image is pulled again, by tag and by digest.
    status, headers, _ = registry("HEAD", "docker-hub/hello-world/manifests/latest")
    digest = headers["Docker-Content-Digest"]
    blocked = {"proxy": {"remote_url": remotes["docker-hub"], "blocked": True}}
    status, _, answer = call("PUT", "/repositories/docker-hub", blocked, administrator)
    assert status == 200, answer
    assert docker(config, "rmi", hello).returncode == 0
    again = docker(config, "pull", hello)
    assert again.returncode == 0, said(again)
    pinned = docker(config, "pull", f"{REGISTRY}/docker-hub/hello-world@{digest}")
    assert pinned.returncode == 0, said(pinned)
    never_fetched = docker(config, "pull", f"{REGISTRY}/docker-hub/busybox:latest")
    assert never_fetched.returncode != 0, "pulled what was never fetched from a blocked remote"

    # Nothing is pushed to a proxy.
    assert docker(config, "tag", hello, f"{REGISTRY}/docker-hub/mine:1.0").returncode == 0
    pushed = docker(config, "push", f"{REGISTRY}/docker-hub/mine:1.0")
    assert pushed.returncode != 0, "pushed to a proxy"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_docker_client.py -q`
Expected: 4 passed. This builds the image from the working tree, so it is the first run of a real client against this plan's code. If a client fails, the assertion message carries the end of its output.

- [ ] **Step 3: Document Docker proxies**

In `README.md`:

Replace

```markdown
  another repository (it is uploaded instead), and deleting a single layer. Proxy and
  group Docker repositories are not available yet.
```

with

```markdown
  another repository (it is uploaded instead), and deleting a single layer. Group
  Docker repositories are not available yet.
```

After

```markdown
- **Clients.** Tested with the Docker client and daemon, whose pushes and pulls go
  through containerd's registry client, and with skopeo, which is built on the image
  library Podman uses.
```

add

````markdown
A proxy is a pull-through cache of another registry:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-hub", "format": "docker", "type": "proxy",
  "proxy": {"remote_url": "https://registry-1.docker.io"}
}' http://localhost:8000/api/v1/repositories

docker pull repo.example.com/docker-hub/alpine:3
docker pull repo.example.com/docker-hub/grafana/grafana:latest
```

- **The remote address** is the registry's own, without `/v2/`: for Docker Hub
  `https://registry-1.docker.io` (not `docker.io` or `hub.docker.com`), or for example
  `https://ghcr.io`, `https://quay.io`, `https://registry.k8s.io`. On Docker Hub an
  image with a one-part name is an official image, so `alpine` is fetched as
  `library/alpine`, as Docker does.
- **Signing in to the remote.** Public registries hand out a token before they serve
  anything, usually from another host. The proxy fetches one, with the user name and
  password (or access token) in `remote_auth` if there is one, and uses it until it
  runs out. The credential is sent to the remote and to the sign-in address the remote
  names, never to the host its layers are downloaded from. A sign-in address must use
  HTTPS if the remote does, and must not be an internal address unless the remote is
  at that host.
- **A tag** is asked about again after `metadata_max_age_minutes`. Only its digest is
  asked for, which registries that count pulls do not count; the image is fetched
  again only if the tag names another one. While the remote cannot be reached, or if
  it has dropped the tag, what is held is served.
- **An image by its digest, and a layer,** are fetched once and checked against the
  digest. What does not match is not kept (`502`). They are never asked about again.
- **A manifest is read before it is kept**, so the proxy knows the layers each image
  uses. A layer that no kept manifest refers to is removed after a day, as on a hosted
  repository, and fetched again if it is asked for.
- **Tags** (`tags/list`) are the remote's, kept for `metadata_max_age_minutes`. The
  catalog lists the images that have been pulled through the proxy.
- An image the remote does not have, or will not show to the proxy's credential, is
  answered `404`. A registry says the same of both.
- Nothing can be pushed to a proxy or deleted from it through the registry API (`405`).
````

- [ ] **Step 4: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-11-docker-format-design.md`:

Replace

```markdown
- **A remote that asks for a token.** The remote client can answer a registry's `Bearer` challenge: fetch a token from the realm the challenge names, with the proxy's credentials if it has any, and repeat the request with it. Tokens are remembered until they expire. The rules of the PyPI design's D8 apply to the realm: it is an address the remote names.
- **What a request to a remote accepts.** A format can say which media types a fetch accepts, so that a manifest is fetched in the form it was pushed in.
```

with

```markdown
- **A remote that asks for a token.** The remote client can answer a registry's `Bearer` challenge: fetch a token from the realm the challenge names, with the proxy's credentials if it has any, and repeat the request with it. Tokens are remembered in memory until they expire, for at most an hour, and are never stored. The realm is an address the remote names, so the PyPI design's D8 applies to it in this form: it must not be an internal address unless the remote is at that host, and it must use HTTPS if the remote does. Unlike a file's address, it is given the credential, because it is where the remote says its users sign in; only a user name and password is sent there, never a stored bearer token. The host a blob is redirected to gets neither the credential nor the token.
- **What a request to a remote accepts.** A fetch can say which media types it accepts, so that a manifest is fetched in the form it was pushed in.
- **Asking without caching.** The proxy engine can fetch a small document into memory, or only ask about it, with everything it does for any fetch: the remote is not asked while it is blocked, a miss is remembered, a failure is recorded. The format reads the document and stores it itself. A miss need not be remembered, for a path that can be found at more than one address.
- **A cached file can record what it refers to**, like a stored one, before what it names has been fetched.
```

Replace

```markdown
**The remote.** A registry's address, such as `https://registry-1.docker.io` or `https://ghcr.io`. For Docker Hub, an image name with one component is asked for under `library/`, as Docker does. The remote's token sign-in is done by the remote client (section 4.2), with the proxy's configured credentials if it has any.

A manifest is stored with what it refers to, as on a hosted repository, so that maintenance treats cached blobs the same way.
```

with

```markdown
**The remote.** A registry's address, such as `https://registry-1.docker.io` or `https://ghcr.io`. For Docker Hub, an image name with one component is asked for under `library/`, as Docker does. The remote's token sign-in is done by the remote client (section 4.2), with the proxy's configured credentials if it has any.

A manifest is read before it is stored: what is not one of the four kinds, or is not the manifest whose digest was asked for, is not kept and is answered `502`. It is stored with what it refers to, as on a hosted repository, so that maintenance treats cached blobs the same way: a blob no kept manifest refers to is removed after a day, and fetched again when it is asked for.

**A tag** is refreshed by asking the remote about it (`HEAD`), which registries that count pulls do not count. If the digest it reports is the one held, nothing is fetched. A remote that reports no digest is asked for the manifest itself. While the remote cannot be asked, or once it has dropped the tag, what is held is served.

**A blob** is not remembered as missing: another image of the remote may have the one this image has not. `HEAD` for a blob that is not held asks the remote and fetches nothing.

**A refusal** (`401` or `403`) from the remote for an image is answered `404`: a registry says the same of an image it does not have as of one it will not show.

The remote's tag list is read page by page, up to 100 pages and 100,000 tags, and kept as one list under `lists/<image>`.
```

Replace

```markdown
  - *Plan 7b:* an image is pulled through a proxy of a public registry.
```

with

```markdown
  - *Plan 7b:* an image is pulled through a proxy of Docker Hub and run, and one through a proxy of registry.k8s.io; both are listed; with the remote blocked the image is pulled again from what was kept; a push to the proxy is refused.
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2279 passed, 1 skipped; no findings.

Run: `uv run pytest -m docker -q`
Expected: 20 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_docker_client.py README.md docs/superpowers/specs/2026-10-11-docker-format-design.md
git commit -m "test(docker): pull through proxies of Docker Hub and registry.k8s.io; document Docker proxies"
```

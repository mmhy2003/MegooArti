"""An in-process stand-in for a remote repository. No test touches the network."""

import asyncio
import hashlib
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from megooarti.repositories.remote import new_client

MODIFIED = "Fri, 02 Jan 2026 03:04:05 GMT"


def etag_of(content: bytes) -> str:
    return '"' + hashlib.md5(content).hexdigest() + '"'


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, remote: "FakeRemote") -> None:
        self._remote = remote
        self._inner = httpx.ASGITransport(app=remote.app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._remote.down:
            raise httpx.ConnectError("connection refused", request=request)
        return await self._inner.handle_async_request(request)


class FakeRemote:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.requests: list[dict] = []
        self.status: int | None = None
        self.declared_extra = 0
        self.redirect_to: str | None = None
        self.down = False
        self.delay = 0.0
        self.app = Starlette(routes=[Route("/{path:path}", self._serve, methods=["GET"])])

    def client(self) -> httpx.AsyncClient:
        return new_client(transport=_Transport(self))

    def paths(self, method: str = "GET") -> list[str]:
        return [seen["path"] for seen in self.requests if seen["method"] == method]

    async def _serve(self, request: Request) -> Response:
        self.requests.append(
            {
                "method": request.method,
                "host": request.url.hostname,
                "path": request.url.path,
                "headers": dict(request.headers),
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.status is not None:
            return Response(status_code=self.status)
        if self.redirect_to and request.url.hostname != urlsplit(self.redirect_to).hostname:
            return RedirectResponse(self.redirect_to + request.url.path, status_code=302)
        content = self.files.get(request.url.path.lstrip("/"))
        if content is None:
            return Response(status_code=404)
        etag = etag_of(content)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304)
        headers = {
            "ETag": etag,
            "Last-Modified": MODIFIED,
            "Content-Type": "application/x-remote",
            "Content-Length": str(len(content) + self.declared_extra),
        }
        return Response(b"" if request.method == "HEAD" else content, headers=headers)

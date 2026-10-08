"""Talking to a proxy repository's remote.

Every outcome is a value, not an exception, so the proxy engine decides what a failure
means: serve a cached copy, answer 404, or count it towards blocking the remote.
"""

import base64
import ipaddress
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any

import httpx

from megooarti import __version__
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.secrets_box import unseal
from megooarti.storage.backends import StagedBlob

# Receives the body and the size the remote declared, if any; returns it staged.
Stage = Callable[[AsyncIterator[bytes], int | None], Awaitable[StagedBlob]]

# What a HEAD answer passes on to the client.
_HEAD_HEADERS = ("Content-Length", "Content-Type", "Last-Modified", "ETag")


@dataclass(frozen=True)
class Fetched:
    staged: StagedBlob
    content_type: str | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class NotModified:
    pass


@dataclass(frozen=True)
class Missing:
    pass


@dataclass(frozen=True)
class Failed:
    reason: str
    blockable: bool  # counts towards blocking the remote


@dataclass(frozen=True)
class Exists:
    headers: dict[str, str]


class _NoCookies(CookieJar):
    """A cookie jar that keeps nothing.

    One client serves every proxy repository. A session cookie a remote sets on an
    authenticated request must not be replayed on a request that has no credential,
    or after the credential was removed.
    """

    def extract_cookies(self, response: Any, request: Any) -> None:
        return None

    def set_cookie(self, cookie: Any) -> None:
        return None


class InwardRedirect(httpx.RequestError):
    """A remote on a public address redirected to an internal one."""


def _is_internal(host: str) -> bool:
    """Whether a host is a loopback, link-local or private address, written as one.

    Names are not resolved, so a name that resolves to an internal address is not
    caught here; network-level egress rules are the complete defence.
    """
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_link_local or address.is_private


async def _refuse_inward_redirects(response: httpx.Response) -> None:
    # Whoever runs a remote can answer with a redirect. Without this, that would let
    # them aim the server at, say, a cloud metadata address and read the answer back.
    if not response.has_redirect_location:
        return
    here = response.request.url
    there = here.join(response.headers["Location"])
    if _is_internal(there.host) and not _is_internal(here.host):
        raise InwardRedirect("redirect to an internal address", request=response.request)


def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,  # httpx drops Authorization when the host changes
        max_redirects=5,
        timeout=httpx.Timeout(60.0, connect=10.0),
        headers={"User-Agent": f"MegooArti/{__version__}"},
        cookies=_NoCookies(),
        event_hooks={"response": [_refuse_inward_redirects]},
    )


def client_of(app: Any) -> httpx.AsyncClient:
    """The application's one outbound client, built the first time it is needed.

    Building it loads the system's TLS trust store, which takes a noticeable fraction
    of a second: too slow to do for every application start that never proxies.
    """
    if app.state.http is None:
        app.state.http = new_client()
    return app.state.http


def authorization(settings: Settings, remote_auth: dict[str, Any]) -> str | None:
    """The Authorization header for a stored credential. Raises SecretUnreadable."""
    kind = remote_auth.get("type", "none")
    if kind == "none":
        return None
    secret = unseal(settings, remote_auth["secret"])
    if kind == "bearer":
        return f"Bearer {secret}"
    pair = f"{remote_auth['username']}:{secret}".encode()
    return f"Basic {base64.b64encode(pair).decode()}"


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


# Answers that say the remote as a whole is struggling. A plain 500 is not among them:
# it is usually one broken path, and must not block every other path.
_REMOTE_IN_TROUBLE = frozenset({429, 502, 503, 504})


def _unexpected(status: int) -> Failed:
    return Failed(f"the remote answered {status}", blockable=status in _REMOTE_IN_TROUBLE)


def _unrequestable(error: Exception) -> Failed:
    """A request that could not even be sent: a bad URL, or a header that cannot exist."""
    if isinstance(error, InwardRedirect):
        return Failed("the remote redirected to an internal address", blockable=False)
    return Failed(f"the request could not be made ({type(error).__name__})", blockable=False)


def _declared_size(response: httpx.Response) -> int | None:
    value = response.headers.get("Content-Length", "")
    plain = value.isascii() and value.isdigit() and len(value) <= 18
    return int(value) if plain else None


async def download(
    client: httpx.AsyncClient,
    url: str,
    *,
    authorization: str | None,
    stage: Stage,
    etag: str | None = None,
    last_modified: str | None = None,
) -> Fetched | NotModified | Missing | Failed:
    """Fetch a file completely, or learn that it is unchanged, absent or unavailable."""
    headers = _request_headers(authorization, etag, last_modified)
    try:
        async with client.stream("GET", url, headers=headers) as response:
            status = response.status_code
            if status == 304:
                return NotModified()
            if status in (404, 410):
                return Missing()
            if status != 200:
                return _unexpected(status)
            encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
            if encoding != "identity":
                # Asked for the bytes as stored, it compressed them anyway. Storing that
                # would serve a compressed file under the original name and type.
                return Failed("the remote sent an encoded body", blockable=False)
            try:
                staged = await stage(response.aiter_raw(), _declared_size(response))
            except ApiError:  # not the number of bytes the remote declared
                return Failed("the remote sent an incomplete file", blockable=True)
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

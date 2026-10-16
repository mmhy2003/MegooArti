"""Talking to a proxy repository's remote.

Every outcome is a value, not an exception, so the proxy engine decides what a failure
means: serve a cached copy, answer 404, or count it towards blocking the remote.
"""

import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import socket
import time
import weakref
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
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

# A connection that could not be made is tried again before it is called a failure, and
# this is how long is waited before each further try. Nothing was sent, so nothing is
# repeated; and one connection that a network dropped is not an outage, though behind
# a group it would be answered as "not there".
CONNECT_WAITS = (0.2, 1.0)


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
    """Whether a host is an address that is not on the public internet, however written.

    A resolver reads `2130706433`, `0x7f000001` and `127.1` as 127.0.0.1, so those
    count as it does. Names are not resolved, so a name that resolves to an internal
    address is not caught here; network-level egress rules are the complete defence.
    """
    host = host.lower().removesuffix(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            # The other ways to write an IPv4 address, as a resolver reads them.
            address = ipaddress.ip_address(socket.inet_aton(host))
        except (OSError, ValueError):
            return False
    address = getattr(address, "ipv4_mapped", None) or address
    return not address.is_global


async def _refuse_inward_redirects(response: httpx.Response) -> None:
    # Whoever runs a remote can answer with a redirect. Without this, that would let
    # them aim the server at, say, a cloud metadata address and read the answer back.
    if not response.has_redirect_location:
        return
    here = response.request.url
    there = here.join(response.headers["Location"])
    if _is_internal(there.host) and not _is_internal(here.host):
        raise InwardRedirect("redirect to an internal address", request=response.request)


def _origin(address: httpx.URL) -> tuple[str, str, int | None]:
    port = address.port or {"http": 80, "https": 443}.get(address.scheme)
    return address.scheme, address.host.lower(), port


def same_origin(first: str, second: str) -> bool:
    """Whether two addresses have the same scheme, host and port."""
    try:
        return _origin(httpx.URL(first)) == _origin(httpx.URL(second))
    except httpx.InvalidURL:
        return False


def refusal(remote_url: str, address: str) -> str | None:
    """Why an address that a remote's own content points at is not fetched, or None.

    A page a remote serves can name any address. One on a loopback, link-local or
    private network is refused unless the remote itself is at that host: the remote
    must not be able to make this server read from the network it is on.
    """
    try:
        target, configured = httpx.URL(address), httpx.URL(remote_url)
    except httpx.InvalidURL:
        return "it points at an address that cannot be read"
    if target.scheme not in ("http", "https") or not target.host:
        return "it points at an address that is not HTTP"
    if _is_internal(target.host) and target.host.lower() != configured.host.lower():
        return "it points at an internal address"
    return None


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


# Answers that say the remote as a whole is struggling. A plain 500 is not among them:
# it is usually one broken path, and must not block every other path.
_REMOTE_IN_TROUBLE = frozenset({429, 502, 503, 504})


def _unexpected(status: int) -> Failed:
    return Failed(
        f"the remote answered {status}", blockable=status in _REMOTE_IN_TROUBLE, status=status
    )


def _unrequestable(error: Exception) -> Failed:
    """A request that could not even be sent: a bad URL, or a header that cannot exist."""
    if isinstance(error, InwardRedirect):
        return Failed("the remote redirected to an internal address", blockable=False)
    return Failed(f"the request could not be made ({type(error).__name__})", blockable=False)


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


def _mark(remote_url: str, authorization: str | None) -> str:
    """What a token is kept under besides its challenge: whose it is.

    The remote is part of it. Two remotes may name one sign-in address, and each has
    to sign in for itself, because the rules about that address depend on the remote.
    """
    return hashlib.sha256(f"{remote_url}\n{authorization or ''}".encode()).hexdigest()


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
    # identity: the answer is read as it arrives, like everything else fetched here.
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if authorization and authorization.startswith("Basic "):
        # The remote named this address as the place its users sign in.
        headers["Authorization"] = authorization
    response = await _send(
        client,
        lambda: client.build_request(
            "GET",
            challenge.realm,
            params={name: value for name, value in wanted.items() if value},
            headers=headers,
        ),
    )
    try:
        if response.status_code in (401, 403):
            # No status: this is not the remote's answer about what was asked for, and
            # must not be taken for "you may not see this".
            reason = "its sign-in address refused the credential"
            raise _SignInFailed(Failed(reason, blockable=False))
        if response.status_code != 200:
            failed = _unexpected(response.status_code)
            reason = f"its sign-in address answered {response.status_code}"
            raise _SignInFailed(Failed(reason, failed.blockable, failed.status))
        encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
        if encoding != "identity":
            reason = "its sign-in address sent an encoded answer"
            raise _SignInFailed(Failed(reason, blockable=False))
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


def _gunzip(data: bytes, limit: int) -> bytes | None:
    """A gzipped body inflated, or None if it is longer than `limit` or not gzip."""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        inflated = inflater.decompress(data, limit + 1)
    except zlib.error:
        return None
    return None if len(inflated) > limit or not inflater.eof else inflated


async def _read(response: httpx.Response, limit: int) -> bytes | None:
    """The body, or None if it is longer than `limit`."""
    received = bytearray()
    async for chunk in response.aiter_raw():
        received += chunk
        if len(received) > limit:
            return None
    return bytes(received)


async def _send(client: httpx.AsyncClient, build: Callable[[], httpx.Request]) -> httpx.Response:
    """Send a request and return the answer with its body unread.

    A connection that could not be made is tried again (CONNECT_WAITS). Not one that
    took too long to make: that has waited already. And not a request whose answer
    failed: the remote has seen it. Where the remote answered with a redirect and the
    host it named took no connection, the whole is asked again, the first request with
    it: these are requests to read, which may be made twice.
    """
    for wait in (*CONNECT_WAITS, None):
        try:
            return await client.send(build(), stream=True)
        except httpx.ConnectError:
            if wait is None:
                raise
            await asyncio.sleep(wait)
    raise AssertionError("the last try answers or raises")


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
        return await _send(client, lambda: client.build_request(method, url, headers=sent))

    if sign_in is None:
        return await send(authorization)
    memory = _memories.setdefault(client, _Memory())
    mark = _mark(sign_in.remote_url, authorization)
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
    gzipped: bool = False,
) -> Document | Missing | Failed:
    """Fetch a small document into memory. One longer than `limit` is a failure.

    With `gzipped`, a body the remote sends gzipped whatever it is asked for (as
    nuget.org sends its registrations) is inflated, to the same `limit`.
    """
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
            if encoding not in ("identity", "gzip") or (encoding == "gzip" and not gzipped):
                return Failed("the remote sent an encoded body", blockable=False)
            body = await _read(response, limit)
            if body is not None and encoding == "gzip":
                body = _gunzip(body, limit)
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

"""Who a request comes from, behind proxies (spec 8).

A request reaches the backend from the gateway (or a proxy of the installation's own, in
its place: the addresses of `MEGOOARTI_FORWARDED_ALLOW_IPS`), which may have it from other
proxies an administrator trusts (the `trusted_proxies` setting). `X-Forwarded-For` is read
from the right, past every trusted proxy: the first address that is not one is the
client's. What is left of it was written by the client, and is never believed.

The request's `client` is that address, for throttling, sessions and the log, and
`state.proxied` says whether a proxy the administrator trusts passed it on: a trusted
header (a header source's) is taken only then.
"""

import ipaddress
from collections.abc import Callable, Sequence

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
_SCHEMES = {"http", "https"}
UNKNOWN = "unknown"


def networks(entries: Sequence[str], *, strict: bool = False) -> list[Network]:
    """Addresses and networks (CIDR), as they are written: a bare address is a network
    of one. Raises ValueError for one that is neither, and, if strict, for a network
    with bits set past its prefix (`10.0.0.5/3`: a mistyped `/32`, not `0.0.0.0/3`)."""
    return [ipaddress.ip_network(entry.strip(), strict=strict) for entry in entries]


def address(hop: str) -> str | None:
    """An address as a proxy writes it, without a port: None for what is not one."""
    hop = hop.strip()
    if hop.startswith("["):  # [2001:db8::1]:443
        hop = hop[1 : hop.find("]")] if "]" in hop else ""
    elif hop.count(":") == 1:  # 203.0.113.7:51234
        hop = hop.split(":")[0]
    try:
        return str(ipaddress.ip_address(hop))
    except ValueError:
        return None


def _within(hop: str | None, among: Sequence[Network]) -> bool:
    if hop is None:
        return False
    found = ipaddress.ip_address(hop)
    return any(found in network for network in among)


class Deployment:
    """The addresses that reach the backend directly and are believed: the gateway's."""

    def __init__(self, allowed: str) -> None:
        entries = [entry.strip() for entry in allowed.split(",") if entry.strip()]
        self.anyone = "*" in entries
        self.networks = networks([entry for entry in entries if entry != "*"])

    def trusts(self, peer: str | None) -> bool:
        return peer is not None and (self.anyone or _within(peer, self.networks))


def resolve(
    peer: str | None, forwarded: Sequence[str], deployment: Deployment, proxies: Sequence[Network]
) -> tuple[str, bool]:
    """The client's address, and whether a proxy the administrator trusts passed it on.

    `forwarded` is `X-Forwarded-For`'s addresses, as written (the client's first). The
    peer is believed as the deployment's, or as a trusted proxy; every address before it
    only as a trusted proxy."""
    hops = [peer, *(address(hop) for hop in reversed(forwarded))]
    client, proxied = peer, False
    for index, hop in enumerate(hops):
        if hop is None:  # no peer, or what is not an address where one should be
            return UNKNOWN, proxied
        by_deployment = index == 0 and deployment.trusts(hop)
        by_administrator = _within(hop, proxies)
        if not (by_deployment or by_administrator):
            return hop, proxied
        # The deployment's own peer (the gateway) passes on what it saw, even when the
        # administrator's list covers it too: only a proxy past it says who signed in.
        proxied = proxied or (by_administrator and not by_deployment)
        client = hop
    return client or UNKNOWN, proxied  # all of them trusted: the furthest is the client


class ProxiesMiddleware:
    """Sets the request's client (and scheme) from what trusted proxies say of it."""

    def __init__(
        self, app: ASGIApp, *, deployment: str, proxies: Callable[[], Sequence[Network]]
    ) -> None:
        self.app = app
        self.deployment = Deployment(deployment)
        self.proxies = proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        forwarded = [
            hop
            for value in headers.getlist("x-forwarded-for")
            for hop in value.split(",")
            if hop.strip()
        ]
        peer = address(scope["client"][0]) if scope.get("client") else None
        proxies = self.proxies()
        client, proxied = resolve(peer, forwarded, self.deployment, proxies)
        believed = self.deployment.trusts(peer) or _within(peer, proxies)
        scope["client"] = (client, 0)
        scope.setdefault("state", {})["proxied"] = proxied
        scheme = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if believed and scheme in _SCHEMES:
            scope["scheme"] = scheme if scope["type"] == "http" else scheme.replace("http", "ws")
        await self.app(scope, receive, send)

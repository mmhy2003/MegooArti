"""The interface every package format implements, and the registry of formats.

The base class is complete, generic, path-addressed behaviour. A format subclasses it,
sets `name`, and overrides only what differs. Formats never touch tables or files:
they work through the repository context they are handed.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError

if TYPE_CHECKING:
    from megooarti.repositories.content import RepositoryContext

# The dispatcher, as an engine sees it: answer this request from that repository.
Serve = Callable[["RepositoryContext", Request, str], Awaitable[Response]]

_CHECKSUM_HEADERS = {
    "md5": "X-Checksum-Md5",
    "sha1": "X-Checksum-Sha1",
    "sha256": "X-Checksum-Sha256",
}


@dataclass(frozen=True)
class ComponentKey:
    """What identifies a component (a package) inside a repository."""

    namespace: str
    name: str
    version: str = ""


def _declared_size(request: Request) -> int | None:
    value = request.headers.get("Content-Length", "")
    plain = value.isascii() and value.isdigit() and len(value) <= 18
    return int(value) if plain else None


def _declared_hashes(request: Request) -> dict[str, str]:
    return {
        algorithm: request.headers[header]
        for algorithm, header in _CHECKSUM_HEADERS.items()
        if header in request.headers
    }


class Format:
    name: str = ""
    types: frozenset[str] = frozenset({"hosted", "proxy", "group"})

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Check and return this format's own settings. The generic format has none.

        `current` is what is stored, on an update, so a format can refuse a change.
        """
        if config:
            details = [
                {"field": "format_config", "message": f"The {self.name} format has no settings."}
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        return {}

    def describe_component(self, path: str) -> ComponentKey | None:
        """Which component a stored path belongs to: the file, in its directory.

        A format returns None for a file that belongs to no package.
        """
        directory, _, filename = path.rpartition("/")
        return ComponentKey(namespace=directory, name=filename)

    def content_type(self, path: str, declared: str | None) -> str | None:
        """The content type to record for a file: an upload, or one a proxy fetched.

        The generic format trusts what the client or the remote declared.
        """
        return declared

    def remote_url(self, base: str, path: str) -> str:
        """Where a proxy repository finds a path on its remote."""
        return f"{base.rstrip('/')}/{quote(path, safe='/')}"

    def is_metadata(self, path: str) -> bool:
        """Whether a path is an index that changes as packages are published.

        Metadata is revalidated on `metadata_max_age_minutes`; everything else on
        `content_max_age_minutes`. The generic format has no metadata.
        """
        return False

    async def handle_hosted(
        self, context: "RepositoryContext", request: Request, path: str
    ) -> Response:
        """Answer a request to a hosted repository. The route has checked `read`.

        A handler does not commit. The route commits once the handler returns, and
        nothing is kept if it raises.
        """
        if request.method in ("GET", "HEAD"):
            return await context.respond(path, request)
        if request.method == "PUT":
            _, created = await context.put(
                path,
                request.stream(),
                content_type=self.content_type(path, request.headers.get("Content-Type")),
                expected_size=_declared_size(request),
                expected_hashes=_declared_hashes(request),
            )
            return Response(status_code=201 if created else 204)
        if request.method == "DELETE":
            if not await context.delete(path):
                raise ApiError(404, "not_found", "No such file.")
            return Response(status_code=204)
        raise ApiError(
            405,
            "method_not_allowed",
            "This repository accepts GET, HEAD, PUT and DELETE.",
            headers={"Allow": "GET, HEAD, PUT, DELETE"},
        )

    async def handle_proxy(
        self, context: "RepositoryContext", request: Request, path: str
    ) -> Response:
        """Answer a request to a proxy repository. The route has checked `read`.

        The generic engine: fetch from the remote on a miss, cache, and keep serving.
        """
        # Imported here: the engine is written against this module, so a top-level
        # import would be circular.
        from megooarti.repositories import proxy

        return await proxy.handle_proxy(context, request, path)

    async def handle_group(
        self, context: "RepositoryContext", request: Request, path: str, serve: Serve
    ) -> Response:
        """Answer a request to a group. `serve` is the dispatcher, for asking a member.

        The generic engine: the first member, in order, that has the path.
        """
        from megooarti.repositories import group

        return await group.handle_group(context, request, path, serve)


_registry: dict[str, Format] = {}


def register(format: Format) -> None:
    if not format.name:
        raise ValueError("a format needs a name before it can be registered")
    _registry[format.name] = format


def get_format(name: str) -> Format | None:
    return _registry.get(name)


def format_names() -> list[str]:
    return sorted(_registry)

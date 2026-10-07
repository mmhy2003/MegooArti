"""The interface every package format implements, and the registry of formats.

The base class is complete, generic, path-addressed behaviour. A format subclasses it,
sets `name`, and overrides only what differs. Formats never touch tables or files:
they work through the repository context they are handed.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError

if TYPE_CHECKING:
    from megooarti.repositories.content import RepositoryContext

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
    return int(value) if value.isdigit() else None


def _declared_hashes(request: Request) -> dict[str, str]:
    return {
        algorithm: request.headers[header]
        for algorithm, header in _CHECKSUM_HEADERS.items()
        if header in request.headers
    }


class Format:
    name: str = ""
    types: frozenset[str] = frozenset({"hosted", "proxy", "group"})

    def validate_config(self, repository_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """Check and return this format's own settings. The generic format has none."""
        if config:
            details = [
                {"field": "format_config", "message": f"The {self.name} format has no settings."}
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        return {}

    def describe_component(self, path: str) -> ComponentKey:
        """Which component a stored path belongs to: the file, in its directory."""
        directory, _, filename = path.rpartition("/")
        return ComponentKey(namespace=directory, name=filename)

    async def handle_hosted(
        self, context: "RepositoryContext", request: Request, path: str
    ) -> Response:
        """Answer a request to a hosted repository. The route has checked `read`."""
        if request.method in ("GET", "HEAD"):
            return await context.respond(path, request)
        if request.method == "PUT":
            _, created = await context.put(
                path,
                request.stream(),
                content_type=request.headers.get("Content-Type"),
                expected_size=_declared_size(request),
                expected_hashes=_declared_hashes(request),
            )
            await context.db.commit()
            return Response(status_code=201 if created else 204)
        if request.method == "DELETE":
            if not await context.delete(path):
                raise ApiError(404, "not_found", "No such file.")
            await context.db.commit()
            return Response(status_code=204)
        raise ApiError(
            405,
            "method_not_allowed",
            "This repository accepts GET, HEAD, PUT and DELETE.",
            headers={"Allow": "GET, HEAD, PUT, DELETE"},
        )


_registry: dict[str, Format] = {}


def register(format: Format) -> None:
    if not format.name:
        raise ValueError("a format needs a name before it can be registered")
    _registry[format.name] = format


def get_format(name: str) -> Format | None:
    return _registry.get(name)


def format_names() -> list[str]:
    return sorted(_registry)

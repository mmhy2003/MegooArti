"""The Maven format: the Maven 2 layout, with generated checksums and metadata.

This is the only Maven module that touches the repository context. What it decides
about a path comes from the pure functions beside it.
"""

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.maven import paths
from megooarti.repositories.paths import normalise_path

_SETTINGS = ("version_policy", "layout_policy")


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": f"format_config.{field}", "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _choice(config: dict[str, Any], field: str, choices: tuple[str, ...], default: str) -> str:
    value = config.get(field, default)
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field, f"Must be one of: {', '.join(choices)}.")
    return value


def _check_policies(settings: dict[str, Any], parsed: paths.MavenPath) -> None:
    """Refuse an upload to a path this repository does not take.

    Checked for uploads only. What is already stored stays readable and deletable,
    so a repository can be made strict without stranding files.
    """
    if parsed.kind == "other" and settings["layout_policy"] == "strict":
        raise ApiError(
            400, "invalid_path", "The path is not valid: it is not in the Maven repository layout."
        )
    if not paths.allowed_by(settings["version_policy"], parsed):
        accepted = settings["version_policy"]
        raise ApiError(
            400, "version_policy_violation", f"This repository takes {accepted} versions only."
        )


class MavenFormat(Format):
    name = "maven"
    # Proxy and group repositories need Maven's own handling of checksums and metadata.
    types = frozenset({"hosted"})

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        unknown = sorted(set(config) - set(_SETTINGS))
        if unknown:
            raise _invalid(unknown[0], "Maven repositories have no such setting.")
        stored = (current or {}).get("version_policy")
        version_policy = _choice(
            config, "version_policy", paths.VERSION_POLICIES, stored or "release"
        )
        if stored is not None and version_policy != stored:
            # Changing it would leave content the repository refuses to take or list.
            raise ApiError(409, "immutable", "A repository's version policy cannot be changed.")
        return {
            "version_policy": version_policy,
            "layout_policy": _choice(config, "layout_policy", paths.LAYOUT_POLICIES, "strict"),
        }

    def describe_component(self, path: str) -> ComponentKey | None:
        """An artifact file belongs to its group, artifact and version. Nothing else does."""
        parsed = paths.classify(path)
        if parsed.kind != "artifact":
            return None
        return ComponentKey(parsed.group_id, parsed.artifact_id, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        # Maven clients rarely declare a type, and never a useful one.
        return paths.content_type(path) or declared

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        parsed = paths.classify(path)
        if request.method == "PUT":
            _check_policies(context.repository.config["format_config"], parsed)
        return await super().handle_hosted(context, request, path)


register(MavenFormat())

"""The Maven format: the Maven 2 layout, with generated checksums and metadata.

This is the only Maven module that touches the repository context. What it decides
about a path comes from the pure functions beside it.
"""

import hashlib
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.maven import checksums, metadata, paths
from megooarti.repositories.paths import normalise_path

log = structlog.get_logger(__name__)

_SETTINGS = ("version_policy", "layout_policy")
# The most that is read into memory: of an upload, and of the record the server keeps.
METADATA_LIMIT = 1024 * 1024
STORED_LIMIT = 4 * 1024 * 1024
_XML = "application/xml"


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


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


async def _digest(
    context: RepositoryContext, target: str, parsed: paths.MavenPath, algorithm: str
) -> tuple[str, datetime] | None:
    """The checksum of what a GET of `target` returns, and when that last changed."""
    if parsed.is_metadata:
        found = await document(context, target, parsed)
        if found is None:
            return None
        data, modified = found
        return hashlib.new(algorithm, data).hexdigest(), modified
    stored = await context.stat(target)
    if stored is None:
        return None
    return getattr(stored, algorithm), stored.modified


async def _plugins(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[tuple[metadata.Plugin, ...], datetime | None]:
    """The plugin entries kept for a group that still have a file, and when they changed."""
    if not parsed.plugin_group:
        return (), None
    stored = await context.stat(path)
    if stored is None or stored.kind != "metadata":
        return (), None
    try:
        record = metadata.parse(await context.read(path, limit=STORED_LIMIT) or b"")
    except (metadata.InvalidMetadata, TooLarge) as error:
        log.warning(
            "plugin_record_unreadable",
            repository=context.repository.name,
            path=path,
            reason=type(error).__name__,
        )
        return (), None
    present = await context.names(
        parsed.plugin_group, [plugin.artifact_id for plugin in record.plugins]
    )
    kept = tuple(plugin for plugin in record.plugins if plugin.artifact_id in present)
    return kept, stored.modified if kept else None


async def document(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[bytes, datetime] | None:
    """The metadata a GET of `path` returns now, and when it last changed.

    Built from the files the repository holds, so it is right after a delete and after
    two deploys at once. None when there is nothing to list.
    """
    if parsed.kind == "snapshot_metadata":
        entries = await context.files(parsed.group_id, parsed.artifact_id, parsed.version)
        built = metadata.for_snapshot(
            parsed.group_id,
            parsed.artifact_id,
            parsed.version,
            [(paths.classify(entry.path), entry.modified) for entry in entries],
        )
        changes = [entry.modified for entry in entries]
    else:
        versions = {}
        if parsed.artifact_id:
            versions = await context.versions(parsed.group_id, parsed.artifact_id)
        plugins, plugins_changed = await _plugins(context, path, parsed)
        built = metadata.for_artifact(parsed.group_id, parsed.artifact_id, versions, plugins)
        changes = [*versions.values(), *([plugins_changed] if plugins_changed else [])]
    if built is None:
        return None
    return metadata.serialise(built), max(changes)


async def keep_plugins(
    context: RepositoryContext, path: str, group_id: str, uploaded: Iterable[metadata.Plugin]
) -> None:
    """Merge uploaded plugin entries into the record kept for a group.

    Only the plugin's jar knows its prefix, so this is the one part of uploaded
    metadata that cannot be derived and has to be kept.
    """
    uploaded = tuple(uploaded)

    async def merged(current: bytes | None) -> bytes | None:
        stored: tuple[metadata.Plugin, ...] = ()
        if current is not None:
            with suppress(metadata.InvalidMetadata):
                stored = metadata.parse(current).plugins
        plugins = metadata.merge_plugins(stored, uploaded)
        present = await context.names(group_id, [plugin.artifact_id for plugin in plugins])
        kept = tuple(plugin for plugin in plugins if plugin.artifact_id in present)
        return metadata.serialise(metadata.Metadata(plugins=kept)) if kept else None

    await context.maintain(path, merged, content_type=_XML, limit=STORED_LIMIT)


async def _metadata(
    context: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> Response:
    """Answer for a maven-metadata.xml path. The document is generated, never stored."""
    if request.method in ("GET", "HEAD"):
        found = await document(context, path, parsed)
        if found is None:
            raise _not_found()
        data, modified = found
        return context.respond_with(
            data,
            request,
            filename=paths.METADATA_FILE,
            content_type=_XML,
            last_modified=modified,
        )
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "Metadata is generated from the files stored. It can be read or uploaded, not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=METADATA_LIMIT)
    if body is None:
        raise ApiError(400, "invalid_metadata", "The metadata is larger than 1 MiB.")
    if parsed.kind == "metadata":
        try:
            uploaded = metadata.parse(body)
        except metadata.InvalidMetadata as error:
            raise ApiError(
                400, "invalid_metadata", f"The metadata cannot be read: {error}."
            ) from None
        if parsed.plugin_group and uploaded.plugins:
            await keep_plugins(context, path, parsed.plugin_group, uploaded.plugins)
    # Everything else a client puts in metadata is derived here from the files stored.
    return Response(status_code=201)


async def _checksum(
    context: RepositoryContext,
    request: Request,
    path: str,
    target: str,
    parsed: paths.MavenPath,
    algorithm: str,
) -> Response:
    """Answer for a checksum path. Checksums are computed, never stored."""
    if request.method in ("GET", "HEAD"):
        found = await _digest(context, target, parsed, algorithm)
        if found is None:
            raise _not_found()
        digest, modified = found
        return context.respond_with(
            digest.encode(),
            request,
            filename=path.rpartition("/")[2],
            content_type="text/plain",
            last_modified=modified,
        )
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "A checksum is computed from its file. It can be read or uploaded, not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=checksums.LIMIT)
    if parsed.is_metadata:
        # It cannot be checked: the client's document is not the one served.
        return Response(status_code=201)
    found = await _digest(context, target, parsed, algorithm)
    if found is None:
        raise ApiError(404, "not_found", "There is no file here for this checksum to belong to.")
    declared = None if body is None else checksums.read_uploaded(body, algorithm)
    if declared != found[0]:
        # Maven only warns when a checksum upload fails, so this log line is where a
        # corrupted deploy becomes visible.
        log.warning(
            "checksum_mismatch",
            repository=context.repository.name,
            path=target,
            algorithm=algorithm,
            by=context.principal.user.username,
        )
        # The file stays. Removing it would let anyone who may add delete files by
        # sending a wrong checksum; the client sees its deploy fail instead.
        raise ApiError(
            400, "checksum_mismatch", f"The {algorithm} checksum does not match the stored file."
        )
    return Response(status_code=201)


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
        # A checksum path is treated as the path it belongs to.
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if request.method == "PUT":
            _check_policies(context.repository.config["format_config"], parsed)
        if algorithm is not None:
            return await _checksum(context, request, path, target, parsed, algorithm)
        if parsed.is_metadata:
            return await _metadata(context, request, path, parsed)
        return await super().handle_hosted(context, request, path)


register(MavenFormat())

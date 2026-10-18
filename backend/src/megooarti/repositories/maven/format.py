"""The Maven format: the Maven 2 layout, with generated checksums and metadata.

This is the only Maven module that touches the repository context. What it decides
about a path comes from the pure functions beside it.

Building, merging, reading and writing metadata is CPU-bound work whose size a remote
decides. It runs on two worker threads of its own, with the database connection given
back first, so a long list of versions queues behind other metadata and not in front
of everything else.
"""

import asyncio
import hashlib
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import group, proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    Usage,
    invalid_upload,
    plain,
    register,
)
from megooarti.repositories.forms import UploadForm
from megooarti.repositories.maven import checksums, metadata, paths, upload, versions
from megooarti.repositories.paths import normalise_path

log = structlog.get_logger(__name__)

_SETTINGS = ("version_policy", "layout_policy")
# The most that is read into memory: of an upload, and of a stored or cached document.
METADATA_LIMIT = 1024 * 1024
STORED_LIMIT = 4 * 1024 * 1024
_XML = "application/xml"
# Not the default executor: that one also reads and writes blobs and checks passwords.
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="maven-metadata")


async def off_loop[T](function: Callable[..., T], *arguments: Any) -> T:
    """Run metadata work in a worker thread, at most two at a time."""
    return await asyncio.get_running_loop().run_in_executor(_workers, function, *arguments)


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": f"format_config.{field}", "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _choice(config: dict[str, Any], field: str, choices: tuple[str, ...], default: str) -> str:
    value = config.get(field, default)
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field, f"Must be one of: {', '.join(choices)}.")
    return value


def _excluded(settings: dict[str, Any], parsed: paths.MavenPath) -> ApiError | None:
    """Why this repository does not take such a path: the error an upload gets, or None.

    It governs what is added, not what is served. What is already stored or cached
    stays readable, so a repository can be made strict without stranding files.
    """
    if parsed.kind == "other" and settings["layout_policy"] == "strict":
        return ApiError(
            400, "invalid_path", "The path is not valid: it is not in the Maven repository layout."
        )
    if not paths.allowed_by(settings["version_policy"], parsed):
        accepted = settings["version_policy"]
        return ApiError(
            400, "version_policy_violation", f"This repository takes {accepted} versions only."
        )
    return None


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


def _checksum_response(
    context: RepositoryContext, request: Request, path: str, digest: str, modified: datetime
) -> Response:
    """A checksum file's content: the digest in lower-case hex, and nothing else."""
    return context.respond_with(
        digest.encode(),
        request,
        filename=path.rpartition("/")[2],
        content_type="text/plain",
        last_modified=modified,
    )


def _metadata_response(
    context: RepositoryContext, request: Request, data: bytes, modified: datetime
) -> Response:
    return context.respond_with(
        data,
        request,
        filename=paths.METADATA_FILE,
        content_type=_XML,
        last_modified=modified,
    )


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
        data = await context.read(path, limit=STORED_LIMIT)
        await context.release()
        record = await off_loop(metadata.parse, data or b"")
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


async def built(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """A hosted repository's metadata for `path`, and when it last changed.

    Built from the files the repository holds, so it is right after a delete and after
    two deploys at once. None when there is nothing to list.
    """
    if parsed.kind == "snapshot_metadata":
        entries = await context.files(parsed.group_id, parsed.artifact_id, parsed.version)
        files = [(paths.classify(entry.path), entry.modified) for entry in entries]
        await context.release()
        made = await off_loop(
            metadata.for_snapshot, parsed.group_id, parsed.artifact_id, parsed.version, files
        )
        changes = [entry.modified for entry in entries]
    else:
        versions = {}
        if parsed.artifact_id:
            versions = await context.versions(parsed.group_id, parsed.artifact_id)
        plugins, plugins_changed = await _plugins(context, path, parsed)
        await context.release()
        made = await off_loop(
            metadata.for_artifact, parsed.group_id, parsed.artifact_id, versions, plugins
        )
        changes = [*versions.values(), *([plugins_changed] if plugins_changed else [])]
    if made is None:
        return None
    return made, max(changes)


async def document(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[bytes, datetime] | None:
    """The metadata a GET of `path` on a hosted repository returns now, as bytes."""
    found = await built(context, path, parsed)
    if found is None:
        return None
    made, modified = found
    return await off_loop(metadata.serialise, made), modified


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
                stored = (await off_loop(metadata.parse, current)).plugins
        plugins = metadata.merge_plugins(stored, uploaded)
        present = await context.names(group_id, [plugin.artifact_id for plugin in plugins])
        kept = tuple(plugin for plugin in plugins if plugin.artifact_id in present)
        return metadata.serialise(metadata.Metadata(plugins=kept)) if kept else None

    await context.maintain(path, merged, content_type=_XML, limit=STORED_LIMIT)


async def _metadata(
    context: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> Response:
    """Answer for a maven-metadata.xml path on a hosted repository.

    The document is generated, never stored.
    """
    if request.method in ("GET", "HEAD"):
        found = await document(context, path, parsed)
        if found is None:
            raise _not_found()
        return _metadata_response(context, request, *found)
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
            uploaded = await off_loop(metadata.parse, body)
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
    """Answer for a checksum path on a hosted repository. Checksums are never stored."""
    if request.method in ("GET", "HEAD"):
        found = await _digest(context, target, parsed, algorithm)
        if found is None:
            raise _not_found()
        return _checksum_response(context, request, path, *found)
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
        # sending a wrong checksum.
        raise ApiError(
            400, "checksum_mismatch", f"The {algorithm} checksum does not match the stored file."
        )
    return Response(status_code=201)


async def _cached_by(
    member: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """The metadata a proxy has for `path`, fetched if need be, as a model."""
    settings = member.repository.config["format_config"]
    if _excluded(settings, parsed) is not None and await member.stat(path) is None:
        return None
    try:
        await proxy.ensure_cached(member, path)
    except ApiError as error:
        if error.status_code not in group.TRY_NEXT:
            raise
        return None
    stored = await member.stat(path)
    if stored is None:
        return None
    try:
        data = await member.read(path, limit=STORED_LIMIT)
        await member.release()
        held = await off_loop(metadata.parse, data or b"")
    except TooLarge:
        reason = "it is larger than 4 MiB"
    except metadata.InvalidMetadata as error:
        reason = str(error)
    else:
        return held, stored.modified
    # Logged, because the group still answers and nothing else would show it.
    log.warning(
        "member_metadata_unusable", repository=member.repository.name, path=path, reason=reason
    )
    return None


async def _held_by(
    member: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """What one member of a group has for a metadata path, or None if it has nothing.

    A member that cannot answer is left out, never an error: the group answers from
    the others.
    """
    kind = member.repository.type
    if kind == "hosted":
        return await built(member, path, parsed)
    if kind == "proxy":
        return await _cached_by(member, path, parsed)
    if kind == "group":
        return await _merged(member, request, path, parsed)
    return None


async def _merged(
    context: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """A group's metadata for `path`: every member's, as one document."""
    found = []
    for member in await group.member_contexts(context, request):
        held = await _held_by(member, request, path, parsed)
        if held is not None:
            found.append(held)
    if not found:
        return None
    await context.release()
    merged = await off_loop(metadata.merge, [held for held, _ in found])
    return merged, max(modified for _, modified in found)


def _kind(files: Sequence[str]) -> str:
    """What a build has to name to be given the artifact: nothing, for a jar."""
    kinds = {
        file.extension
        for file in map(paths.classify, files)
        if file.kind == "artifact" and not file.classifier
    }
    kinds = {kind for kind in kinds if not kind.endswith(".asc")}  # a signature is of a file
    if "jar" in kinds or not kinds:
        return ""
    # A POM and Gradle's module file describe the artifact. They are it only if alone.
    others = sorted(kinds - {"pom", "module"})
    return others[0] if others else "pom"


class MavenFormat(Format):
    name = "maven"

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if repository_type == "group":
            # A group holds nothing of its own, so it has no policy of its own.
            if config:
                raise _invalid(sorted(config)[0], "A Maven group has no settings.")
            return {}
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

    def default_deployment_policy(self, config: dict[str, Any]) -> str:
        """A release is deployed once: replaced, a build that used it cannot be repeated.

        A snapshot is replaced by its nature, and a mixed repository takes snapshots.
        """
        if config.get("version_policy") == "release":
            return "disable_redeploy"
        return "allow_redeploy"

    def describe_component(
        self, path: str, attributes: dict[str, Any] | None = None
    ) -> ComponentKey | None:
        """An artifact file belongs to its group, artifact and version. Nothing else does."""
        parsed = paths.classify(path)
        if parsed.kind != "artifact":
            return None
        return ComponentKey(parsed.group_id, parsed.artifact_id, parsed.version)

    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its coordinates, and the three of them as they are written in a build file."""
        together = f"{key.namespace}:{key.name}:{key.version}"
        return f"{super().search_text(key, attributes)} {together}"

    def ordered_versions(self, texts: Sequence[str]) -> list[str] | None:
        return versions.sorted_versions(texts)

    def is_prerelease(self, version: str) -> bool:
        return versions.is_prerelease(version)

    def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
        """A dependency, as Maven and Gradle write one. The repository is named elsewhere."""
        kind = _kind(files)
        if not plain(key.namespace, key.name, key.version) or (kind and not plain(kind)):
            return []
        lines = [
            f"  <groupId>{escape(key.namespace)}</groupId>",
            f"  <artifactId>{escape(key.name)}</artifactId>",
            f"  <version>{escape(key.version)}</version>",
            *([f"  <type>{escape(kind)}</type>"] if kind else []),
        ]
        dependency = "\n".join(["<dependency>", *lines, "</dependency>"])
        notation = f"{key.namespace}:{key.name}:{key.version}" + (f"@{kind}" if kind else "")
        return [
            Usage("Maven", "xml", dependency),
            Usage("Gradle (Kotlin)", "kotlin", f'implementation("{notation}")'),
            Usage("Gradle (Groovy)", "groovy", f"implementation '{notation}'"),
        ]

    def content_type(self, path: str, declared: str | None) -> str | None:
        # Maven clients rarely declare a type, and never a useful one.
        return paths.content_type(path) or declared

    async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
        """Store an artifact's files where its coordinates say, as a deploy would.

        Checksums and metadata are generated from what is stored, so there is nothing
        to write for them. A POM is written when the version would have none.
        """
        sent = [(file.field, file.filename) for file in form.files]
        try:
            planned = upload.plan(form.fields, sent)
        except upload.InvalidUpload as error:
            raise invalid_upload(error.field, str(error)) from None
        settings = context.repository.config["format_config"]
        for path in planned.paths:
            refusal = _excluded(settings, paths.classify(path))
            if refusal is not None:
                raise refusal
        stored = []
        for path, file in zip(planned.paths, form.files, strict=True):
            await context.store(path, file.staged, content_type=self.content_type(path, None))
            stored.append(path)
        if planned.pom is not None and await context.stat(planned.pom_path) is None:
            written = await context.stage_bytes(planned.pom)
            await context.store(planned.pom_path, written, content_type=_XML)
            stored.append(planned.pom_path)
        return stored

    def is_metadata(self, path: str) -> bool:
        """What changes at a remote: metadata, the catalog, and old-style snapshot files.

        Release files and timestamped snapshot files never change once published.
        """
        parsed = paths.classify(path)
        if parsed.is_metadata or parsed.kind == "catalog":
            return True
        return parsed.kind == "artifact" and parsed.is_snapshot and parsed.build is None

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        # A checksum path is treated as the path it belongs to.
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if request.method == "PUT":
            refusal = _excluded(context.repository.config["format_config"], parsed)
            if refusal is not None:
                raise refusal
        if algorithm is not None:
            return await _checksum(context, request, path, target, parsed, algorithm)
        if parsed.is_metadata:
            return await _metadata(context, request, path, parsed)
        return await super().handle_hosted(context, request, path)

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        if request.method not in ("GET", "HEAD"):
            return await super().handle_proxy(context, request, path)  # refuses it
        path = normalise_path(path)
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if paths.split_checksum(target)[1] is not None:
            # A checksum of a checksum: answering it would mean fetching and keeping
            # the remote's own checksum file, which a proxy never does.
            raise _not_found()
        settings = context.repository.config["format_config"]
        if _excluded(settings, parsed) is not None and await context.stat(target) is None:
            # Not asked of the remote: this repository would not keep the answer.
            raise _not_found()
        if algorithm is None:
            # Files, and metadata exactly as the remote wrote it: a proxy does not hold
            # every version, so it cannot write the list itself.
            return await super().handle_proxy(context, request, path)
        # The remote's own checksum file is never requested. The file is, if it is not
        # cached yet, and the checksum is of the bytes that will be served.
        await proxy.ensure_cached(context, target)
        stored = await context.stat(target)
        if stored is None:
            raise _not_found()
        return _checksum_response(
            context, request, path, getattr(stored, algorithm), stored.modified
        )

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if request.method in ("GET", "HEAD"):
            path = normalise_path(path)
            target, algorithm = paths.split_checksum(path)
            parsed = paths.classify(target)
            if parsed.is_metadata:
                found = await _merged(context, request, target, parsed)
                if found is None:
                    raise _not_found()
                merged, modified = found
                data = await off_loop(metadata.serialise, merged)
                if algorithm is None:
                    return _metadata_response(context, request, data, modified)
                digest = hashlib.new(algorithm, data).hexdigest()
                return _checksum_response(context, request, path, digest, modified)
        # A file and its checksums: the first member that has the file answers both.
        return await super().handle_group(context, request, path, serve)


register(MavenFormat())

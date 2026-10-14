"""Groups of APT repositories: one address, one key, for the suites of all the members.

A group serves each suite its members have. A client trusts the group's key and
nothing else, so the group checks what it signs: a proxy member's `InRelease` must be
signed by one of the keys its remote was given (`remote_keys`), and each `Packages`
file of it that the group reads must have the SHA-256 that `Release` names. A member
that fails a check is left out, its reason logged and kept as its last error, and the
group answers with the others. A hosted member's indexes are the server's own.

A suite that one member has is that member's, as it is: the group signs its `Release`
again, unchanged, and sends every other file of the suite on from that member, which
the client checks against that `Release`. Where several members have a suite, the
group writes a `Release` of its own: a component and architecture that one member has
is that member's files, and one that several have is one `Packages` written from
theirs, in their order, a package an earlier member has left out of a later one's.

What a group writes of a suite is kept, by a digest of what its members' indexes are
now: a hosted member's revision, and a proxy's `InRelease` and keys. Anything else is
answered as any group answers it: by the first member that has it.
"""

import asyncio
import gzip
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived, group, proxy, proxy_state, signing
from megooarti.repositories.apt import format as apt
from megooarti.repositories.apt import merge, releases
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve

log = structlog.get_logger(__name__)

# The most of a member's `InRelease`, and of a packed `Packages` file, that is read.
RELEASE_MOST = 16 * 1024 * 1024
PACKED_MOST = 256 * 1024 * 1024
# Which of a member's `Packages` files is read, the first that its `Release` names.
_VARIANTS = ("Packages.xz", "Packages.gz", "Packages")
_SIGNED = ("Release", "InRelease", "Release.gpg")


class LeftOut(Exception):
    """A member that a check found wanting, and why."""


@dataclass(frozen=True)
class Offer:
    """What one member has of a suite."""

    member: RepositoryContext
    release: releases.Release
    files: derived.Files | None  # a hosted member's own index files; None for a proxy


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def remote_keys(member: RepositoryContext) -> str:
    return member.repository.config.get("format_config", {}).get("remote_keys") or ""


async def _token(member: RepositoryContext, suite: str) -> str | None:
    """What a member's indexes of a suite are now, or None if it does not have the suite."""
    if member.repository.type == "hosted":
        if apt.suite_of(member) != suite:
            return None
        revision, _ = await member.revision()
        return f"{member.repository.id}:{revision}"
    path = f"dists/{suite}/InRelease"
    try:
        await proxy.ensure_cached(member, path)
    except ApiError as error:
        if error.status_code in group.TRY_NEXT:
            return None  # it does not have the suite, or cannot be asked now
        raise
    stored = await member.stat(path)
    if stored is None:
        return None
    keys = hashlib.sha256(remote_keys(member).encode()).hexdigest()
    return f"{member.repository.id}:{stored.sha256}:{keys}"


async def _leave_out(context: RepositoryContext, member: RepositoryContext, reason: str) -> None:
    log.warning(
        "group_member_unverified",
        group=context.repository.name,
        member=member.repository.name,
        reason=reason,
    )
    if member.repository.type == "proxy":
        said = f"Left out of the group {context.repository.name}: {reason}"
        await proxy_state.record_failure(
            member.db, member.repository, utcnow(), said, blockable=False
        )


async def _offer(member: RepositoryContext, suite: str) -> Offer:
    """What a member has of a suite, checked. Raises LeftOut."""
    if member.repository.type == "hosted":
        written = await apt.hosted_indexes(member)
        return Offer(member, releases.parse(written.files["Release"]), written.files)
    keys = remote_keys(member)
    if not keys:
        raise LeftOut("it has no keys of its remote to check its InRelease with")
    try:
        signed = await member.read(f"dists/{suite}/InRelease", limit=RELEASE_MOST)
    except TooLarge:
        raise LeftOut("its InRelease is larger than this server reads") from None
    if signed is None:
        raise LeftOut("its InRelease is gone")
    try:
        text = signing.verify_clear(signed, signing.read_public_keys(keys))
        return Offer(member, releases.parse(text), None)
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    except signing.Unverified as error:
        raise LeftOut(f"its InRelease is not signed by its remote's keys: {error}") from None
    except releases.InvalidRelease as error:
        raise LeftOut(f"its InRelease cannot be read: {error}") from None


def _variant(offer: Offer, directory: str) -> tuple[str, releases.Entry] | None:
    for name in _VARIANTS:
        entry = offer.release.entries.get(f"{directory}/{name}")
        if entry is not None:
            return f"{directory}/{name}", entry
    return None


async def _packages(offer: Offer, suite: str, directory: str) -> bytes:
    """A member's `Packages` of one component and architecture, as text, checked."""
    name, entry = _variant(offer, directory)
    if offer.files is not None:
        packed = offer.files.get(name)
    else:
        path = f"dists/{suite}/{name}"
        try:
            await proxy.ensure_cached(offer.member, path)
            packed = await offer.member.read(path, limit=PACKED_MOST)
        except TooLarge:
            raise LeftOut(f"its {name} is larger than this server reads") from None
        except ApiError as error:
            raise LeftOut(f"its {name} cannot be fetched: {error.message}") from None
    if packed is None or hashlib.sha256(packed).hexdigest() != entry.sha256:
        raise LeftOut(f"its {name} is not the one its Release names")
    try:
        return await asyncio.to_thread(merge.unpacked, name, packed)
    except merge.InvalidIndex as error:
        raise LeftOut(str(error)) from None


def _packed(texts: list[bytes]) -> tuple[bytes, releases.Entry]:
    """Members' `Packages` merged, as `Packages.gz`, and what `Release` says of the text.

    apt finds an index in `Release` by the name of its text (`Packages`), and checks
    the text it unpacks against it, as Debian's mirrors have it: the text is named and
    not kept. Debian's `main` for one architecture is 57 MB of text and 13 MB packed;
    packed with gzip it takes a second, with xz most of a minute.
    """
    text = merge.merged(texts)
    named = releases.Entry(len(text), hashlib.sha256(text).hexdigest())
    return gzip.compress(text, 6, mtime=0), named


def _signed(text: bytes, signer: signing.Signer) -> derived.Files:
    return {"Release": text, "InRelease": signer.clear(text), "Release.gpg": signer.detached(text)}


def _union(lists: Sequence[Sequence[str]]) -> list[str]:
    seen: list[str] = []
    for items in lists:
        seen.extend(item for item in items if item not in seen)
    return seen


async def _merged(
    context: RepositoryContext, offers: list[Offer], suite: str, signer: signing.Signer
) -> derived.Written:
    """A `Release` of the group's own, for a suite several members have."""
    components = _union([offer.release.components for offer in offers])
    architectures = [
        name for name in _union([offer.release.architectures for offer in offers]) if name != "all"
    ]
    entries: dict[str, releases.Entry] = {}
    files: derived.Files = {}
    routes: dict[str, uuid.UUID | None] = {"*": offers[0].member.repository.id}

    def copy(offer: Offer, prefix: str) -> None:
        for path, entry in offer.release.entries.items():
            if path.startswith(prefix) and path not in entries:
                entries[path] = entry

    for component in components:
        having = [offer for offer in offers if component in offer.release.components]
        routes[component] = having[0].member.repository.id
        for architecture in architectures:
            directory = f"{component}/binary-{architecture}"
            with_it = [offer for offer in having if _variant(offer, directory) is not None]
            if len(with_it) == 1:
                copy(with_it[0], f"{directory}/")
                routes[directory] = with_it[0].member.repository.id
            elif with_it:
                routes[directory] = None  # what is merged is the group's; nothing else is
                texts = []
                for offer in with_it:
                    try:
                        texts.append(await _packages(offer, suite, directory))
                    except LeftOut as error:
                        await _leave_out(context, offer.member, str(error))
                packed, named = await asyncio.to_thread(_packed, texts)
                files[f"{directory}/Packages.gz"] = packed
                entries[f"{directory}/Packages.gz"] = releases.Entry(
                    len(packed), hashlib.sha256(packed).hexdigest()
                )
                entries[f"{directory}/Packages"] = named
        # What else a component has (translations, and the like) is its first member's.
        for path in list(having[0].release.entries):
            if path.startswith(f"{component}/") and not path.startswith(f"{component}/binary-"):
                copy(having[0], path)
    for path in offers[0].release.entries:
        if "/" not in path:
            copy(offers[0], path)

    moments = [offer.release.moment for offer in offers if offer.release.moment is not None]
    moment = max(moments) if moments else utcnow()
    text = releases.compose(
        label=context.repository.name,
        suite=suite,
        moment=moment,
        components=components,
        architectures=architectures,
        entries=entries.items(),
    )
    return derived.Written("", moment, {**files, **_signed(text, signer)}, routes)


async def _suite_index(
    context: RepositoryContext, suite: str
) -> tuple[derived.Written, dict[uuid.UUID, RepositoryContext]]:
    """What the group has of a suite, and its members that answer for it."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, suite)
        if token is not None:
            candidates.append(member)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has this suite.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    revision = hashlib.sha256("\n".join([key.fingerprint, suite, *tokens]).encode()).hexdigest()

    async def write() -> derived.Written:
        offers = []
        for member in candidates:
            try:
                offers.append(await _offer(member, suite))
            except LeftOut as error:
                await _leave_out(context, member, str(error))
        if not offers:
            raise _not_found("No repository of this group that has this suite could be checked.")
        signer = signing.signer(context.settings, key)
        if len(offers) > 1:
            written = await _merged(context, offers, suite, signer)
        else:
            # One member's suite is that member's: its own Release, signed again.
            signed = _signed(offers[0].release.text, signer)
            moment = offers[0].release.moment or utcnow()
            written = derived.Written("", moment, signed, {"*": offers[0].member.repository.id})
        return derived.Written(revision, written.changed, written.files, written.routes)

    written = await derived.written((context.repository.id, suite), revision, write)
    return written, {member.repository.id: member for member in members}


def _route(routes: dict[str, uuid.UUID | None], path: str) -> uuid.UUID | None:
    """The member that answers for a file of a suite, or None if none does."""
    parts = path.split("/")
    for prefix in ("/".join(parts[:2]), parts[0]):
        if prefix in routes:
            return routes[prefix]
    return routes.get("*")


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """A suite's index files from what the group writes; anything else from a member."""
    if request.method not in ("GET", "HEAD") or not path.startswith("dists/"):
        return await group.handle_group(context, request, path, serve)
    suite, _, under = path.removeprefix("dists/").partition("/")
    written, members = await _suite_index(context, suite)
    data = written.files.get(under)
    if data is not None:
        filename = under.rpartition("/")[2]
        return context.respond_with(
            data,
            request,
            filename=filename,
            content_type=apt.index_content_type(filename),
            last_modified=written.changed,
            etag=hashlib.sha256(data).hexdigest(),
            dated=False,
        )
    if under in _SIGNED:
        raise _not_found("No such file.")
    member = members.get(_route(written.routes, under))
    if member is None:
        raise _not_found("No repository of this group has this file.")
    return await serve(member, request, path)

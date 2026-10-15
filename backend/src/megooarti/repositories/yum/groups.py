"""Groups of YUM repositories: one address, one key, for the `repodata/` of all the members.

A group serves a `repodata/` in each directory where a member has one: a hosted
member in a directory as deep as its `repodata_depth` that holds packages, a proxy
member where its remote has `repodata/repomd.xml`. A client trusts the group's key and
nothing else, so the group checks what it signs: every file of a member that it reads
must have the checksum the member's `repomd.xml` names, and a proxy's `repomd.xml` must
be signed by one of its remote's keys where it was given them (`remote_keys`). A
member that fails a check is left out, its reason logged and kept as its last error;
a proxy whose `repomd.xml` may be behind its remote is asked again first.

A directory one member has is that member's: its `repomd.xml` signed again with the
group's key, and every other file sent on from it; dnf checks each against that
`repomd.xml`. In a directory several members have, the group writes `primary.xml`,
`filelists.xml` and `other.xml` from theirs, an earlier member's package first, and
names in its `repomd.xml` what else the first member that has it has (package groups,
updates, modules).

What a group writes of a directory is kept, by a digest of what its members' metadata
is now: a hosted member's revision, and a proxy's `repomd.xml`, its signature and its
keys. A request does not wait for the next one while one is kept, and holds no
database connection while it waits for the first, and one is written at a time.
While a member that the last one had cannot be checked, the last one is kept a
while longer and tried again.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field, replace
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived, group, proxy, signing
from megooarti.repositories.checks import LeftOut, leave_out, members_in, remote_keys
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve
from megooarti.repositories.models import SigningKey
from megooarti.repositories.yum import format as yum
from megooarti.repositories.yum import merge, paths

# The most of a member's `repomd.xml` and of its signature that is read, and of one of
# its packed files.
REPOMD_MOST = 16 * 1024 * 1024
PACKED_MOST = 256 * 1024 * 1024
# How long what was written while a member was left out is served before another try.
RETRY = timedelta(minutes=1)
# The mark of a revision written while a member was left out: no digest ends so.
_INCOMPLETE = "~"
# Who answers for every file a group did not write itself, in `Written.routes`.
_ANY = "*"


@dataclass(frozen=True)
class Offer:
    """What one member has of a directory, checked."""

    member: RepositoryContext
    repomd: bytes
    said: merge.Repomd
    hosted: derived.Written | None  # a hosted member's own metadata; None for a proxy


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def _owned(kind: str) -> bool:
    """Whether a kind of file is one a group writes itself where it merges: the packages'
    lists, and every other form of them (`primary_db`, `filelists_zck`, ...)."""
    return kind.split("_")[0].split("-")[0] in merge.KINDS


def _in(directory: str, href: str) -> str:
    """A path under a directory, from what `repomd.xml` says of it."""
    return f"{directory}/{href}" if directory else href


async def _token(member: RepositoryContext, directory: str) -> str | None:
    """What a member's metadata of a directory is now, or None if it has none there."""
    if member.repository.type == "hosted":
        if not paths.at_depth(directory, yum.depth_of(member)):
            return None
        revision, _ = await member.revision()
        return f"{member.repository.id}:{revision}"
    found = []
    keys = remote_keys(member)
    for name in (paths.REPOMD, paths.SIGNATURE) if keys else (paths.REPOMD,):
        path = paths.in_repodata(directory, name)
        try:
            await proxy.ensure_cached(member, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            if name == paths.REPOMD:
                return None  # it does not have the directory, or cannot be asked now
        stored = await member.stat(path)
        if stored is None and name == paths.REPOMD:
            return None
        found.append(stored.sha256 if stored else "-")
    found.append(hashlib.sha256(keys.encode()).hexdigest())
    return f"{member.repository.id}:{':'.join(found)}"


class Stale(LeftOut):
    """A proxy member whose kept `repomd.xml` may be behind its remote: what it names, or
    its signature, is gone or not what it says. Fetched again, it may be whole."""


@dataclass
class _Outcome:
    """Which members a writing left out and why, and which of them asking again may mend."""

    left: dict[uuid.UUID, tuple[RepositoryContext, str]] = field(default_factory=dict)
    stale: set[uuid.UUID] = field(default_factory=set)


async def _leave(
    context: RepositoryContext, member: RepositoryContext, error: LeftOut, outcome: _Outcome
) -> None:
    """Note that a member is left out. It is said once the writing is done: what the
    member fetches after this, for the rest of the writing, would say all was well."""
    outcome.left.setdefault(member.repository.id, (member, str(error)))
    if isinstance(error, Stale):
        outcome.stale.add(member.repository.id)


async def _offer(member: RepositoryContext, directory: str) -> Offer:
    """What a member has of a directory, checked. Raises LeftOut."""
    hosted = None
    if member.repository.type == "hosted":
        hosted = await yum.hosted_repodata(member)
        repomd = yum.repodata_file(hosted, directory, paths.REPOMD)
    else:
        try:
            repomd = await member.read(
                paths.in_repodata(directory, paths.REPOMD), limit=REPOMD_MOST
            )
        except TooLarge:
            raise LeftOut("its repomd.xml is larger than this server reads") from None
        if repomd is None:
            raise Stale("its repomd.xml is gone")
        keys = remote_keys(member)
        if keys:
            await _check_signature(member, directory, repomd, keys)
    try:
        said = merge.parse_repomd(repomd)
    except merge.InvalidMetadata as error:
        raise LeftOut(str(error)) from None
    if "primary" not in said.data:
        raise LeftOut("its repomd.xml names no primary.xml")
    return Offer(member, repomd, said, hosted)


async def _check_signature(
    member: RepositoryContext, directory: str, repomd: bytes, keys: str
) -> None:
    """Raise unless one of its remote's keys signed a proxy's `repomd.xml`.

    The two are fetched each when its own copy is old: a signature that does not fit
    may be of the next `repomd.xml`, which asking again for both mends.
    """
    try:
        signature = await member.read(
            paths.in_repodata(directory, paths.SIGNATURE), limit=REPOMD_MOST
        )
    except TooLarge:
        signature = None
    if signature is None:
        raise Stale("its remote did not sign its repomd.xml, which its keys could check")
    try:
        certificates = signing.read_public_keys(keys)
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    try:
        signing.verify_detached(repomd, signature, certificates)
    except signing.Unverified as error:
        raise Stale(f"its repomd.xml is not signed by its remote's keys: {error}") from None


async def _packed(offer: Offer, directory: str, data: merge.Data) -> bytes:
    """One of a member's files that its `repomd.xml` names, as it is packed, checked."""
    if offer.hosted is not None:
        packed = yum.repodata_file(offer.hosted, directory, data.href.removeprefix("repodata/"))
        missing = LeftOut
    else:
        path = _in(directory, data.href)
        missing = Stale
        try:
            await proxy.ensure_cached(offer.member, path)
            packed = await offer.member.read(path, limit=PACKED_MOST)
        except TooLarge:
            raise LeftOut(f"its {data.type} is larger than this server reads") from None
        except ApiError as error:
            raise Stale(f"its {data.type} cannot be fetched: {error.message}") from None
    if packed is None:
        raise missing(f"its {data.type} is gone")
    try:
        merge.check(data, packed)
    except merge.InvalidMetadata as error:
        raise missing(str(error)) from None
    return packed


async def _merged_kind(
    context: RepositoryContext,
    kind: str,
    entries: list[tuple[Offer, set[bytes], str, bytes]],
    outcome: _Outcome,
) -> merge.Merged:
    """Members' files of one kind, merged; a member whose file cannot be read left out."""
    while True:
        try:
            return await asyncio.to_thread(
                merge.merged,
                kind,
                [(href, packed) for _, _, href, packed in entries],
                [mine for _, mine, _, _ in entries],
            )
        except merge.InvalidMetadata as error:
            offer = entries.pop(error.args[1])[0]
            await _leave(context, offer.member, LeftOut(str(error.args[0])), outcome)


async def _merged(
    context: RepositoryContext, offers: list[Offer], directory: str, outcome: _Outcome
) -> tuple[bytes, derived.Files, dict[str, uuid.UUID | None], list[Offer]]:
    """What the group writes of a directory several members have.

    Returns its `repomd.xml`, the files it names that the group wrote, which member
    answers for each of the others, and the members it has.
    """
    primaries: list[tuple[Offer, bytes]] = []
    for offer in offers:
        try:
            primaries.append((offer, await _packed(offer, directory, offer.said.data["primary"])))
        except LeftOut as error:
            await _leave(context, offer.member, error, outcome)
    while True:
        try:
            kept = await asyncio.to_thread(
                merge.kept,
                [(offer.said.data["primary"].href, packed) for offer, packed in primaries],
            )
            break
        except merge.InvalidMetadata as error:
            offer, _ = primaries.pop(error.args[1])
            await _leave(context, offer.member, LeftOut(str(error.args[0])), outcome)
    taken = [offer for offer, _ in primaries]
    if not taken:
        raise LeftOut("no member's primary.xml could be read")
    parts = [
        await _merged_kind(
            context,
            "primary",
            [
                (offer, mine, offer.said.data["primary"].href, packed)
                for (offer, packed), mine in zip(primaries, kept, strict=True)
            ],
            outcome,
        )
    ]
    for kind in ("filelists", "other"):
        entries = []
        for offer, mine in zip(taken, kept, strict=True):
            data = offer.said.data.get(kind)
            if data is None:
                continue
            try:
                entries.append((offer, mine, data.href, await _packed(offer, directory, data)))
            except LeftOut as error:
                await _leave(context, offer.member, error, outcome)
        parts.append(await _merged_kind(context, kind, entries, outcome))
    routes: dict[str, uuid.UUID | None] = {}
    passed = []
    for offer in taken:
        for kind, data in offer.said.data.items():
            if _owned(kind) or any(other.type == kind for other in passed):
                continue
            passed.append(data)
            routes[data.href.removeprefix("repodata/")] = offer.member.repository.id
    # The newest of its members' files: the same members, the same bytes, in any process.
    moment = max(offer.said.moment for offer in taken) or int(utcnow().timestamp())
    repomd = merge.repomd(str(moment), parts, passed)
    return repomd, {part.name: part.packed for part in parts}, routes, taken


def _carried(previous: derived.Written | None) -> derived.Files:
    """What the group wrote of the last revision that its `repomd.xml` named."""
    if previous is None:
        return {}
    repomd = previous.files.get(paths.REPOMD, b"")
    return {
        name: data
        for name, data in previous.files.items()
        if paths.hashed(name) and f'href="repodata/{name}"'.encode() in repomd
    }


async def _written(
    context: RepositoryContext,
    offers: list[Offer],
    directory: str,
    signer: signing.Signer,
    previous: derived.Written | None,
    outcome: _Outcome,
) -> derived.Written:
    """The group's `repodata/` of a directory. Raises LeftOut if no member can be read."""
    if len(offers) == 1:
        repomd, files, taken = offers[0].repomd, {}, offers
        routes: dict[str, uuid.UUID | None] = {_ANY: offers[0].member.repository.id}
    else:
        repomd, files, routes, taken = await _merged(context, offers, directory, outcome)
    if previous is not None:
        carried = _carried(previous)
        files = {**carried, **files}
        # Whoever answered for what the last `repomd.xml` named still does.
        named = previous.files.get(paths.REPOMD, b"")
        for name, member in previous.routes.items():
            if name == _ANY or f'href="repodata/{name}"'.encode() in named:
                routes.setdefault(name, member)
    files[paths.REPOMD] = repomd
    files[paths.SIGNATURE] = await asyncio.to_thread(signer.detached, repomd)
    members = frozenset(offer.member.repository.id for offer in taken)
    return derived.Written("", utcnow(), files, routes, members=members)


async def _offers(
    db: AsyncSession,
    context: RepositoryContext,
    candidates: list[uuid.UUID],
    directory: str,
    outcome: _Outcome,
) -> list[Offer]:
    offers = []
    for member in await members_in(db, context, candidates):
        try:
            offers.append(await _offer(member, directory))
        except LeftOut as error:
            await _leave(context, member, error, outcome)
    # A hosted member's directory without packages adds nothing to another's.
    filled = [offer for offer in offers if not _empty(offer, directory)]
    return filled or offers[:1]


async def _ask_again(
    db: AsyncSession, context: RepositoryContext, stale: set[uuid.UUID], directory: str
) -> None:
    """Fetch stale proxies' `repomd.xml` and signature again, however new their copies."""
    for member in await members_in(db, context, sorted(stale)):
        names = (paths.REPOMD, paths.SIGNATURE) if remote_keys(member) else (paths.REPOMD,)
        for name in names:
            try:
                await proxy.ensure_cached(member, paths.in_repodata(directory, name), again=True)
            except ApiError:
                pass  # what comes of it is seen when the member is checked again


def _digest(key: SigningKey, directory: str, tokens: list[str]) -> str:
    """What a group's metadata of a directory is written from: its key and its members'."""
    return hashlib.sha256("\n".join([key.fingerprint, directory, *tokens]).encode()).hexdigest()


async def _write(
    db: AsyncSession,
    context: RepositoryContext,
    candidates: list[uuid.UUID],
    directory: str,
    key: SigningKey,
    revision: str,
) -> derived.Written:
    """What the group has of a directory, written with a session of its own."""
    of = (context.repository.id, directory)
    now = utcnow()
    previous = derived.peek(of)
    whole = previous is not None and not str(previous.revision).endswith(_INCOMPLETE)
    signer = signing.signer(context.settings, key)
    for attempt in (1, 2):
        outcome = _Outcome()
        written = None
        offers = await _offers(db, context, candidates, directory, outcome)
        # Keep the last whole one while a member it had cannot be checked.
        held = whole and bool(outcome.left.keys() & previous.members)
        if offers and not held:
            try:
                written = await _written(context, offers, directory, signer, previous, outcome)
            except LeftOut:
                written = None
            held = whole and bool(outcome.left.keys() & previous.members)
        if outcome.stale and attempt == 1:
            await _ask_again(db, context, outcome.stale, directory)
            # What was asked again is what the next request finds: written for that.
            members = await members_in(db, context, candidates)
            tokens = [await _token(member, directory) for member in members]
            revision = _digest(key, directory, [token for token in tokens if token])
            continue
        break
    for member, reason in outcome.left.values():
        await leave_out(context, member, reason)
    await db.commit()
    if held:
        return replace(previous, held_until=now + RETRY)
    if written is None:
        raise _not_found("No repository of this group that has this directory could be checked.")
    if outcome.left:
        # Tried again after a while: what was left out may be back.
        return replace(written, revision=revision + _INCOMPLETE, held_until=now + RETRY)
    return replace(written, revision=revision)


def _empty(offer: Offer, directory: str) -> bool:
    """Whether an offer is a hosted member's directory that holds no packages."""
    return offer.hosted is not None and not yum.holds_packages(offer.hosted, directory)


async def _directory_index(
    context: RepositoryContext, request: Request, directory: str
) -> tuple[derived.Written, dict[uuid.UUID, RepositoryContext]]:
    """What the group has of a directory, and its members that answer for it."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, directory)
        if token is not None:
            candidates.append(member.repository.id)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has metadata in this directory.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    revision = _digest(key, directory, tokens)
    # A request that waits for the writing holds no connection: the writing has its own.
    await context.release()
    sessions = request.app.state.sessionmaker

    async def write() -> derived.Written:
        async with sessions() as db:
            return await _write(db, context, candidates, directory, key, revision)

    of = (context.repository.id, directory)
    written = await derived.written(of, revision, write, stale=True)
    return written, {member.repository.id: member for member in members}


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """A directory's `repodata/` from what the group writes; anything else from a member."""
    parsed = paths.classify(path)
    if request.method not in ("GET", "HEAD") or parsed.kind != "repodata":
        return await group.handle_group(context, request, path, serve)
    written, members = await _directory_index(context, request, parsed.directory)
    data = written.files.get(parsed.filename)
    if data is not None:
        return context.respond_with(
            data,
            request,
            filename=parsed.filename,
            content_type=yum.repodata_content_type(parsed.filename),
            last_modified=written.changed,
            etag=hashlib.sha256(data).hexdigest(),
            dated=False,
        )
    if parsed.filename in (paths.REPOMD, paths.SIGNATURE):
        raise _not_found("No such file.")
    member = members.get(written.routes.get(parsed.filename) or written.routes.get(_ANY))
    if member is None:
        raise _not_found("No repository of this group has this file.")
    return await serve(member, request, path)

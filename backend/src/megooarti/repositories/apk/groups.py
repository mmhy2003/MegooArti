"""Groups of apk repositories: one address, one key, for the indexes of all the members.

A group serves an `APKINDEX.tar.gz` in each directory where a member has one: a hosted
member in a directory where it holds packages, a proxy where its remote has the file.
A client trusts the group's key and nothing else, so the group checks what it signs:
a proxy's index must be signed by one of the keys its remote was given
(`remote_keys`), and a member that fails is left out, its reason logged and kept as
its last error.

A directory one member has is that member's index, its records as the member wrote
them, signed again with the group's key. In a directory several members have, the
group writes an index of its own, an earlier member's record first: of a name and
version, the file apk would ask for, the first member's alone. Packages are asked of
the members in order, as in any group.

What a group writes of a directory is kept, by a digest of what its members' indexes
are now: a hosted member's revision, and a proxy's index and keys. A request does not
wait for the next one while one is kept, and holds no database connection while it
waits for the first; one is written at a time. While a member that the last one had
cannot be checked, the last one is kept a while longer and tried again.
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
from megooarti.repositories.apk import format as apk
from megooarti.repositories.apk import index, paths
from megooarti.repositories.checks import LeftOut, leave_out, members_in, remote_keys
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve
from megooarti.repositories.models import SigningKey

# The most of a proxy member's index, packed, that is read.
PACKED_MOST = 256 * 1024 * 1024
# How long what was written while a member was left out is served before another try.
RETRY = timedelta(minutes=1)
# The mark of a revision written while a member was left out: no digest ends so.
_INCOMPLETE = "~"


@dataclass(frozen=True)
class Offer:
    """What one member has of a directory, checked."""

    member: RepositoryContext
    read: index.Read
    empty: bool  # a hosted member's directory that holds no packages


@dataclass
class _Outcome:
    """Which members a writing left out, and why."""

    left: dict[uuid.UUID, tuple[RepositoryContext, str]] = field(default_factory=dict)


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


async def _token(member: RepositoryContext, directory: str) -> str | None:
    """What a member's index of a directory is now, or None if it has none there."""
    if member.repository.type == "hosted":
        revision, _ = await member.revision()
        return f"{member.repository.id}:{revision}"
    path = paths.in_directory(directory, index.INDEX)
    try:
        await proxy.ensure_cached(member, path)
    except ApiError as error:
        if error.status_code in group.TRY_NEXT:
            return None  # it does not have the directory, or cannot be asked now
        raise
    stored = await member.stat(path)
    if stored is None:
        return None
    keys = hashlib.sha256(remote_keys(member).encode()).hexdigest()
    return f"{member.repository.id}:{stored.sha256}:{keys}"


async def _offer(member: RepositoryContext, directory: str) -> Offer:
    """What a member has of a directory, checked. Raises LeftOut."""
    if member.repository.type == "hosted":
        written = await apk.hosted_indexes(member)
        data = apk.index_file(written, directory)
        read = await asyncio.to_thread(index.read, data)
        return Offer(member, read, not apk.holds_packages(written, directory))
    keys = remote_keys(member)
    if not keys:
        raise LeftOut("it has no keys of its remote to check its index with")
    try:
        data = await member.read(paths.in_directory(directory, index.INDEX), limit=PACKED_MOST)
    except TooLarge:
        raise LeftOut("its index is larger than this server reads") from None
    if data is None:
        raise LeftOut("its index is gone")
    try:
        read = await asyncio.to_thread(index.read, data)
    except index.InvalidIndex as error:
        raise LeftOut(f"its index cannot be read: {error}") from None
    if not read.key_name:
        raise LeftOut("its index is not signed")
    try:
        certificates = signing.read_rsa_public_keys(keys)
        signing.verify_rsa(read.packed, read.signature, certificates, sha256=read.sha256)
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    except signing.Unverified:
        raise LeftOut(
            f"its index is not signed by its remote's keys (it says {read.key_name})"
        ) from None
    return Offer(member, read, False)


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
            outcome.left.setdefault(member.repository.id, (member, str(error)))
    # A hosted member's directory without packages adds nothing to another's.
    filled = [offer for offer in offers if not offer.empty]
    return filled or offers[:1]


def _written(
    offers: list[Offer], description: str, key_name: str, signer: signing.RsaSigner
) -> derived.Written:
    """The group's index of a directory, signed with its key."""
    if len(offers) == 1:
        # The member's records as it wrote them: its second stream, signed again.
        packed = offers[0].read.packed
    else:
        text = index.merged([offer.read.text for offer in offers])
        packed = index.archive(description, text, 0)
    data = index.signature(packed, key_name, signer, 0) + packed
    members = frozenset(offer.member.repository.id for offer in offers)
    return derived.Written("", utcnow(), {index.INDEX: data}, members=members)


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
    outcome = _Outcome()
    offers = await _offers(db, context, candidates, directory, outcome)
    for member, reason in outcome.left.values():
        await leave_out(context, member, reason)
    await db.commit()
    # Keep the last whole one while a member it had cannot be checked.
    if whole and outcome.left.keys() & previous.members:
        return replace(previous, held_until=now + RETRY)
    if not offers:
        raise _not_found("No repository of this group that has this directory could be checked.")
    written = await asyncio.to_thread(
        _written,
        offers,
        apk.description_of(context),
        paths.key_name(context.repository.name),
        signing.signer(context.settings, key),
    )
    if outcome.left:
        # Tried again after a while: what was left out may be back.
        return replace(written, revision=revision + _INCOMPLETE, held_until=now + RETRY)
    return replace(written, revision=revision)


async def _directory_index(
    context: RepositoryContext, request: Request, directory: str
) -> derived.Written:
    """What the group has of a directory."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, directory)
        if token is not None:
            candidates.append(member.repository.id)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has an index in this directory.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    said = "\n".join([key.fingerprint, directory, *tokens])
    revision = hashlib.sha256(said.encode()).hexdigest()
    # A request that waits for the writing holds no connection: the writing has its own.
    await context.release()
    sessions = request.app.state.sessionmaker

    async def write() -> derived.Written:
        async with sessions() as db:
            return await _write(db, context, candidates, directory, key, revision)

    of = (context.repository.id, directory)
    return await derived.written(of, revision, write, stale=True)


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """A directory's index from what the group writes; anything else from a member."""
    parsed = paths.classify(path, context.repository.name)
    if request.method not in ("GET", "HEAD") or parsed.kind != "index":
        return await group.handle_group(context, request, path, serve)
    written = await _directory_index(context, request, parsed.directory)
    data = written.files[index.INDEX]
    return context.respond_with(
        data,
        request,
        filename=index.INDEX,
        content_type="application/gzip",
        last_modified=written.changed,
        etag=hashlib.sha256(data).hexdigest(),
        dated=False,
    )

"""Groups of APT repositories: one address, one key, for the suites of all the members.

A group serves each suite its members have. A client trusts the group's key and
nothing else, so the group checks what it signs: a proxy member's `InRelease` must be
signed by one of the keys its remote was given (`remote_keys`), and must not have
expired (`Valid-Until`); each `Packages` file of it that the group reads must have the
SHA-256 that `Release` names, and is read by that hash where the remote has it so. A
member that fails a check is left out, its reason logged and kept as its last error.
A hosted member's indexes are the server's own.

The group writes a `Release` of its own for every suite. It says whose suite it is as
its first proxy member that has the suite says it, or else its first member: apt
refuses a suite whose Origin, Label or Codename changes. A suite one member has names
that member's files as they are, and every file is sent on from that member. A suite
several members have names, for a component and architecture one member has, that
member's files, and for one that several have, one `Packages.gz` written from theirs,
in their order, a package an earlier member has left out of a later one's. Its `Date`
never goes back, and it is valid no longer than its members are.

What a group writes of a suite is kept, by a digest of what its members' indexes are
now: a hosted member's revision, and a proxy's `InRelease` and keys. A request does
not wait for the next one while one is kept, and holds no database connection while
it waits for the first: the writing has a session of its own. While a member that the
last one had cannot be checked, the last one is kept a while longer and tried again.
Anything else is answered as any group answers it: by the first member that has it.
"""

import asyncio
import gzip
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived, group, proxy, signing
from megooarti.repositories.apt import format as apt
from megooarti.repositories.apt import merge, releases
from megooarti.repositories.checks import LeftOut, leave_out, members_in, remote_keys
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import Serve
from megooarti.repositories.models import SigningKey

# The most of a member's `InRelease`, and of a packed `Packages` file, that is read.
RELEASE_MOST = 16 * 1024 * 1024
PACKED_MOST = 256 * 1024 * 1024
# How long what was written while a member was left out is served before another try.
RETRY = timedelta(minutes=1)
# Which of a member's `Packages` files is read, the first that its `Release` names.
_VARIANTS = ("Packages.xz", "Packages.gz", "Packages")
_SIGNED = ("Release", "InRelease", "Release.gpg")
# The mark of a revision written while a member was left out: no digest ends so.
_INCOMPLETE = "~"


@dataclass(frozen=True)
class Offer:
    """What one member has of a suite."""

    member: RepositoryContext
    release: releases.Release
    files: derived.Files | None  # a hosted member's own index files; None for a proxy


def _not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


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


async def _offer(member: RepositoryContext, suite: str, now: datetime) -> Offer:
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
        release = releases.parse(signing.verify_clear(signed, signing.read_public_keys(keys)))
    except signing.KeysUnusable as error:
        raise LeftOut(f"its remote's keys cannot be read: {error}") from None
    except signing.Unverified as error:
        raise LeftOut(f"its InRelease is not signed by its remote's keys: {error}") from None
    except releases.InvalidRelease as error:
        raise LeftOut(f"its InRelease cannot be read: {error}") from None
    if release.valid_until is not None and release.valid_until < now:
        raise LeftOut(f"its Release was valid until {release.valid_until:%Y-%m-%d %H:%M} UTC")
    return Offer(member, release, None)


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
        # By its hash where the remote has it so: that file never changes, while the
        # one by its name may already be the next one's.
        path = (
            f"dists/{suite}/{directory}/by-hash/SHA256/{entry.sha256}"
            if offer.release.by_hash
            else f"dists/{suite}/{name}"
        )
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
    context: RepositoryContext, offers: list[Offer], suite: str
) -> tuple[list[str], list[str], dict, derived.Files, dict, bool]:
    """What a suite several members have names, and whether a member's file was left out.

    Returns its components, architectures, entries, the files the group writes, and
    which member answers for the others.
    """
    components = _union([offer.release.components for offer in offers])
    architectures = [
        name for name in _union([offer.release.architectures for offer in offers]) if name != "all"
    ]
    entries: dict[str, releases.Entry] = {}
    files: derived.Files = {}
    routes: dict[str, uuid.UUID | None] = {"*": offers[0].member.repository.id}
    incomplete = False

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
                        incomplete = True
                        await leave_out(context, offer.member, str(error))
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
    return components, architectures, entries, files, routes, incomplete


async def _written(
    context: RepositoryContext,
    offers: list[Offer],
    suite: str,
    signer: signing.Signer,
    previous: derived.Written | None,
) -> tuple[derived.Written, bool]:
    """The group's index files of a suite, and whether a member's file was left out."""
    if len(offers) == 1:
        only = offers[0]
        components, architectures = only.release.components, only.release.architectures
        entries, files = dict(only.release.entries), {}
        routes: dict = {"*": only.member.repository.id}
        by_hash, incomplete = only.release.by_hash, False
    else:
        components, architectures, entries, files, routes, incomplete = await _merged(
            context, offers, suite
        )
        by_hash = False
    lead = next((offer for offer in offers if offer.files is None), offers[0])
    moments = [offer.release.moment for offer in offers if offer.release.moment is not None]
    moment = max(moments) if moments else utcnow()
    if previous is not None:
        moment = max(moment, previous.changed)  # a client keeps a list newer than this
    ends = [offer.release.valid_until for offer in offers if offer.release.valid_until]
    text = releases.compose(
        header=lead.release.header,
        moment=moment,
        valid_until=min(ends) if ends else None,
        components=components,
        architectures=architectures,
        entries=entries.items(),
        by_hash=by_hash,
    )
    return derived.Written("", moment, {**files, **_signed(text, signer)}, routes), incomplete


async def _write(
    db: AsyncSession,
    context: RepositoryContext,
    candidates: list[uuid.UUID],
    suite: str,
    key: SigningKey,
    revision: str,
) -> derived.Written:
    """What the group has of a suite, written with a session of its own."""
    of = (context.repository.id, suite)
    now = utcnow()
    members = await members_in(db, context, candidates)
    offers, left_out = [], False
    for member in members:
        try:
            offers.append(await _offer(member, suite, now))
        except LeftOut as error:
            left_out = True
            await leave_out(context, member, str(error))
    previous = derived.peek(of)
    whole = previous is not None and not str(previous.revision).endswith(_INCOMPLETE)
    if left_out and whole:
        # Keep the last whole one while a member cannot be checked, and try again later.
        await db.commit()
        return replace(previous, held_until=now + RETRY)
    if not offers:
        await db.commit()
        raise _not_found("No repository of this group that has this suite could be checked.")
    signer = signing.signer(context.settings, key)
    written, incomplete = await _written(context, offers, suite, signer, previous)
    await db.commit()
    if left_out or incomplete:
        return replace(written, revision=revision + _INCOMPLETE, held_until=now + RETRY)
    return replace(written, revision=revision)


async def _suite_index(
    context: RepositoryContext, request: Request, suite: str
) -> tuple[derived.Written, dict[uuid.UUID, RepositoryContext]]:
    """What the group has of a suite, and its members that answer for it."""
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    candidates, tokens = [], []
    for member in members:
        token = await _token(member, suite)
        if token is not None:
            candidates.append(member.repository.id)
            tokens.append(token)
    if not candidates:
        raise _not_found("No repository of this group has this suite.")
    key = await signing.key_of(context.db, context.settings, context.repository)
    revision = hashlib.sha256("\n".join([key.fingerprint, suite, *tokens]).encode()).hexdigest()
    # A request that waits for the writing holds no connection: the writing has its own.
    await context.release()
    sessions = request.app.state.sessionmaker

    async def write() -> derived.Written:
        async with sessions() as db:
            return await _write(db, context, candidates, suite, key, revision)

    written = await derived.written((context.repository.id, suite), revision, write, stale=True)
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
    written, members = await _suite_index(context, request, suite)
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

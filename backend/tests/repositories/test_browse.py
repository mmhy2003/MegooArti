"""What a repository holds, as folders, files and components."""

import hashlib
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select

from megooarti.repositories import browse, service
from megooarti.repositories.browse import BadCursor
from megooarti.repositories.models import Asset
from tests.repositories.conftest import someone

EVERYTHING = someone("repository:raw:files", "repository:maven:releases")


@pytest.fixture
async def context(files, context_for):
    return await context_for(files, EVERYTHING)


async def put(context, *paths: str) -> None:
    for path in paths:
        await context.store(path, await context.stage_bytes(path.encode()))


async def listing(db, repository, folder: str = "", **options) -> list[tuple[str, str]]:
    options.setdefault("limit", 50)
    items, _ = await browse.children(db, repository, folder, **options)
    return [(child.kind, child.name) for child in items]


@contextmanager
def statements(connection):
    """Counts what is sent to the database while it is open."""
    seen: list[str] = []

    def note(connection, cursor, statement, *rest) -> None:
        seen.append(statement)

    event.listen(connection, "before_cursor_execute", note)
    try:
        yield seen
    finally:
        event.remove(connection, "before_cursor_execute", note)


async def test_a_folder_shows_what_is_directly_in_it(context, db, files):
    await put(context, "readme.txt", "docs/guide.md", "docs/api/index.html", "src/a/b/c.py")

    root = await listing(db, files)
    docs = await listing(db, files, "docs")
    deep = await listing(db, files, "src/a")

    assert root == [("folder", "docs"), ("file", "readme.txt"), ("folder", "src")]
    assert docs == [("folder", "api"), ("file", "guide.md")]
    assert deep == [("folder", "b")]


async def test_a_file_in_a_listing_says_what_it_is(context, db, files):
    await put(context, "docs/guide.md")

    (child,), following = await browse.children(db, files, "docs", limit=10)

    assert (child.name, child.path, child.kind) == ("guide.md", "docs/guide.md", "file")
    assert child.size == len(b"docs/guide.md")
    assert child.modified is not None
    # A file of a Raw repository is a component of its own: its folder and its name.
    assert (child.component.namespace, child.component.name) == ("docs", "guide.md")
    assert following is None


async def test_names_are_in_the_order_of_their_bytes(context, db, files):
    # "-" and "." come before "/", digits and letters after it, capitals before small.
    await put(context, "a/x", "a-b", "a.b", "a0", "aa", "B", "a", "ab/c", "a b")

    assert await listing(db, files) == [
        ("file", "B"),
        ("file", "a"),
        ("file", "a b"),
        ("file", "a-b"),
        ("file", "a.b"),
        ("folder", "a"),  # a name can be a file and a folder
        ("file", "a0"),
        ("file", "aa"),
        ("folder", "ab"),
    ]
    assert await listing(db, files, "a") == [("file", "x")]
    assert await listing(db, files, "ab") == [("file", "c")]


async def test_a_folder_does_not_show_its_neighbours(context, db, files):
    await put(context, "app/one", "app-old/two", "app.bak/three", "apple/four", "ap/five")

    assert await listing(db, files, "app") == [("file", "one")]
    assert await listing(db, files, "ap") == [("file", "five")]
    assert await listing(db, files, "apple") == [("file", "four")]


async def test_a_folder_that_is_not_there_is_empty(context, db, files):
    await put(context, "docs/guide.md")

    assert await listing(db, files, "nothing") == []
    assert await listing(db, files, "docs/guide.md") == []  # a file has nothing in it
    assert await listing(db, files, "doc") == []


async def test_a_long_folder_is_read_page_by_page(context, db, files):
    names = [f"file-{number:03}" for number in range(25)] + ["sub/one", "sub/two", "zeta"]
    await put(context, *(f"big/{name}" for name in names))
    read, after, pages = [], "", 0

    while True:
        items, following = await browse.children(db, files, "big", after=after, limit=10)
        read += [child.name for child in items]
        pages += 1
        if following is None:
            break
        after = following

    assert read == [f"file-{number:03}" for number in range(25)] + ["sub", "zeta"]
    assert pages == 3


async def test_reading_on_from_a_folder_or_a_file_skips_exactly_that(context, db, files):
    await put(context, "a", "a/one", "a/two", "b", "c/one")

    assert await listing(db, files, after="f:a") == [
        ("folder", "a"),
        ("file", "b"),
        ("folder", "c"),
    ]
    assert await listing(db, files, after="d:a") == [("file", "b"), ("folder", "c")]
    assert await listing(db, files, after="d:c") == []


@pytest.mark.parametrize("after", ["a", "x:a", "d:", "d:a/b", ":"])
async def test_what_is_not_a_cursor_is_refused(db, files, after):
    with pytest.raises(BadCursor):
        await browse.children(db, files, "", after=after, limit=10)


async def test_listing_a_folder_costs_the_same_whatever_lies_beneath_it(context, db, files):
    await put(
        context,
        *(
            f"top-{folder}/deep/{n}/file-{m}"
            for folder in "abc"
            for n in range(8)
            for m in range(8)
        ),
    )
    await put(context, "top-file")
    await db.commit()

    with statements((await db.connection()).sync_connection) as seen:
        items, _ = await browse.children(db, files, "", limit=50)

    assert [child.name for child in items] == ["top-a", "top-b", "top-c", "top-file"]
    assert len(seen) == 2  # the walk, and the details of the files it found


async def test_only_this_repository_is_listed(context, db, files, context_for):
    more = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    await put(await context_for(more, someone("repository:raw:more")), "theirs/file", "zzz")
    await put(context, "ours/file")

    assert await listing(db, files) == [("folder", "ours")]
    assert await listing(db, more) == [("folder", "theirs"), ("file", "zzz")]
    assert await listing(db, files, "theirs") == []


async def test_everything_about_a_file(context, db, files):
    data = b"docs/guide.md"
    await put(context, "docs/guide.md")

    detail = await browse.asset(db, files, "docs/guide.md")

    assert (detail.path, detail.size) == ("docs/guide.md", len(data))
    assert detail.sha256 == hashlib.sha256(data).hexdigest()
    assert detail.sha512 == hashlib.sha512(data).hexdigest()
    assert detail.sha1 == hashlib.sha1(data).hexdigest()
    assert detail.md5 == hashlib.md5(data).hexdigest()
    assert (detail.blob_store, detail.created_by) == ("default", "dana")
    assert detail.created is not None and detail.modified is not None
    assert (detail.last_downloaded, detail.last_verified) == (None, None)
    assert (detail.component.namespace, detail.component.name) == ("docs", "guide.md")
    assert await browse.asset(db, files, "docs") is None


async def test_the_paths_under_a_folder_are_read_in_order_and_in_pieces(context, db, files):
    await put(context, "a/1", "a/2", "a/b/3", "a-not/4", "a0", "b/5")

    everything = await browse.paths_under(db, files, "a", limit=10)
    first = await browse.paths_under(db, files, "a", limit=2)
    rest = await browse.paths_under(db, files, "a", after=first[-1], limit=10)

    assert everything == ["a/1", "a/2", "a/b/3"]
    assert (first, rest) == (["a/1", "a/2"], ["a/b/3"])


AWKWARD = [
    "app",
    "app/one",
    "app/two/three",
    "app-old/x",
    "app.bak/x",
    "app0",
    "app0/x",
    "apple",
    "app /x",
    "app!",
    "App",
    "d:app",
    "f:app/x",
    "100%",
    "a_b",
    "it's",
    "caf\u00e9/x",
    "\u6f22\u5b57",
    "z",
]


def expected_children(paths: list[str], folder: str) -> list[tuple[str, str]]:
    """What a folder shows, worked out the slow way."""
    prefix = f"{folder}/" if folder else ""
    seen: list[tuple[str, str]] = []
    for path in sorted(paths, key=lambda path: path.encode()):
        if not path.startswith(prefix):
            continue
        name, nested, _ = path[len(prefix) :].partition("/")
        child = ("folder" if nested else "file", name)
        if child not in seen:
            seen.append(child)
    return seen


@pytest.mark.parametrize("limit", [1, 2, 3, 7, 50])
@pytest.mark.parametrize("folder", ["", "app", "app0", "app/two", "caf\u00e9"])
async def test_awkward_names_are_all_listed_once_at_any_page_size(
    context, db, files, folder, limit
):
    await put(context, *AWKWARD)
    read, after = [], ""

    while True:
        items, following = await browse.children(db, files, folder, after=after, limit=limit)
        assert items or following is None  # never an empty page with more to come
        read += [(child.kind, child.name) for child in items]
        if following is None:
            break
        after = following

    assert read == expected_children(AWKWARD, folder)


async def test_a_folder_of_thousands_is_read_page_by_page(context, db, files):
    await put(context, "seed")
    blob = (await db.scalars(select(Asset.blob_id))).first()
    names = [f"file-{number:05}" for number in range(2500)]
    db.add_all(
        Asset(
            repository_id=files.id,
            path=f"many/{name}",
            blob_id=blob,
            content_type="text/plain",
            created_by="dana",
        )
        for name in names
    )
    await db.flush()
    read, after, pages = [], "", 0

    while after is not None:
        items, after = await browse.children(db, files, "many", after=after or "", limit=200)
        read += [child.name for child in items]
        pages += 1

    assert (read, pages) == (names, 13)


async def test_the_paths_under_a_folder_never_include_what_is_outside_it(context, db, files):
    await put(context, "aaa/keep", "app", "app-old/keep", "app/one", "app/two", "zzz/keep")

    for after in ("a", "aaa/keep", "app", "app-old/keep", ""):
        assert await browse.paths_under(db, files, "app", after=after, limit=10) == [
            "app/one",
            "app/two",
        ]
    assert await browse.paths_under(db, files, "app", after="app/one", limit=10) == ["app/two"]
    assert await browse.paths_under(db, files, "app", after="zzz", limit=10) == []


async def test_components_are_paged_with_when_they_last_changed(context, db, files):
    await put(context, "docs/a", "docs/b", "docs/c", "top")

    page, total = await browse.components(db, files, unlisted=frozenset(), limit=2, offset=1)
    hidden, fewer = await browse.components(
        db, files, unlisted=frozenset({"docs"}), limit=10, offset=0
    )

    assert total == 4
    assert [(part.namespace, part.name) for part in page] == [("docs", "a"), ("docs", "b")]
    assert all(part.modified is not None for part in page)
    assert ([part.name for part in hidden], fewer) == (["top"], 1)

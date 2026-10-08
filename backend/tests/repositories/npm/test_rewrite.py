import json
import random

import pytest

from megooarti.repositories.npm.rewrite import TarballLinks, rewrite

BASE = "https://repo.example/repository/npmjs"
REMOTE = "https://registry.npmjs.org"


def document(package: str = "left-pad", versions: tuple[str, ...] = ("1.0.0", "1.3.0")) -> bytes:
    """A package document as a remote serves it."""
    name = package.rpartition("/")[2]
    body = {
        "name": package,
        "readme": 'It says "tarball": "http://x/-/y.tgz" in prose, and \\ too.',
        "versions": {
            version: {
                "name": package,
                "version": version,
                "dist": {
                    "shasum": "0" * 40,
                    "tarball": f"{REMOTE}/{package}/-/{name}-{version}.tgz",
                },
            }
            for version in versions
        },
    }
    return json.dumps(body).encode()


def links(data: bytes) -> list[str]:
    return [version["dist"]["tarball"] for version in json.loads(data)["versions"].values()]


def in_pieces(data: bytes, cuts: list[int]) -> bytes:
    rewriter = TarballLinks(BASE, "left-pad")
    edges = [0, *sorted(cuts), len(data)]
    out = [rewriter.feed(data[start:end]) for start, end in zip(edges, edges[1:], strict=False)]
    return b"".join(out) + rewriter.finish()


def test_every_link_points_at_this_repository():
    rewritten = rewrite(document(), BASE, "left-pad")

    assert links(rewritten) == [
        f"{BASE}/left-pad/-/left-pad-1.0.0.tgz",
        f"{BASE}/left-pad/-/left-pad-1.3.0.tgz",
    ]


def test_nothing_else_changes():
    original, rewritten = json.loads(document()), json.loads(rewrite(document(), BASE, "left-pad"))
    for version in original["versions"].values():
        version["dist"]["tarball"] = "x"
    for version in rewritten["versions"].values():
        version["dist"]["tarball"] = "x"

    assert rewritten == original
    assert "http://x/-/y.tgz" in rewritten["readme"]  # prose that looks like a link


def test_a_scoped_package_links_to_its_scoped_path():
    rewritten = rewrite(document("@acme/widget", ("2.0.0",)), BASE, "@acme/widget")

    assert links(rewritten) == [f"{BASE}/@acme/widget/-/widget-2.0.0.tgz"]


@pytest.mark.parametrize(
    "written",
    [
        '"tarball":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"',
        '"tarball" : "https://r.example/left-pad/-/left-pad-1.0.0.tgz"',
        '"tarball":\n\t"http://other.example:8080/deep/path/left-pad/-/left-pad-1.0.0.tgz"',
        '"tarball":"/left-pad/-/left-pad-1.0.0.tgz"',
    ],
)
def test_links_are_found_however_they_are_spaced_and_wherever_they_point(written):
    rewritten = rewrite(f'{{"dist":{{{written}}}}}'.encode(), BASE, "left-pad")

    assert json.loads(rewritten) == {"dist": {"tarball": f"{BASE}/left-pad/-/left-pad-1.0.0.tgz"}}


@pytest.mark.parametrize(
    "left_alone",
    [
        b'{"tarball":"https:\\/\\/r.example\\/left-pad\\/-\\/left-pad-1.0.0.tgz"}',
        b'{"tarball":"https://r.example/download/left-pad/1.0.0/abcdef"}',
        b'{"tarball":"https://r.example/left-pad/-/left-pad-1.0.0.zip"}',
        b'{"tarball":17,"other":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"}',
        b'{"not-tarball":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"}',
        b"",
        b"not json at all",
    ],
)
def test_what_is_not_a_plain_link_is_passed_on_unchanged(left_alone):
    assert rewrite(left_alone, BASE, "left-pad") == left_alone


def test_the_result_is_the_same_wherever_the_document_is_cut():
    data = document()
    whole = rewrite(data, BASE, "left-pad")

    for cut in range(len(data) + 1):
        assert in_pieces(data, [cut]) == whole, cut


def test_a_tarball_that_is_no_link_far_back_does_not_hide_a_link_cut_in_its_key():
    # Something else called "tarball", then more text than a link is waited for.
    data = (
        b'{"keywords":["tarball"],"readme":"' + b"x" * 9000 + b'",'
        b'"dist":{"tarball":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"}}'
    )
    whole = rewrite(data, BASE, "left-pad")

    assert json.loads(whole)["dist"] == {"tarball": f"{BASE}/left-pad/-/left-pad-1.0.0.tgz"}
    for cut in range(len(data) + 1):
        assert in_pieces(data, [cut]) == whole, cut


def test_the_result_is_the_same_in_pieces_of_any_size():
    data = document(versions=tuple(f"1.{minor}.0" for minor in range(40)))
    whole = rewrite(data, BASE, "left-pad")
    chooser = random.Random(5)

    for size in (1, 2, 3, 7, 64, 1000):
        assert in_pieces(data, list(range(size, len(data), size))) == whole, size
    for _ in range(50):
        cuts = sorted(chooser.sample(range(len(data)), 12))
        assert in_pieces(data, cuts) == whole, cuts


def test_only_the_start_of_an_unfinished_link_is_held_back():
    rewriter = TarballLinks(BASE, "left-pad")

    passed = rewriter.feed(b'{"a":"' + b"x" * 100_000 + b'","tarball":"https://r.example/le')

    assert len(passed) == len(b'{"a":"') + 100_000 + len(b'",')
    assert rewriter.feed(b'ft-pad/-/left-pad-1.0.0.tgz"}') == (
        f'"tarball":"{BASE}/left-pad/-/left-pad-1.0.0.tgz"}}'.encode()
    )
    assert rewriter.finish() == b""


def test_a_value_too_long_to_be_a_link_is_not_waited_for():
    rewriter = TarballLinks(BASE, "left-pad")
    endless = b'{"tarball":"' + b"x" * 20_000

    assert rewriter.feed(endless) == endless
    assert rewriter.finish() == b""


def test_an_address_with_characters_json_escapes_stays_valid_json():
    rewritten = rewrite(document(versions=("1.0.0",)), 'https://odd.example/a"b', "left-pad")

    assert links(rewritten) == ['https://odd.example/a"b/left-pad/-/left-pad-1.0.0.tgz']

from html.parser import HTMLParser

import pytest

from megooarti.repositories.pypi import pages
from megooarti.repositories.pypi.pages import Link, Reader

SHA = "a" * 64


class Anchors(HTMLParser):
    """The links of a page, as a browser or pip would read them."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[dict[str, str | None], str]] = []
        self.metas: dict[str, str | None] = {}
        self._open: dict[str, str | None] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open = dict(attrs)
        if tag == "meta":
            self.metas[dict(attrs).get("name")] = dict(attrs).get("content")

    def handle_data(self, data):
        if self._open is not None:
            self.found.append((self._open, data))
            self._open = None


def read(page: bytes) -> Anchors:
    parser = Anchors()
    parser.feed(page.decode())
    return parser


def test_a_project_page_lists_each_file_with_its_hash():
    page = pages.project_page(
        "requests",
        [
            Link("requests-2.31.0.tar.gz", "2.31.0", f"sha256={SHA}"),
            Link("requests-2.31.0-py3-none-any.whl", "2.31.0", f"sha256={SHA}", ">=3.7"),
        ],
    )

    anchors = read(page)
    assert page.startswith(b"<!DOCTYPE html>")
    assert anchors.metas == {"pypi:repository-version": "1.0"}
    assert anchors.found == [
        (
            {"href": f"../../packages/requests/2.31.0/requests-2.31.0.tar.gz#sha256={SHA}"},
            "requests-2.31.0.tar.gz",
        ),
        (
            {
                "href": "../../packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl"
                f"#sha256={SHA}",
                "data-requires-python": ">=3.7",
            },
            "requests-2.31.0-py3-none-any.whl",
        ),
    ]


def test_what_a_file_declares_is_escaped_in_the_page():
    hostile = '">3.8"><script>alert(1)</script>'
    page = pages.project_page("pkg", [Link("pkg-1.0.tar.gz", "1.0", "", hostile)])

    assert b"<script>" not in page
    assert b"&gt;3.8" in page
    assert read(page).found == [
        (
            {"href": "../../packages/pkg/1.0/pkg-1.0.tar.gz", "data-requires-python": hostile},
            "pkg-1.0.tar.gz",
        )
    ]


def test_a_version_with_an_epoch_and_a_local_part_is_linked_as_it_is_written():
    page = pages.project_page("pkg", [Link("pkg-1.0+cpu.tar.gz", "1!1.0+cpu", f"sha256={SHA}")])

    assert read(page).found[0][0]["href"] == (
        f"../../packages/pkg/1!1.0+cpu/pkg-1.0+cpu.tar.gz#sha256={SHA}"
    )


def test_a_link_without_a_hash_has_no_fragment():
    page = pages.project_page("pkg", [Link("pkg-1.0.tar.gz", "1.0")])

    assert read(page).found[0][0] == {"href": "../../packages/pkg/1.0/pkg-1.0.tar.gz"}


def test_a_project_without_files_still_has_a_page():
    page = pages.project_page("pkg", [])

    assert read(page).found == []
    assert page.endswith(b"</html>\n")
    assert b"Links for pkg" in page


def test_the_root_page_links_each_project():
    page = pages.root_page(["django", "zope-interface"])

    assert read(page).found == [
        ({"href": "django/"}, "django"),
        ({"href": "zope-interface/"}, "zope-interface"),
    ]
    assert read(page).metas == {"pypi:repository-version": "1.0"}
    assert read(pages.root_page([])).found == []


HOST = "https://files.example/packages"
ADDRESS = "https://index.example/simple/requests/"
FILE = "https://f.example/requests-1.0.tar.gz"


def remote_link(path: str, digest: str, *attributes: str) -> str:
    """A link as pypi.org writes it: an absolute address on another host, then the name."""
    name = path.rpartition("/")[2]
    written = "".join(f" {attribute}" for attribute in attributes)
    return f'<a href="{HOST}/{path}#sha256={digest}"{written}>{name}</a><br />\n'


# A project page as pypi.org writes it.
REMOTE_PAGE = (
    "<!DOCTYPE html>\n<html>\n  <head>\n"
    '    <meta name="pypi:repository-version" content="1.3">\n'
    "    <title>Links for requests</title>\n  </head>\n  <body>\n"
    "    <h1>Links for requests</h1>\n"
    + remote_link("ab/cd/requests-2.30.0.tar.gz", SHA)
    + remote_link(
        "ef/01/requests-2.31.0-py3-none-any.whl",
        "b" * 64,
        'data-requires-python="&gt;=3.7"',
        f'data-dist-info-metadata="sha256={"c" * 64}"',
        f'data-core-metadata="sha256={"c" * 64}"',
    )
    + remote_link(
        "23/45/requests-2.31.0.tar.gz",
        "d" * 64,
        'data-requires-python="&gt;=3.7"',
        'data-yanked="broken &amp; withdrawn"',
    )
    + "</body>\n</html>\n<!--SERIAL 12345-->\n"
).encode()


def read_in_pieces(page: bytes, cuts: list[int], project: str = "requests") -> list[Link]:
    reader = Reader(project, ADDRESS)
    edges = [0, *sorted(cuts), len(page)]
    found = []
    for start, end in zip(edges, edges[1:], strict=False):
        found.extend(reader.feed(page[start:end]))
    return found


def test_the_links_of_a_remote_page_are_read():
    assert read_in_pieces(REMOTE_PAGE, []) == [
        Link(
            filename="requests-2.30.0.tar.gz",
            version="2.30.0",
            digest=f"sha256={SHA}",
            url=f"{HOST}/ab/cd/requests-2.30.0.tar.gz",
        ),
        Link(
            filename="requests-2.31.0-py3-none-any.whl",
            version="2.31.0",
            digest=f"sha256={'b' * 64}",
            requires_python=">=3.7",
            metadata=f"sha256={'c' * 64}",
            url=f"{HOST}/ef/01/requests-2.31.0-py3-none-any.whl",
        ),
        Link(
            filename="requests-2.31.0.tar.gz",
            version="2.31.0",
            digest=f"sha256={'d' * 64}",
            requires_python=">=3.7",
            yanked="broken & withdrawn",
            url=f"{HOST}/23/45/requests-2.31.0.tar.gz",
        ),
    ]


def test_the_links_read_are_the_same_wherever_the_page_is_cut():
    whole = read_in_pieces(REMOTE_PAGE, [])

    for cut in range(len(REMOTE_PAGE) + 1):
        assert read_in_pieces(REMOTE_PAGE, [cut]) == whole, cut
    for size in (1, 2, 3, 7, 64):
        assert read_in_pieces(REMOTE_PAGE, list(range(size, len(REMOTE_PAGE), size))) == whole


def test_a_link_inside_an_attribute_is_not_a_link_wherever_the_page_is_cut():
    inner = f"<a href='{HOST}/requests-6.6.6.tar.gz'>"
    page = (
        f'<a href="{HOST}/requests-1.0.tar.gz" title="see {inner} for more">x</a>'
        f'<a href="{HOST}/requests-2.0.tar.gz">y</a>'
    ).encode()

    for cut in range(len(page) + 1):
        found = read_in_pieces(page, [cut])
        assert [link.version for link in found] == ["1.0", "2.0"], cut


@pytest.mark.parametrize(
    ("tag", "address", "digest"),
    [
        # Relative links, as devpi, Artifactory and Nexus write them.
        (
            f'<a href="../../packages/ab/requests-1.0.tar.gz#md5={"a" * 32}">',
            "https://index.example/packages/ab/requests-1.0.tar.gz",
            "md5=" + "a" * 32,
        ),
        (
            '<a href="requests-1.0.tar.gz">',
            "https://index.example/simple/requests/requests-1.0.tar.gz",
            "",
        ),
        (
            '<a href="/root/requests-1.0.tar.gz">',
            "https://index.example/root/requests-1.0.tar.gz",
            "",
        ),
        # Other ways of writing a tag.
        (f"<A HREF='{FILE}'>", FILE, ""),
        (f"<a\n  class=x\thref={FILE} >", FILE, ""),
        (f'<a rel="internal" href = "{FILE}">', FILE, ""),
        (
            f'<a href="https://f.example/a%20b/requests-1.0.tar.gz?x=1#sha256={"A" * 64}">',
            "https://f.example/a%20b/requests-1.0.tar.gz?x=1",
            "sha256=" + "a" * 64,
        ),
        (
            '<a href="https://f.example/requests-1.0%2Blocal.tar.gz">',
            "https://f.example/requests-1.0%2Blocal.tar.gz",
            "",
        ),
        # A hash that cannot be checked here is dropped, not the link.
        (f'<a href="{FILE}#sha384={"a" * 96}">', FILE, ""),
        (f'<a href="{FILE}#sha256=nothex">', FILE, ""),
        (f'<a href="{FILE}#egg=requests">', FILE, ""),
    ],
)
def test_links_are_read_however_they_are_written(tag, address, digest):
    found = read_in_pieces(f"<body>{tag}requests-1.0.tar.gz</a></body>".encode(), [])

    assert [(link.url, link.digest) for link in found] == [(address, digest)]


def test_an_unescaped_greater_than_in_an_attribute_does_not_end_the_tag():
    page = f'<a data-requires-python=">=3.7,<4" href="{FILE}">x</a>'.encode()

    found = read_in_pieces(page, [])

    assert [(link.version, link.requires_python) for link in found] == [("1.0", ">=3.7,<4")]


@pytest.mark.parametrize(
    "tag",
    [
        "<a>",
        '<a name="top">',
        '<a href="">',
        '<a href="#sha256=' + "a" * 64 + '">',
        '<a href="https://f.example/urllib3-2.0.0.tar.gz">',  # another project's file
        '<a href="https://f.example/requests-1.0.txt">',
        '<a href="https://f.example/requests/">',
        '<a href="https://f.example/requests-1.0.tar.gz/">',
        '<a href="https://f.example/requests-..tar.gz">',
        '<a href="https://f.example/a/..%2Frequests-1.0.tar.gz">',
        '<a href="https://f.example/requests-1.0%20x.tar.gz">',
        '<a href="ftp://f.example/requests-1.0.tar.gz">',
        '<a href="file:///etc/requests-1.0.tar.gz">',
        '<a href="javascript:requests-1.0.tar.gz">',
        '<abbr href="https://f.example/requests-1.0.tar.gz">',
        '<link href="https://f.example/requests-1.0.tar.gz">',
        f'<a href="{FILE}"',  # never closed
        # Addresses a parser refuses.
        '<a href="http://[::1/requests-1.0.tar.gz">',
        '<a href="http://[not-an-address]/requests-1.0.tar.gz">',
        '<a href="//[/requests-1.0.tar.gz">',
    ],
)
def test_what_is_not_a_link_to_a_file_of_the_project_is_left_out(tag):
    assert read_in_pieces(f"<body>{tag}text</a></body>".encode(), []) == []


@pytest.mark.parametrize(
    ("attributes", "yanked", "metadata"),
    [
        ("", None, None),
        ("data-yanked", "", None),
        ('data-yanked=""', "", None),
        ('data-yanked="a\nreason"', "areason", None),
        ('data-core-metadata="true"', None, "true"),
        ("data-dist-info-metadata=true", None, "true"),
        ('data-core-metadata="false"', None, None),
        ('data-core-metadata=""', None, "true"),
        ('data-core-metadata="sha256=' + "E" * 64 + '"', None, "sha256=" + "e" * 64),
        ('data-core-metadata="sha384=' + "e" * 96 + '"', None, "true"),
        (
            'data-dist-info-metadata="true" data-core-metadata="sha256=' + "e" * 64 + '"',
            None,
            "sha256=" + "e" * 64,
        ),
    ],
)
def test_what_a_remote_says_about_a_file(attributes, yanked, metadata):
    page = f'<a href="{FILE}" {attributes}>x</a>'.encode()

    (link,) = read_in_pieces(page, [])

    assert (link.yanked, link.metadata) == (yanked, metadata)


def test_what_a_remote_declares_is_bounded():
    page = f'<a href="{FILE}" data-requires-python="{"&gt;=3" * 2000}">x</a>'.encode()

    (link,) = read_in_pieces(page, [])

    assert len(link.requires_python) == 1024


def test_a_tag_too_long_to_be_a_link_is_passed_over_and_reading_goes_on():
    endless = f'<a href="{FILE}" title="{"x" * 40_000}">x</a>'
    page = (endless + '<a href="https://f.example/requests-2.0.tar.gz">y</a>').encode()
    whole = read_in_pieces(page, [])

    assert [link.version for link in whole] == ["2.0"]
    for cut in range(0, len(page), 997):
        assert read_in_pieces(page, [cut]) == whole, cut


def test_only_an_unfinished_tag_is_held_back():
    reader = Reader("requests", ADDRESS)

    reader.feed(b"x" * 1_000_000 + b'<a href="https://f.example/requests-1.0')

    assert len(reader._held) == len(b'<a href="https://f.example/requests-1.0')
    assert [link.version for link in reader.feed(b'.tar.gz">x</a>' + b"y" * 1000)] == ["1.0"]
    assert reader._held == b""


def test_text_that_is_not_utf8_does_not_stop_the_reading():
    page = b'<p>\xff\xfe</p><a title="\xff" href="' + FILE.encode() + b'">\xff</a>'

    assert [link.version for link in read_in_pieces(page, [])] == ["1.0"]


def test_a_link_read_from_a_remote_is_written_with_what_it_said():
    (_, wheel, yanked) = read_in_pieces(REMOTE_PAGE, [])

    page = pages.project_page("requests", [wheel, yanked])

    assert HOST.encode() not in page  # where the remote keeps a file is never passed on
    assert read(page).found == [
        (
            {
                "href": "../../packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl"
                f"#sha256={'b' * 64}",
                "data-requires-python": ">=3.7",
                "data-dist-info-metadata": f"sha256={'c' * 64}",
                "data-core-metadata": f"sha256={'c' * 64}",
            },
            "requests-2.31.0-py3-none-any.whl",
        ),
        (
            {
                "href": f"../../packages/requests/2.31.0/requests-2.31.0.tar.gz#sha256={'d' * 64}",
                "data-requires-python": ">=3.7",
                "data-yanked": "broken & withdrawn",
            },
            "requests-2.31.0.tar.gz",
        ),
    ]


def test_a_yanked_file_without_a_reason_is_still_marked():
    page = pages.project_page("pkg", [Link("pkg-1.0.tar.gz", "1.0", yanked="")])

    assert read(page).found[0][0] == {
        "href": "../../packages/pkg/1.0/pkg-1.0.tar.gz",
        "data-yanked": "",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sha256=" + "A" * 64, ("sha256", "a" * 64)),
        ("md5=" + "0" * 32, ("md5", "0" * 32)),
        ("SHA1=" + "f" * 40, ("sha1", "f" * 40)),
        ("sha512=" + "1" * 128, ("sha512", "1" * 128)),
        ("sha256=" + "a" * 63, None),
        ("sha256=" + "g" * 64, None),
        ("sha384=" + "a" * 96, None),
        ("blake2b=" + "a" * 64, None),
        ("true", None),
        ("", None),
    ],
)
def test_a_hash_that_can_be_checked(text, expected):
    assert pages.digest_of(text) == expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (FILE, FILE + ".metadata"),
        (FILE + "?x=1", FILE + ".metadata?x=1"),
        ("http://h.example/a/b.whl", "http://h.example/a/b.whl.metadata"),
    ],
)
def test_a_metadata_file_is_beside_its_file(address, expected):
    assert pages.metadata_address(address) == expected


def test_a_link_that_cannot_be_read_does_not_stop_the_others():
    page = (
        f'<a href="{FILE}">a</a>'
        '<a href="http://[::1/requests-2.0.tar.gz">b</a>'
        '<a href="https://f.example/requests-3.0.tar.gz">c</a>'
    ).encode()

    assert [link.version for link in read_in_pieces(page, [])] == ["1.0", "3.0"]

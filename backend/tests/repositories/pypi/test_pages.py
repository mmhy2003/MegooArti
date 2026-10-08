from html.parser import HTMLParser

from megooarti.repositories.pypi import pages
from megooarti.repositories.pypi.pages import Link

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

"""PyPI index pages (PEP 503): the list of projects, and the files of one project.

Pure functions. Every link is relative, so a page is the same whatever address the
client used to reach the repository.

A proxy does not serve a remote's page. `Reader` takes the links out of it as it
streams, and the page served is written from them here: nothing a remote wrote reaches a
client but file names, hashes and a few known attributes.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape, unescape
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from megooarti.repositories.pypi import names

CONTENT_TYPE = "text/html; charset=utf-8"
_HEAD = (
    "<!DOCTYPE html>\n<html>\n  <head>\n"
    '    <meta name="pypi:repository-version" content="1.0">\n'
    "    <title>{title}</title>\n  </head>\n  <body>\n    <h1>{title}</h1>\n"
)
_FOOT = "  </body>\n</html>\n"

# The opening tag of a link. A quoted value may contain `>`, so quotes are followed.
_START = re.compile(rb"<a\s", re.IGNORECASE)
_TAG = re.compile(rb"<a\s((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.IGNORECASE)
_ATTRIBUTE = re.compile(
    rb"([A-Za-z][A-Za-z0-9_:.-]*)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+)))?"
)
# The longest tag that is read. A longer one is passed over.
MAX_TAG = 16 * 1024
# The hashes a blob store computes, with their length in hex: what a download can be
# checked against.
_HASHES = {"sha256": 64, "sha512": 128, "sha1": 40, "md5": 32}
_MAX_DECLARED = 1024


@dataclass(frozen=True)
class Link:
    """One file on a project's page."""

    filename: str
    version: str
    digest: str = ""  # `sha256=<hex>`: what a client checks the download against
    requires_python: str | None = None
    yanked: str | None = None  # the reason given, which may be empty; None if not yanked
    metadata: str | None = None  # `sha256=<hex>` or `true` if the file has a metadata file
    url: str = ""  # where a remote keeps the file; never written to a page


def _segment(text: str) -> str:
    """A version or a file name as it is written in an address. `+` and `!` stay."""
    return quote(text, safe="+!")


def head(title: str) -> bytes:
    return _HEAD.format(title=escape(title)).encode()


def foot() -> bytes:
    return _FOOT.encode()


def link_line(project: str, link: Link) -> bytes:
    """One file's line. `project` is in its normal form; the page is at `simple/<project>/`."""
    address = f"../../packages/{project}/{_segment(link.version)}/{_segment(link.filename)}"
    if link.digest:
        address += f"#{link.digest}"
    attributes = f' href="{escape(address)}"'
    if link.requires_python:
        attributes += f' data-requires-python="{escape(link.requires_python)}"'
    if link.yanked is not None:
        attributes += f' data-yanked="{escape(link.yanked)}"'
    if link.metadata is not None:
        # Under both names: older clients know only the first, newer ones the second.
        value = escape(link.metadata)
        attributes += f' data-dist-info-metadata="{value}" data-core-metadata="{value}"'
    return f"    <a{attributes}>{escape(link.filename)}</a><br>\n".encode()


def project_page(project: str, links: Iterable[Link]) -> bytes:
    """The page of a project that is held whole in memory: a hosted repository's."""
    lines = [link_line(project, link) for link in links]
    return head(f"Links for {project}") + b"".join(lines) + foot()


def root_page(projects: Iterable[str]) -> bytes:
    """The list of projects. The page is at `simple/`."""
    lines = [
        f'    <a href="{escape(project)}/">{escape(project)}</a><br>\n' for project in projects
    ]
    return head("Simple index") + "".join(lines).encode() + foot()


def metadata_address(address: str) -> str:
    """Where the metadata file of a file is: the file's address with `.metadata` added."""
    parts = urlsplit(address)
    return urlunsplit(parts._replace(path=parts.path + ".metadata"))


def digest_of(text: str) -> tuple[str, str] | None:
    """`sha256=<hex>` as (algorithm, lower-case hex), if it is a hash that can be checked."""
    algorithm, _, value = text.strip().partition("=")
    algorithm, value = algorithm.lower(), value.lower()
    if _HASHES.get(algorithm) != len(value) or not value.isalnum() or not value.isascii():
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return algorithm, value


def _declared(value: str | None) -> str | None:
    """Text a remote's page gives for a file, bounded and on one line."""
    if value is None:
        return None
    kept = "".join(character for character in value if character.isprintable())
    return kept.strip()[:_MAX_DECLARED]


class Reader:
    """Reads the links of a remote's project page, fed to it in pieces.

    `feed` returns the links found so far, in the page's order. A link whose file is
    not a file of the project is left out. What is held back between pieces is at most
    one unfinished tag, and a tag is settled before anything after it is looked at, so
    the links found do not depend on where the page is cut.
    """

    def __init__(self, project: str, address: str) -> None:
        """`project` is in its normal form. `address` is the page's own, for its links."""
        self._project = project
        self._address = address
        self._held = b""

    def feed(self, chunk: bytes) -> list[Link]:
        data = self._held + chunk
        found = []
        position = 0
        while True:
            start = _START.search(data, position)
            if start is None:
                # The end may be the beginning of a tag: `<`, or `<a`.
                keep = 2 if data[-2:].lower() == b"<a" else 1 if data.endswith(b"<") else 0
                self._held = data[len(data) - keep :] if keep else b""
                return found
            tag = _TAG.match(data, start.start(), start.start() + MAX_TAG)
            if tag is None:
                if len(data) - start.start() < MAX_TAG:
                    self._held = data[start.start() :]  # it may not have ended yet
                    return found
                position = start.end()  # too long to be a link, or not a tag: passed over
                continue
            position = tag.end()
            link = self._link(tag[1])
            if link is not None:
                found.append(link)

    def _link(self, written: bytes) -> Link | None:
        given: dict[str, str] = {}
        for name, double, single, bare in _ATTRIBUTE.findall(written):
            value = (double or single or bare).decode("utf-8", "replace")
            given.setdefault(name.decode("ascii").lower(), unescape(value))
        href = given.get("href")
        if not href:
            return None
        target, _, fragment = href.partition("#")
        try:
            address = urljoin(self._address, target)
            parts = urlsplit(address)
        except ValueError:
            return None  # not an address at all: one bad link must not cost the others
        filename = unquote(parts.path.rpartition("/")[2])
        if parts.scheme not in ("http", "https") or not names.is_valid_segment(filename):
            return None
        version = names.version_of(self._project, filename)
        if version is None:
            return None
        digest = digest_of(fragment)
        described = given.get("data-core-metadata", given.get("data-dist-info-metadata"))
        metadata = None
        if described is not None and described.strip().lower() != "false":
            checked = digest_of(described)
            metadata = "true" if checked is None else "=".join(checked)
        return Link(
            filename=filename,
            version=version,
            digest="" if digest is None else "=".join(digest),
            requires_python=_declared(given.get("data-requires-python")) or None,
            yanked=_declared(given.get("data-yanked")),
            metadata=metadata,
            url=address,
        )

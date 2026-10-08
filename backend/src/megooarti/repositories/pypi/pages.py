"""PyPI index pages (PEP 503): the list of projects, and the files of one project.

Pure functions. Every link is relative, so a page is the same whatever address the
client used to reach the repository.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

CONTENT_TYPE = "text/html; charset=utf-8"
_HEAD = (
    "<!DOCTYPE html>\n<html>\n  <head>\n"
    '    <meta name="pypi:repository-version" content="1.0">\n'
    "    <title>{title}</title>\n  </head>\n  <body>\n    <h1>{title}</h1>\n"
)
_FOOT = "  </body>\n</html>\n"


@dataclass(frozen=True)
class Link:
    """One file on a project's page."""

    filename: str
    version: str
    digest: str = ""  # `sha256=<hex>`: what a client checks the download against
    requires_python: str | None = None


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

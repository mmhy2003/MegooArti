"""Point the tarball links of a package document at this repository, as it streams.

A proxy serves the remote's package document, and every `"tarball"` in it names the
remote. These documents reach tens of megabytes, so they are never parsed: the links
are rewritten in the bytes as they pass. Pure: no database, no files.

A JSON string cannot contain an unescaped quote, so `"tarball": "` can only be a key
and its value, never text inside a README.
"""

import json
import re

# "tarball": "<any address>/-/<file>.tgz" - the value has no quote and no backslash, so
# a link written with escaped slashes is left as it is.
_LINK = re.compile(rb'"tarball"\s*:\s*"[^"\\]*/-/([^"/\\]+\.tgz)"')
_KEY = b'"tarball"'
# The longest link that is waited for. Anything longer is passed on unchanged.
_MAX_LINK = 8192


class TarballLinks:
    """Rewrites links in a document fed to it in pieces.

    `feed` returns what can be passed on so far; `finish` returns the rest. What is
    held back is only the start of a link that has not ended yet.
    """

    def __init__(self, base: str, package: str) -> None:
        """`base` is the public address of the repository, without a trailing slash."""
        # As it is written inside a JSON string: an address may hold a character JSON escapes.
        self._opening = b'"tarball":"' + json.dumps(f"{base}/{package}/-/")[1:-1].encode()
        self._held = b""

    def feed(self, chunk: bytes) -> bytes:
        data = self._held + chunk
        passed = []
        position = 0
        for link in _LINK.finditer(data):
            passed.append(data[position : link.start()])
            passed.append(self._opening + link[1] + b'"')
            position = link.end()
        rest = data[position:]
        keep = _unfinished(rest)
        passed.append(rest[: len(rest) - keep])
        self._held = rest[len(rest) - keep :] if keep else b""
        return b"".join(passed)

    def finish(self) -> bytes:
        held, self._held = self._held, b""
        return held


def _unfinished(rest: bytes) -> int:
    """How many bytes at the end of `rest` may be the start of a link.

    Only the last `"tarball"` can be one: an earlier one that did not match is followed
    by a quote, which ends its value.
    """
    start = rest.rfind(_KEY)
    if start != -1:
        waiting = len(rest) - start
        return waiting if waiting <= _MAX_LINK else 0
    # No whole key: the end may still be the beginning of one.
    for length in range(min(len(_KEY) - 1, len(rest)), 0, -1):
        if rest.endswith(_KEY[:length]):
            return length
    return 0


def rewrite(document: bytes, base: str, package: str) -> bytes:
    """A whole document with its links rewritten."""
    links = TarballLinks(base, package)
    return links.feed(document) + links.finish()

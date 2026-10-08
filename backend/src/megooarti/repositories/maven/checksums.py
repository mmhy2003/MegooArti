"""Reading a checksum file a client uploaded."""

import re

LIMIT = 1024

_DIGEST_LENGTH = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}
_HEX = frozenset("0123456789abcdef")
# The BSD style: "SHA1(file)= <digest>".
_LABELLED = re.compile(r".+= [0-9A-Fa-f]+")


def read_uploaded(body: bytes, algorithm: str) -> str | None:
    """The digest in an uploaded checksum file, in lower case, or None if there is none.

    Read the way Maven reads these files: the first line that is not blank; in it, the
    text after "= " if the line has that form, otherwise the first word.
    """
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if _LABELLED.fullmatch(line):
        word = line.rpartition(" ")[2]
    else:
        word = line.partition(" ")[0]
    word = word.lower()
    if len(word) != _DIGEST_LENGTH[algorithm] or not _HEX.issuperset(word):
        return None
    return word

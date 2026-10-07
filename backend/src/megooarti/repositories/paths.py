"""Validation of paths inside a repository.

These paths are database keys, never file paths: blob files are named by content hash.
The rules exist so that one asset has one spelling and nothing surprising is stored.
"""

from megooarti.errors import ApiError

MAX_PATH_BYTES = 1024


def _invalid(reason: str) -> ApiError:
    return ApiError(400, "invalid_path", f"The path is not valid: {reason}.")


def normalise_path(raw: str) -> str:
    """Return `raw` if it is an acceptable repository path; raise 400 invalid_path if not."""
    if not raw:
        raise _invalid("it is empty")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise _invalid(f"it is longer than {MAX_PATH_BYTES} bytes")
    if "\\" in raw:
        raise _invalid("it contains a backslash")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise _invalid("it contains a control character")
    for segment in raw.split("/"):
        if segment in ("", ".", ".."):
            raise _invalid("it has an empty, '.' or '..' segment")
    return raw

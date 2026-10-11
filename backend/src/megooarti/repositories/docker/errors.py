"""Errors in the registry's own shape.

Container clients show a registry's error codes to their users, so under `/v2/` an
error is `{"errors": [{"code", "message", "detail"}]}`, not MegooArti's envelope. This
is the one API that does not use the standard one.
"""

from typing import Any

from starlette.responses import JSONResponse

from megooarti.errors import ApiError

API_VERSION = {"Docker-Distribution-Api-Version": "registry/2.0"}
# For an error raised by the core in MegooArti's own shape: the code that fits its status.
_BY_STATUS = {
    400: "UNSUPPORTED",
    401: "UNAUTHORIZED",
    403: "DENIED",
    404: "NAME_UNKNOWN",
    405: "UNSUPPORTED",
    409: "DENIED",
    413: "SIZE_INVALID",
    416: "BLOB_UPLOAD_INVALID",
    429: "TOOMANYREQUESTS",
}


class RegistryError(ApiError):
    """An error with one of the registry's codes. `code` is that code, in upper case."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, code, message, headers=headers)
        self.detail = detail


def unknown(code: str, message: str) -> RegistryError:
    """`404` for something of a kind the registry names: a blob, a manifest, an upload."""
    return RegistryError(404, code, message)


def response(error: ApiError, headers: dict[str, str] | None = None) -> JSONResponse:
    """The answer for an error raised anywhere beneath a registry route."""
    if isinstance(error, RegistryError):
        code, detail = error.code, error.detail
    else:
        code, detail = _BY_STATUS.get(error.status_code, "UNKNOWN"), None
    entry: dict[str, Any] = {"code": code, "message": error.message}
    if detail is not None:
        entry["detail"] = detail
    return JSONResponse(
        {"errors": [entry]},
        status_code=error.status_code,
        headers={**API_VERSION, **(error.headers or {}), **(headers or {})},
    )

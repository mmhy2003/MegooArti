"""One JSON shape for every error the API returns."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from megooarti.request_id import HEADER as REQUEST_ID_HEADER

log = structlog.get_logger(__name__)

_CODES_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
}


class ApiError(Exception):
    """Raise from a handler to return an error response in the standard shape."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }
    response = JSONResponse(body, status_code=status_code, headers=headers)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(request, error.status_code, error.code, error.message, error.details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _CODES_BY_STATUS.get(error.status_code, "http_error")
        return error_response(
            request, error.status_code, code, str(error.detail), headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return error_response(
            request, 422, "validation_error", "The request is not valid.", details
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        log.error(
            "unhandled_exception",
            request_id=getattr(request.state, "request_id", None),
            method=request.method,
            path=request.url.path,
            exc_info=error,
        )
        return error_response(request, 500, "internal_error", "An unexpected error occurred.")

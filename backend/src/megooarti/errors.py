"""One JSON shape for every error the API returns."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]]
    request_id: str | None


class ErrorResponse(BaseModel):
    """The body of every error response."""

    error: ErrorBody


# Passed to FastAPI(responses=...) so the OpenAPI document describes this shape on every
# route, in place of FastAPI's own validation-error schema.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": ErrorResponse, "description": "Any error."}
}


class ApiError(Exception):
    """Raise from a handler to return an error response in the standard shape."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or [], request_id=request_id)
    )
    response = JSONResponse(body.model_dump(), status_code=status_code, headers=headers)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


class UnhandledErrorMiddleware:
    """Turn an exception no handler caught into the standard 500 response.

    Doing this here, rather than in a FastAPI handler for Exception, keeps the log line
    and the response inside the request ID scope and inside every other middleware.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:
            if response_started:  # too late to change the response; let the server log it
                raise
            request = Request(scope)
            log.error(
                "unhandled_exception",
                method=request.method,
                path=request.url.path,
                exc_info=error,
            )
            response = error_response(
                request, 500, "internal_error", "An unexpected error occurred."
            )
            await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request, error.status_code, error.code, error.message, error.details, error.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _CODES_BY_STATUS.get(error.status_code, "http_error")
        return error_response(
            request, error.status_code, code, str(error.detail), headers=error.headers
        )

    @app.exception_handler(DBAPIError)
    async def handle_database_error(request: Request, error: DBAPIError) -> JSONResponse:
        # 22021 is text PostgreSQL cannot store, such as a NUL character: bad input,
        # not a server fault. Every other database error stays an unhandled 500.
        if getattr(error.orig, "sqlstate", None) != "22021":
            raise error
        return error_response(
            request,
            422,
            "validation_error",
            "The request contains a character that cannot be stored.",
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

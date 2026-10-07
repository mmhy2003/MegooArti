import re

import pytest
import structlog
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response

from megooarti.request_id import RequestIdMiddleware

GENERATED = re.compile(r"[0-9a-f]{32}")


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def echo(request: Request) -> dict[str, str | None]:
        return {
            "state": request.state.request_id,
            "log_context": structlog.contextvars.get_contextvars().get("request_id"),
        }

    return app


async def get_echo(headers: dict[str, str] | None = None) -> Response:
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/echo", headers=headers)


async def test_generates_an_id_and_exposes_it_to_handlers_logs_and_the_client():
    response = await get_echo()
    request_id = response.headers["X-Request-ID"]
    assert GENERATED.fullmatch(request_id)
    assert response.json() == {"state": request_id, "log_context": request_id}


async def test_keeps_a_well_formed_id_sent_by_the_client():
    response = await get_echo({"X-Request-ID": "build-1234.a_b"})
    assert response.headers["X-Request-ID"] == "build-1234.a_b"
    assert response.json()["state"] == "build-1234.a_b"


@pytest.mark.parametrize("hostile", ["has space", "x" * 65, '{"forged":true}', "semi;colon"])
async def test_replaces_a_malformed_id_sent_by_the_client(hostile):
    response = await get_echo({"X-Request-ID": hostile})
    assert GENERATED.fullmatch(response.headers["X-Request-ID"])


async def test_log_context_is_cleared_after_the_request():
    await get_echo()
    assert "request_id" not in structlog.contextvars.get_contextvars()

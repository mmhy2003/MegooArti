import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from megooarti.errors import ApiError


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    @router.get("/conflict")
    async def conflict() -> None:
        raise ApiError(409, "conflict", "A repository with this name already exists.")

    @router.get("/items/{number}")
    async def item(number: int) -> dict[str, int]:
        return {"number": number}

    app.include_router(router)
    return app


def assert_error(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


async def test_unknown_route(client):
    assert_error(await client.get("/api/v1/nope"), 404, "not_found")


async def test_wrong_method(client):
    assert_error(await client.post("/api/v1/status/live"), 405, "method_not_allowed")


async def test_api_error(client):
    error = assert_error(await client.get("/_test/conflict"), 409, "conflict")
    assert error["message"] == "A repository with this name already exists."
    assert error["details"] == []


async def test_validation_error_lists_the_offending_field(client):
    error = assert_error(await client.get("/_test/items/abc"), 422, "validation_error")
    assert [detail["field"] for detail in error["details"]] == ["path.number"]
    assert error["details"][0]["message"]


async def test_unhandled_exception_reveals_nothing_internal(client):
    response = await client.get("/_test/boom")
    error = assert_error(response, 500, "internal_error")
    assert error["message"] == "An unexpected error occurred."
    assert "secret detail" not in response.text
    assert "RuntimeError" not in response.text


async def test_unhandled_exception_does_not_escape_to_the_server(app):
    transport = ASGITransport(app=app)  # re-raises anything the application lets through
    async with AsyncClient(transport=transport, base_url="http://test") as strict:
        response = await strict.get("/_test/boom")

    assert_error(response, 500, "internal_error")


async def test_validation_errors_are_documented_in_the_standard_format(client):
    document = (await client.get("/api/v1/openapi.json")).json()

    assert "default" in document["paths"]["/_test/items/{number}"]["get"]["responses"]
    assert "HTTPValidationError" not in document["components"]["schemas"]

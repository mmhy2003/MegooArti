import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def test_liveness(client):
    response = await client.get("/api/v1/status/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


async def test_openapi_document_is_served(client):
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "MegooArti"
    assert "/api/v1/status/live" in document["paths"]


async def test_interactive_documentation_is_served(client):
    response = await client.get("/api/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_settings_are_available_on_the_app(app, settings):
    assert app.state.settings is settings


async def test_statement_errors_do_not_reveal_bound_parameters(app, client):
    with pytest.raises(DBAPIError) as caught:
        async with app.state.engine.connect() as connection:
            await connection.execute(
                text("SELECT 1 / 0, CAST(:token AS text)"), {"token": "tok_SECRET_123"}
            )

    assert "tok_SECRET_123" not in str(caught.value)


async def test_openapi_documents_the_error_format(client):
    document = (await client.get("/api/v1/openapi.json")).json()

    responses = document["paths"]["/api/v1/status/live"]["get"]["responses"]
    assert responses["default"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    fields = document["components"]["schemas"]["ErrorBody"]["properties"]
    assert set(fields) == {"code", "message", "details", "request_id"}

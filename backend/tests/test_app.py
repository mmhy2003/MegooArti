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

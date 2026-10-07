from megooarti.config import Settings
from megooarti.main import create_app
from tests.clients import client_for

READY = "/api/v1/status/ready"


async def test_ready_when_the_database_is_reachable_and_migrated(client):
    response = await client.get(READY)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "schema": "ok"}}


async def test_not_ready_when_the_schema_is_behind_the_code(empty_database):
    app = create_app(Settings(_env_file=None, database_url=empty_database))

    async with client_for(app) as client:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "schema": "out_of_date"},
    }


async def test_not_ready_when_the_database_is_unreachable():
    nowhere = "postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/megooarti"
    app = create_app(Settings(_env_file=None, database_url=nowhere))

    async with client_for(app) as client:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "unreachable", "schema": "unknown"},
    }


async def test_liveness_does_not_depend_on_the_database():
    nowhere = "postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/megooarti"
    app = create_app(Settings(_env_file=None, database_url=nowhere))

    async with client_for(app) as client:
        response = await client.get("/api/v1/status/live")

    assert response.status_code == 200

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from megooarti.pagination import Page, PageParams, page

NUMBERS = list(range(1, 301))


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/numbers", response_model=Page[int])
    async def numbers(params: PageParams = Depends()) -> dict:
        chosen = NUMBERS[params.offset : params.offset + params.limit]
        return page(chosen, len(NUMBERS), params)

    return app


async def get_numbers(query: str = ""):
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        return await client.get(f"/numbers{query}")


async def test_default_page_is_the_first_fifty():
    body = (await get_numbers()).json()
    assert body["items"] == NUMBERS[:50]
    assert (body["total"], body["limit"], body["offset"]) == (300, 50, 0)


async def test_limit_and_offset_select_a_window():
    body = (await get_numbers("?limit=3&offset=10")).json()
    assert body == {"items": [11, 12, 13], "total": 300, "limit": 3, "offset": 10}


@pytest.mark.parametrize("query", ["?limit=0", "?limit=201", "?offset=-1"])
async def test_out_of_range_values_are_rejected(query):
    assert (await get_numbers(query)).status_code == 422

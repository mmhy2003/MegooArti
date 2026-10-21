"""Many readers of one uncached file, with real concurrent database sessions."""

import asyncio

from starlette.requests import Request

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Repository
from megooarti.repositories.proxy import handle_proxy
from tests.repositories.conftest import someone
from tests.repositories.fake_remote import FakeRemote
from tests.storage.test_races import Factory, run

CONTENT = b"a large file, slowly served" * 1000


def test_many_readers_of_one_uncached_file_ask_the_remote_once(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        async with factory() as db:
            repository = await service.create_repository(
                db,
                name="mirror",
                format="raw",
                type="proxy",
                online=True,
                blob_store=None,
                proxy={"remote_url": "http://remote.test/files"},
            )
            await db.commit()
        fake = FakeRemote()
        fake.files["files/big.bin"] = CONTENT
        fake.delay = 0.2
        http = fake.client()

        async def read_once() -> bytes:
            async with factory() as db:
                mirror = await db.get(Repository, repository.id)
                reader = someone("repository:raw:mirror:read")
                context = await build_context(db, settings, mirror, reader, outbound=lambda: http)
                request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
                response = await handle_proxy(context, request, "big.bin")
                return b"".join([chunk async for chunk in response.body_iterator])

        try:
            bodies = await asyncio.gather(*(read_once() for _ in range(6)))
        finally:
            await http.aclose()

        assert bodies == [CONTENT] * 6
        assert fake.paths() == ["/files/big.bin"]

    run(empty_database, tmp_path, scenario)

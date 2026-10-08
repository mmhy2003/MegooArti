from starlette.responses import Response

from megooarti.repositories import formats, service
from megooarti.repositories.dispatch import ENGINES
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic, error_code


def test_hosted_repositories_have_an_engine():
    assert "hosted" in ENGINES


async def test_a_repository_of_a_type_with_no_engine_is_unavailable(client, make_user, db):
    await make_user("root", roles=["admin"])
    db.add(Repository(name="odd", name_key="odd", format="raw", type="mystery"))
    await db.commit()

    response = await client.get("/repository/odd/a.bin", headers=basic("root", PASSWORD))

    assert (response.status_code, error_code(response)) == (503, "repository_unavailable")


class Answering(Format):
    """A format that answers for its own proxy and group repositories."""

    name = "raw"

    async def handle_proxy(self, context, request, path):
        return Response(f"proxy hook: {path}")

    async def handle_group(self, context, request, path, serve):
        return Response(f"group hook: {path}")


async def test_a_format_answers_for_its_proxy_and_group_repositories(
    client, make_user, db, mirror, fake_remote, monkeypatch
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    await service.create_repository(
        db,
        name="all",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["mirror"]},
    )
    await db.commit()
    monkeypatch.setitem(formats._registry, "raw", Answering())

    through_proxy = await client.get("/repository/mirror/a/b.bin", headers=root)
    through_group = await client.get("/repository/all/a/b.bin", headers=root)

    assert through_proxy.text == "proxy hook: a/b.bin"
    assert through_group.text == "group hook: a/b.bin"

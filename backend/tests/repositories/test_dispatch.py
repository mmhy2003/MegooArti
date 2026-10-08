from megooarti.repositories.dispatch import ENGINES
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

"""Images by selector permissions (spec 10): a pull is checked at the path of the
registry's request, and the catalog lists the images a selector reaches."""

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import error_code, push_image


async def test_a_selector_pulls_the_images_it_matches_and_lists_only_them(
    client, images, root, make_user, db
):
    await push_image(client, root, "team/app", "1.0", "ours")
    await push_image(client, root, "secret/tool", "1.0", "theirs")
    db.add(ContentSelector(name="team", expression='path =^ "/team/"'))
    await roles.create_role(db, "team-pullers", "", ["selector:team:docker:images:read"], [])
    await db.commit()
    await make_user("puller", roles=["team-pullers"])
    puller = basic("puller", PASSWORD)

    allowed = await client.get("/v2/images/team/app/manifests/1.0", headers=puller)
    denied = await client.get("/v2/images/secret/tool/manifests/1.0", headers=puller)
    catalog = await client.get("/v2/_catalog", headers=puller)

    assert allowed.status_code == 200
    assert (denied.status_code, error_code(denied)) == (403, "DENIED")
    assert catalog.json() == {"repositories": ["images/team/app"]}

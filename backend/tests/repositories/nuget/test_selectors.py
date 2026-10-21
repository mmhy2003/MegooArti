"""NuGet by selector permissions (spec 10): a package is served only where the path it is
kept at may be read, whatever address it is asked for by (the V2 download too)."""

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg

URL = "/repository/nuget-hosted"


async def test_a_package_hidden_by_a_selector_is_not_served_by_another_address(
    client, hosted, root, make_user, db
):
    assert (await push(client, root, nupkg("Secret.Lib", "1.0.0"))).status_code == 201
    assert (await push(client, root, nupkg("Open.Lib", "1.0.0"))).status_code == 201
    db.add(ContentSelector(name="open", expression='not path =^ "/v3/package/secret.lib/"'))
    await roles.create_role(db, "open", "", ["selector:open:nuget:nuget-hosted:read"], [])
    await db.commit()
    await make_user("ola", roles=["open"])
    ola = basic("ola", PASSWORD)

    direct = await client.get(
        f"{URL}/v3/package/secret.lib/1.0.0/secret.lib.1.0.0.nupkg", headers=ola
    )
    by_v2 = await client.get(f"{URL}/package/Secret.Lib/1.0.0", headers=ola)
    open_by_v2 = await client.get(f"{URL}/package/Open.Lib/1.0.0", headers=ola)

    assert direct.status_code == 403
    assert by_v2.status_code == 403, by_v2.status_code
    assert open_by_v2.status_code == 200

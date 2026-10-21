"""npm by selector permissions (spec 10): a package's dist-tags are changed only by whoever
may write where they are kept, and a tarball asked for by another spelling is served only
where it may be read."""

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.accounts import PASSWORD, basic
from tests.repositories.npm.conftest import URL, publish


async def test_dist_tags_change_only_where_the_writer_may_write(
    client, registry, root, make_user, db
):
    for package in ("@acme/app", "@secret/pkg"):
        for version in ("1.0.0", "2.0.0"):
            assert (await publish(client, root, package, version)).status_code == 201
    db.add(
        ContentSelector(name="acme", expression='path =^ "/@acme/" or path =^ "/-/package/@acme/"')
    )
    await roles.create_role(db, "acme", "", ["selector:acme:npm:npm:*"], [])
    await db.commit()
    await make_user("ace", roles=["acme"])
    ace = basic("ace", PASSWORD)

    ours = await client.put(
        f"{URL}/-/package/@acme%2fapp/dist-tags/latest", json="1.0.0", headers=ace
    )
    theirs = await client.put(
        f"{URL}/-/package/@secret%2fpkg/dist-tags/latest", json="1.0.0", headers=ace
    )
    left = await client.get(f"{URL}/-/package/@secret%2fpkg/dist-tags", headers=root)

    assert ours.status_code == 200
    assert theirs.status_code == 403
    assert left.json() == {"latest": "2.0.0"}


async def test_a_tarball_asked_for_with_a_revision_is_served_only_where_it_may_be_read(
    client, registry, root, make_user, db
):
    assert (await publish(client, root, "tool", "1.0.0")).status_code == 201
    db.add(ContentSelector(name="no-tool", expression='not path == "/tool/-/tool-1.0.0.tgz"'))
    await roles.create_role(db, "no-tool", "", ["selector:no-tool:npm:npm:read"], [])
    await db.commit()
    await make_user("nat", roles=["no-tool"])
    nat = basic("nat", PASSWORD)

    straight = await client.get(f"{URL}/tool/-/tool-1.0.0.tgz", headers=nat)
    revised = await client.get(f"{URL}/tool/-/tool-1.0.0.tgz/-rev/1-abc", headers=nat)

    assert straight.status_code == 403
    assert revised.status_code == 403, revised.status_code

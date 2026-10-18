"""The formats this server has, and the public repository each gives a new proxy:
what the web form and an agent make repositories with (MCP spec 6.2)."""

import pytest

from megooarti.repositories.formats import format_names, get_format
from tests.accounts import PASSWORD, basic

NUGET = "https://api.nuget.org/v3/index.json"
CHOCOLATEY = "https://community.chocolatey.org/api/v2/"


async def test_every_format_is_listed_with_its_types_and_public_remotes(client, make_user):
    await make_user("dev")

    answer = await client.get("/api/v1/formats", headers=basic("dev", PASSWORD))

    assert answer.status_code == 200, answer.text
    listed = {item["name"]: item for item in answer.json()["items"]}
    assert sorted(listed) == sorted(format_names())
    assert listed["maven"]["public_remotes"] == {"": "https://repo1.maven.org/maven2"}
    assert listed["nuget"]["public_remotes"] == {"": NUGET, "v3": NUGET, "v2": CHOCOLATEY}
    assert listed["raw"]["public_remotes"] == {}
    assert listed["yum"]["public_remotes"] == {}
    assert listed["docker"]["types"] == ["group", "hosted", "proxy"]


async def test_the_formats_are_not_told_to_whoever_is_not_signed_in(client):
    assert (await client.get("/api/v1/formats")).status_code == 401


@pytest.mark.parametrize(
    ("name", "config", "remote"),
    [
        ("maven", {}, "https://repo1.maven.org/maven2"),
        ("npm", {}, "https://registry.npmjs.org"),
        ("pypi", {}, "https://pypi.org"),
        ("docker", {}, "https://registry-1.docker.io"),
        ("apt", {"suite": "stable"}, "http://deb.debian.org/debian"),
        ("apk", {}, "https://dl-cdn.alpinelinux.org/alpine"),
        ("nuget", {}, NUGET),
        ("nuget", {"protocol": "v3"}, NUGET),
        ("nuget", {"protocol": "v2"}, CHOCOLATEY),
        ("yum", {}, None),
        ("raw", {}, None),
    ],
)
def test_a_proxy_with_these_settings_is_given_its_formats_public_remote(name, config, remote):
    handler = get_format(name)
    assert handler is not None

    assert handler.public_remote(config) == remote

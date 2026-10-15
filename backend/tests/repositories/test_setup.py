"""How a machine is set up to use a repository: given with the repository, ready to copy."""

import pytest

from megooarti.repositories import service
from tests.accounts import PASSWORD, basic

CONTENT = "/api/v1/content"
APT_KEYS = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str, type: str = "hosted", **settings):
    if type == "proxy":
        settings.setdefault("proxy", {"remote_url": "https://remote.test/mirror"})
    made = await service.create_repository(
        db,
        name=name,
        format=format,
        type=type,
        online=True,
        blob_store=None if type == "group" else "default",
        **settings,
    )
    await db.commit()
    return made


async def setup(client, root, name: str) -> list[dict]:
    view = await client.get(f"{CONTENT}/{name}", headers=root)
    assert view.status_code == 200, view.text
    return view.json()["setup"]


async def test_an_apt_repository_says_its_key_its_suite_and_how_apt_signs_in(client, db, root):
    await create(db, "apt-hosted", "apt", format_config={"suite": "trixie"})

    (said,) = await setup(client, root, "apt-hosted")

    assert (said["label"], said["language"]) == ("apt", "shell")
    assert said["text"] == (
        'sudo curl -fsS -u "$MEGOOARTI_USER:$MEGOOARTI_TOKEN" -o /etc/apt/keyrings/apt-hosted.asc '
        "https://test/repository/apt-hosted/public.key\n"
        'echo "deb [signed-by=/etc/apt/keyrings/apt-hosted.asc] '
        'https://test/repository/apt-hosted trixie main" \\\n'
        "  | sudo tee /etc/apt/sources.list.d/apt-hosted.list > /dev/null\n"
        "printf 'machine test\\nlogin %s\\npassword %s\\n' \\\n"
        '  "$MEGOOARTI_USER" "$MEGOOARTI_TOKEN" \\\n'
        "  | sudo tee /etc/apt/auth.conf.d/apt-hosted.conf > /dev/null\n"
        "sudo chmod 600 /etc/apt/auth.conf.d/apt-hosted.conf\n"
        "sudo apt-get update"
    )


async def test_an_apt_group_or_proxy_leaves_the_suite_and_a_proxy_the_keyring_to_fill_in(
    client, db, root
):
    await create(db, "apt-hosted", "apt")
    await create(db, "apt-debian", "apt", "proxy")
    await create(db, "apt-all", "apt", "group", group={"members": ["apt-hosted"]})

    (group,) = await setup(client, root, "apt-all")
    (proxy,) = await setup(client, root, "apt-debian")

    assert "apt-all <suite> main" in group["text"]
    assert "/etc/apt/keyrings/apt-all.asc" in group["text"]
    assert "public.key" not in proxy["text"]
    assert "signed-by=/usr/share/keyrings/<distribution>-archive-keyring.gpg" in proxy["text"]


async def test_apt_is_told_to_send_credentials_over_plain_http_where_the_address_is_so(
    client, db, root
):
    await create(db, "apt-hosted", "apt")

    (said,) = (await client.get(f"http://plain.test{CONTENT}/apt-hosted", headers=root)).json()[
        "setup"
    ]

    assert "printf 'machine http://plain.test\\nlogin" in said["text"]


@pytest.mark.parametrize(
    ("type", "made", "baseurl", "checks"),
    [
        (
            "hosted",
            {},
            "baseurl=https://test/repository/yum-x/\n",
            ("repo_gpgcheck=1", "gpgcheck=0"),
        ),
        (
            "hosted",
            {"format_config": {"repodata_depth": 2}},
            "baseurl=https://test/repository/yum-x/<directory>\n",
            ("repo_gpgcheck=1", "gpgcheck=0"),
        ),
        (
            "proxy",
            {},
            "baseurl=https://test/repository/yum-x/\n",
            ("repo_gpgcheck=0", "gpgcheck=1"),
        ),
        (
            "group",
            {"group": {"members": []}},
            "baseurl=https://test/repository/yum-x/\n",
            ("repo_gpgcheck=1", "gpgcheck=1"),
        ),
    ],
)
async def test_a_yum_repository_says_its_key_and_its_repo_file(
    client, db, root, type, made, baseurl, checks
):
    await create(db, "yum-x", "yum", type, **made)

    (said,) = await setup(client, root, "yum-x")

    assert said["label"] == "dnf"
    assert said["text"].startswith(
        "sudo tee" if type == "proxy" else 'sudo curl -fsS -u "$MEGOOARTI_USER:$MEGOOARTI_TOKEN"'
    )
    assert baseurl in said["text"]
    for check in checks:
        assert f"\n{check}\n" in said["text"]
    assert said["text"].endswith("sudo chmod 600 /etc/yum.repos.d/yum-x.repo")


async def test_an_apk_repository_says_its_key_under_the_name_apk_finds_it_by(client, db, root):
    await create(db, "apk-hosted", "apk")
    await create(db, "apk-alpine", "apk", "proxy")

    (hosted,) = await setup(client, root, "apk-hosted")
    (proxy,) = await setup(client, root, "apk-alpine")

    assert hosted["text"] == (
        "wget -q -O /etc/apk/keys/megooarti-apk-hosted.rsa.pub "
        '"https://$MEGOOARTI_USER:$MEGOOARTI_TOKEN@test/repository/apk-hosted/'
        'megooarti-apk-hosted.rsa.pub"\n'
        'echo "https://$MEGOOARTI_USER:$MEGOOARTI_TOKEN@test/repository/apk-hosted/<directory>" '
        ">> /etc/apk/repositories\n"
        "chmod 600 /etc/apk/repositories\n"
        "apk update"
    )
    assert proxy["text"].startswith('echo "https://$MEGOOARTI_USER:$MEGOOARTI_TOKEN@test/')


async def test_a_format_whose_clients_need_the_address_alone_says_nothing_more(client, db, root):
    await create(db, "files", "raw")

    assert await setup(client, root, "files") == []

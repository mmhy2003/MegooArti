"""apt, on Debian and on Ubuntu, against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the two images, and for the proxies of Debian's and Ubuntu's mirrors. Each run of apt is
a new container, whose own sources are taken away so that it reaches nothing but the
stack.
"""

import base64
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

# The two distributions, by the version each was tested with.
IMAGES = {"debian": "debian:13", "ubuntu": "ubuntu:26.04"}
MIRRORS = {"debian": "http://deb.debian.org/debian", "ubuntu": "http://archive.ubuntu.com/ubuntu"}
KEYRINGS = {
    "debian": "/usr/share/keyrings/debian-archive-keyring.gpg",
    "ubuntu": "/usr/share/keyrings/ubuntu-archive-keyring.gpg",
}
NETWORK = f"{PROJECT}_default"
HOSTED = "apt-hosted"
# What an account that installs and publishes gets: everything on APT repositories.
USERNAME = "ci"
PASSWORD = "installs-debian-packages"
PACKAGE = "megooarti-hello"

# Builds `/out/<package>_<version>_all.deb` with dpkg-deb, which every Debian image has.
BUILD = """
set -e
mkdir -p p/DEBIAN p/usr/bin
printf '#!/bin/sh\\necho "hello from %s %s"\\n' "$1" "$2" > "p/usr/bin/$1"
chmod 755 "p/usr/bin/$1"
control=p/DEBIAN/control
printf 'Package: %s\\nVersion: %s\\nArchitecture: all\\n' "$1" "$2" > $control
printf 'Maintainer: CI <ci@example.com>\\nDescription: Says hello\\n' >> $control
printf ' A package built by the tests of MegooArti.\\n' >> $control
dpkg-deb --root-owner-group --build p "/out/$1_$2_all.deb"
"""

# Sets apt up to reach nothing but one repository of the stack, as `ci`.
# `with_apt <keyring> <repository> <suite> [<suite> ...]`
SETUP = f"""
with_apt() {{
  rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*
  keyring=$1 repository=$2
  shift 2
  for suite in "$@"; do
    echo "deb [signed-by=$keyring] http://gateway/repository/$repository $suite main"
  done > /etc/apt/sources.list.d/megooarti.list
  auth=/etc/apt/auth.conf.d/megooarti.conf
  printf 'machine http://gateway\\nlogin {USERNAME}\\npassword {PASSWORD}\\n' > $auth
  chmod 600 $auth
}}
. /etc/os-release
export DEBIAN_FRONTEND=noninteractive
"""


def apt(distribution: str, directory: Path, script: str):
    """Run a shell script in a distribution's image, beside the stack, with `directory`."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        IMAGES[distribution],
        "sh",
        "-c",
        f"{SETUP}\n{script}",
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def send(method: str, path: str, data: bytes | None = None) -> tuple[int, bytes]:
    """A request to a repository from outside, as `ci`: (status, body)."""
    credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{path}",
        method=method,
        data=data,
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@pytest.fixture(scope="module")
def repositories(administrator) -> None:
    """A hosted APT repository, a proxy of each mirror, and the account `ci`."""
    made = [
        {"name": HOSTED, "format": "apt", "type": "hosted"},
        *(
            {
                "name": f"apt-{distribution}",
                "format": "apt",
                "type": "proxy",
                # Not left alone after one failure: the internet may be slow once.
                "proxy": {"remote_url": mirror, "auto_block": False},
            }
            for distribution, mirror in MIRRORS.items()
        ),
    ]
    role = {"name": "apt-users", "permissions": ["repository:apt"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["apt-users"],
        "must_change_password": False,
    }
    for body in made:
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    for path, body in (("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer


def build(work: Path, package: str, version: str) -> bytes:
    """A package of our own, built with dpkg-deb in Debian's image."""
    (work / "build.sh").write_text(BUILD, encoding="utf-8", newline="\n")
    built = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--volume",
            f"{work}:/out",
            "--workdir",
            "/tmp",
            IMAGES["debian"],
            "sh",
            "/out/build.sh",
            package,
            version,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, said(built)
    return (work / f"{package}_{version}_all.deb").read_bytes()


def key_of(repository: str, work: Path) -> None:
    """Save a repository's public key where a client finds it, as `<repository>.asc`."""
    status, key = send("GET", f"{repository}/public.key")
    assert status == 200
    (work / f"{repository}.asc").write_bytes(key)


@pytest.fixture(scope="module")
def published(repositories, tmp_path_factory) -> Path:
    """Our package, built with dpkg-deb and uploaded. Returns where its public key is."""
    work = tmp_path_factory.mktemp("apt")
    status, answer = send("PUT", f"{HOSTED}/", build(work, PACKAGE, "1.0"))
    assert status == 201, answer
    status, key = send("GET", f"{HOSTED}/public.key")
    assert status == 200
    (work / "megooarti.asc").write_bytes(key)
    return work


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_apt_installs_a_package_uploaded_to_a_hosted_repository(published, distribution):
    installed = apt(
        distribution,
        published,
        f"with_apt /src/megooarti.asc {HOSTED} stable"
        f" && apt-get update && apt-get install -y {PACKAGE} && {PACKAGE}",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == f"hello from {PACKAGE} 1.0"


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_apt_refuses_a_repository_signed_with_a_key_it_was_not_given(published, distribution):
    refused = apt(
        distribution,
        published,
        f"with_apt {KEYRINGS[distribution]} {HOSTED} stable && apt-get update",
    )

    assert refused.returncode != 0, said(refused)
    assert "NO_PUBKEY" in refused.stdout + refused.stderr or "not signed" in refused.stderr


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_apt_installs_a_public_package_through_a_proxy_of_its_mirror(published, distribution):
    installed = apt(
        distribution,
        published,
        f'with_apt {KEYRINGS[distribution]} apt-{distribution} "$VERSION_CODENAME"'
        " && apt-get update && apt-get install -y hello && hello",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == "Hello, world!"


# --- Groups ---------------------------------------------------------------------------

ADMIN = "admin:'a brand new password'"  # what the `administrator` fixture made it
SHARED = "megooarti-shared"
# The guide's commands, as an administrator types them, against the stack: a proxy of
# Debian with Debian's keys, armoured by GnuPG.
GUIDE = f"""
set -e
apt-get update -qq && apt-get install -y -qq gpg jq curl > /dev/null
keys=$(gpg --no-default-keyring --keyring /usr/share/keyrings/debian-archive-keyring.gpg \\
  --export --armor)
jq -n --arg keys "$keys" '{{
  name: "apt-debian-keyed", format: "apt", type: "proxy",
  proxy: {{remote_url: "http://deb.debian.org/debian", auto_block: false}},
  format_config: {{remote_keys: $keys}}
}}' | curl -fsS -u {ADMIN} -H 'Content-Type: application/json' -d @- \\
  http://gateway/api/v1/repositories > /dev/null
echo made
"""


def made(administrator, body: dict) -> None:
    status, _, answer = call("POST", "/repositories", body, administrator)
    assert status == 201, answer


@pytest.fixture(scope="module")
def keyed(published, administrator) -> None:
    """A proxy of Debian made with the guide's commands, with Debian's keys."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", NETWORK, IMAGES["debian"], "sh", "-c", GUIDE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert result.stdout.strip().endswith("made"), said(result)


@pytest.fixture(scope="module")
def groups(keyed, published, administrator) -> Path:
    """Three groups, with their keys saved beside the hosted repository's.

    `apt-public`: the hosted repository (suite stable) and the proxy: `trixie` is Debian's
    alone, and `stable`, which Debian's mirror has as well, is both members'.
    `apt-merged`: a hosted repository whose suite is trixie too, and the proxy.
    `apt-wrong`: that one, and a proxy of Debian given a key Debian does not sign with.
    """
    made(
        administrator,
        {
            "name": "apt-trixie",
            "format": "apt",
            "type": "hosted",
            "format_config": {"suite": "trixie"},
        },
    )
    status, answer = send("PUT", "apt-trixie/", build(published, SHARED, "1.0"))
    assert status == 201, answer
    _, _, hosted_key = call("GET", "/repositories/apt-hosted/signing-key", headers=administrator)
    made(
        administrator,
        {
            "name": "apt-debian-wrong",
            "format": "apt",
            "type": "proxy",
            "proxy": {"remote_url": MIRRORS["debian"], "auto_block": False},
            # A key Debian does not sign with: the hosted repository's own.
            "format_config": {"remote_keys": hosted_key["public_key"]},
        },
    )
    for name, members in (
        ("apt-public", [HOSTED, "apt-debian-keyed"]),
        ("apt-merged", ["apt-trixie", "apt-debian-keyed"]),
        ("apt-wrong", ["apt-trixie", "apt-debian-wrong"]),
    ):
        made(
            administrator,
            {"name": name, "format": "apt", "type": "group", "group": {"members": members}},
        )
        key_of(name, published)
    return published


def test_apt_installs_from_a_suite_one_member_has_and_one_both_have_through_a_group(groups):
    installed = apt(
        "debian",
        groups,
        "with_apt /src/apt-public.asc apt-public stable trixie"
        f" && apt-get update && apt-get install -y {PACKAGE} hello && {PACKAGE} && hello",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-2:] == [f"hello from {PACKAGE} 1.0", "Hello, world!"]


def test_apt_installs_from_a_suite_the_members_share_through_a_group(groups):
    installed = apt(
        "debian",
        groups,
        "with_apt /src/apt-merged.asc apt-merged trixie"
        f" && apt-get update && apt-get install -y {SHARED} hello && {SHARED} && hello",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-2:] == [f"hello from {SHARED} 1.0", "Hello, world!"]


def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_of_a_group(groups, administrator):
    installed = apt(
        "debian",
        groups,
        "with_apt /src/apt-wrong.asc apt-wrong trixie && apt-get update"
        f" && apt-get install -y {SHARED} && {SHARED} && ! apt-get install -y hello",
    )
    _, _, shown = call("GET", "/repositories/apt-debian-wrong", headers=administrator)

    assert installed.returncode == 0, said(installed)
    assert shown["status"]["last_error"].startswith("Left out of the group apt-wrong")

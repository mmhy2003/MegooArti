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
# `with_apt <keyring> <repository> <suite>`
SETUP = f"""
with_apt() {{
  rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*
  echo "deb [signed-by=$1] http://gateway/repository/$2 $3 main" \\
    > /etc/apt/sources.list.d/megooarti.list
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


@pytest.fixture(scope="module")
def published(repositories, tmp_path_factory) -> Path:
    """Our package, built with dpkg-deb and uploaded. Returns where its public key is."""
    work = tmp_path_factory.mktemp("apt")
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
            PACKAGE,
            "1.0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, said(built)
    package = (work / f"{PACKAGE}_1.0_all.deb").read_bytes()

    status, answer = send("PUT", f"{HOSTED}/", package)
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

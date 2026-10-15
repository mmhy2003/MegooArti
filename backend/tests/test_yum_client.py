"""dnf, on Fedora and on Rocky Linux, against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the two images, to build a package, and for the proxies of Fedora's and Rocky's
mirrors. Each run of dnf is a new container, whose own repositories are taken away so
that it reaches nothing but the stack.
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
IMAGES = {"fedora": "fedora:44", "rocky": "rockylinux/rockylinux:10"}
MIRRORS = {
    "fedora": "http://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os",
    "rocky": "http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os",
}
KEYS = {
    "fedora": "/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-primary",
    "rocky": "/etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10",
}
NETWORK = f"{PROJECT}_default"
HOSTED = "yum-hosted"
# What an account that installs and publishes gets: everything on YUM repositories.
USERNAME = "ci"
PASSWORD = "installs-rpm-packages"
PACKAGE = "megooarti-hello"

# Builds `/out/<package>-<version>-1.noarch.rpm`, of epoch 1, with rpmbuild in Fedora's image.
BUILD = """
set -e
dnf install -y -q rpm-build > /dev/null
mkdir -p /tmp/rpm/SPECS
cat > /tmp/rpm/SPECS/p.spec <<SPEC
Name: $1
Epoch: 1
Version: $2
Release: 1
Summary: Says hello
License: MIT
BuildArch: noarch
%description
A package built by the tests of MegooArti.
%install
mkdir -p %{buildroot}/usr/bin
printf '#!/bin/sh\\necho "hello from $1 $2"\\n' > %{buildroot}/usr/bin/$1
chmod 755 %{buildroot}/usr/bin/$1
%files
/usr/bin/$1
SPEC
rpmbuild --quiet --define "_topdir /tmp/rpm" -bb /tmp/rpm/SPECS/p.spec
cp /tmp/rpm/RPMS/noarch/*.rpm /out/
"""

# Sets dnf up to reach nothing but one repository of the stack, as `ci`.
# `with_dnf <repository path> <key> <repo_gpgcheck> <gpgcheck>`
SETUP = f"""
with_dnf() {{
  rm -f /etc/yum.repos.d/*
  cat > /etc/yum.repos.d/megooarti.repo <<REPO
[megooarti]
name=MegooArti
baseurl=http://gateway/repository/$1
username={USERNAME}
password={PASSWORD}
gpgkey=file://$2
repo_gpgcheck=$3
gpgcheck=$4
REPO
}}
"""


def dnf(distribution: str, directory: Path, script: str):
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
        timeout=1800,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def send(
    method: str, path: str, data: bytes | None = None, *, timeout: int = 60
) -> tuple[int, bytes]:
    """A request to a repository from outside, as `ci`: (status, body)."""
    credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{path}",
        method=method,
        data=data,
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@pytest.fixture(scope="module")
def repositories(administrator) -> None:
    """A hosted YUM repository at depth 2, a proxy of each mirror, and the account `ci`."""
    made = [
        {
            "name": HOSTED,
            "format": "yum",
            "type": "hosted",
            "format_config": {"repodata_depth": 2},
        },
        *(
            {
                "name": f"yum-{distribution}",
                "format": "yum",
                "type": "proxy",
                # Not left alone after one failure: the internet may be slow once.
                "proxy": {"remote_url": mirror, "auto_block": False},
            }
            for distribution, mirror in MIRRORS.items()
        ),
    ]
    role = {"name": "yum-users", "permissions": ["repository:yum"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["yum-users"],
        "must_change_password": False,
    }
    for body in made:
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    for path, body in (("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer


def build(work: Path, package: str, version: str) -> bytes:
    """A package of our own, built with rpmbuild in Fedora's image."""
    (work / "build.sh").write_text(BUILD, encoding="utf-8", newline="\n")
    built = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--volume",
            f"{work}:/out",
            IMAGES["fedora"],
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
    return (work / f"{package}-{version}-1.noarch.rpm").read_bytes()


@pytest.fixture(scope="module")
def published(repositories, tmp_path_factory) -> Path:
    """Our package, built with rpmbuild and uploaded two directories down for each
    distribution. Returns where the repository's public key is saved."""
    work = tmp_path_factory.mktemp("yum")
    package = build(work, PACKAGE, "1.0")
    for distribution in IMAGES:
        path = f"{HOSTED}/{distribution}/x86_64/{PACKAGE}-1.0-1.noarch.rpm"
        status, answer = send("PUT", path, package)
        assert status == 201, answer
    status, key = send("GET", f"{HOSTED}/public.key")
    assert status == 200
    (work / "megooarti.asc").write_bytes(key)
    return work


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_dnf_installs_a_package_uploaded_to_a_hosted_repository(published, distribution):
    installed = dnf(
        distribution,
        published,
        f"with_dnf {HOSTED}/{distribution}/x86_64 /src/megooarti.asc 1 0"
        # As the web UI says to: the name, and the version with its epoch.
        f" && dnf install -y {PACKAGE}-1:1.0-1 && {PACKAGE}",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == f"hello from {PACKAGE} 1.0"


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_dnf_refuses_metadata_signed_with_a_key_it_was_not_given(published, distribution):
    refused = dnf(
        distribution,
        published,
        f"with_dnf {HOSTED}/{distribution}/x86_64 {KEYS[distribution]} 1 0"
        f" && dnf install -y {PACKAGE}",
    )

    assert refused.returncode != 0, said(refused)
    assert "GPG signature verification error" in refused.stdout + refused.stderr, said(refused)


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_dnf_installs_a_public_package_through_a_proxy_of_its_mirror(published, distribution):
    installed = dnf(
        distribution,
        published,
        f"with_dnf yum-{distribution} {KEYS[distribution]} 0 1"
        " && dnf install -y bc && echo '6 * 7' | bc",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == "42"


# --- Groups ---------------------------------------------------------------------------

ADMIN = "admin:'a brand new password'"  # what the `administrator` fixture made it
FLAT = "yum-flat"
# The guide's commands, as an administrator types them, against the stack: a proxy of
# Rocky's BaseOS given Rocky's key, which signs its repomd.xml.
GUIDE = f"""
set -e
dnf install -y -q jq > /dev/null
keys=$(cat /etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10)
jq -n --arg keys "$keys" '{{
  name: "yum-rocky-keyed", format: "yum", type: "proxy",
  proxy: {{remote_url: "{MIRRORS["rocky"]}", auto_block: false}},
  format_config: {{remote_keys: $keys}}
}}' | curl -fsS -u {ADMIN} -H 'Content-Type: application/json' -d @- \\
  http://gateway/api/v1/repositories > /dev/null
echo made
"""


def made(administrator, body: dict) -> None:
    status, _, answer = call("POST", "/repositories", body, administrator)
    assert status == 201, answer


@pytest.fixture(scope="module")
def groups(published, administrator) -> Path:
    """Four groups, with their keys saved beside the hosted repository's.

    `yum-rocky-all` and `yum-fedora-all`: a hosted repository at depth 0 and a proxy of
    each mirror, merged at the root. `yum-pass`: the hosted repository at depth 2 and
    Rocky's proxy, which have no directory in common. `yum-wrong`: the one at depth 0,
    and a proxy of Rocky given a key Rocky does not sign with.
    """
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", NETWORK, IMAGES["rocky"], "sh", "-c", GUIDE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert result.stdout.strip().endswith("made"), said(result)
    made(administrator, {"name": FLAT, "format": "yum", "type": "hosted"})
    package = (published / f"{PACKAGE}-1.0-1.noarch.rpm").read_bytes()
    status, answer = send("PUT", f"{FLAT}/{PACKAGE}-1.0-1.noarch.rpm", package)
    assert status == 201, answer
    _, _, hosted_key = call("GET", f"/repositories/{HOSTED}/signing-key", headers=administrator)
    made(
        administrator,
        {
            "name": "yum-rocky-wrong",
            "format": "yum",
            "type": "proxy",
            "proxy": {"remote_url": MIRRORS["rocky"], "auto_block": False},
            # A key Rocky does not sign with: the hosted repository's own.
            "format_config": {"remote_keys": hosted_key["public_key"]},
        },
    )
    for name, members in (
        ("yum-rocky-all", [FLAT, "yum-rocky-keyed"]),
        ("yum-fedora-all", [FLAT, "yum-fedora"]),
        ("yum-pass", [HOSTED, "yum-rocky-keyed"]),
        ("yum-wrong", [FLAT, "yum-rocky-wrong"]),
    ):
        made(
            administrator,
            {"name": name, "format": "yum", "type": "group", "group": {"members": members}},
        )
        status, key = send("GET", f"{name}/public.key")
        assert status == 200
        (published / f"{name}.asc").write_bytes(key)
    # The first time, a group fetches its members' metadata and merges it: for Fedora's
    # whole release, a minute or more, longer than dnf waits for an answer.
    for name in ("yum-rocky-all", "yum-fedora-all"):
        status, answer = send("GET", f"{name}/repodata/repomd.xml", timeout=900)
        assert status == 200, answer
    return published


def distribution_group(distribution: str) -> str:
    return f"yum-{distribution}-all"


@pytest.mark.parametrize("distribution", sorted(IMAGES))
def test_dnf_installs_ours_and_the_mirrors_through_a_group_that_merges_them(groups, distribution):
    name = distribution_group(distribution)
    installed = dnf(
        distribution,
        groups,
        f"with_dnf {name} /src/{name}.asc 1 0"
        f" && dnf install -y {PACKAGE} bc && {PACKAGE} && echo '6 * 7' | bc",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-2:] == [f"hello from {PACKAGE} 1.0", "42"]


def test_dnf_installs_from_a_directory_one_member_of_a_group_has(groups):
    installed = dnf(
        "rocky",
        groups,
        "with_dnf yum-pass/rocky/x86_64 /src/yum-pass.asc 1 0"
        f" && dnf install -y {PACKAGE} && {PACKAGE}",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == f"hello from {PACKAGE} 1.0"


def test_a_member_signed_by_a_key_it_was_not_given_is_left_out_of_a_group(groups, administrator):
    installed = dnf(
        "rocky",
        groups,
        "with_dnf yum-wrong /src/yum-wrong.asc 1 0"
        f" && dnf install -y {PACKAGE} && {PACKAGE} && ! dnf install -y bc",
    )
    _, _, shown = call("GET", "/repositories/yum-rocky-wrong", headers=administrator)

    assert installed.returncode == 0, said(installed)
    assert shown["status"]["last_error"].startswith("Left out of the group yum-wrong")

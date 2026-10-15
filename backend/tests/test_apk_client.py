"""apk, on the two newest Alpine Linux releases, against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the two images, to build a package with abuild, and for the proxy of Alpine's mirror.
Each run of apk is a new container, whose own repositories are taken away so that it
reaches nothing but the stack.
"""

import base64
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

# The two releases, by the version each was tested with.
IMAGES = {"3.24": "alpine:3.24", "3.23": "alpine:3.23"}
MIRROR = "https://dl-cdn.alpinelinux.org/alpine"
NETWORK = f"{PROJECT}_default"
HOSTED = "apk-hosted"
KEY = f"megooarti-{HOSTED}.rsa.pub"
# What an account that installs and publishes gets: everything on apk repositories.
USERNAME = "ci"
PASSWORD = "installs-alpine-packages"
PACKAGE = "megooarti-hello"

# Builds `/out/<package>-<version>-r0.apk` with abuild, in Alpine's image, signed with a
# key made for it: one apk has not been given.
BUILD = """
set -e
apk add -q alpine-sdk > /dev/null
adduser -D builder && addgroup builder abuild
su builder -c 'abuild-keygen -a -n -q' > /dev/null 2>&1
cp /home/builder/.abuild/*.rsa.pub /etc/apk/keys/
mkdir -p /work/p
cat > /work/p/APKBUILD <<SPEC
pkgname=$1
pkgver=$2
pkgrel=0
pkgdesc="Says hello"
url="https://example.com/$1"
arch="noarch"
license="MIT"
options="!check"
package() {
\tmkdir -p "\\$pkgdir"/usr/bin
\tprintf '#!/bin/sh\\\\necho "hello from $1 $2"\\\\n' > "\\$pkgdir"/usr/bin/$1
\tchmod 755 "\\$pkgdir"/usr/bin/$1
}
SPEC
chown -R builder /work
su builder -c 'cd /work/p && abuild -q -r -P /work/out' > /dev/null 2>&1
cp /work/out/*/x86_64/$1-$2-r0.apk /out/
"""

# Sets apk up to reach nothing but one repository of the stack, as `ci`, trusting the key
# given, if one is. `with_apk <repository path> [<key file>]`
SETUP = f"""
with_apk() {{
  echo "http://{USERNAME}:{PASSWORD}@gateway/repository/$1" > /etc/apk/repositories
  if [ -n "$2" ]; then cp "$2" /etc/apk/keys/; fi
}}
"""


def apk(release: str, directory: Path, script: str):
    """Run a shell script in a release's image, beside the stack, with `directory`."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        IMAGES[release],
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
    """A hosted apk repository, a proxy of Alpine's mirror, and the account `ci`."""
    made = [
        {"name": HOSTED, "format": "apk", "type": "hosted"},
        {
            "name": "apk-alpine",
            "format": "apk",
            "type": "proxy",
            # Not left alone after one failure: the internet may be slow once.
            "proxy": {"remote_url": MIRROR, "auto_block": False},
        },
    ]
    role = {"name": "apk-users", "permissions": ["repository:apk"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["apk-users"],
        "must_change_password": False,
    }
    for body in made:
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    for path, body in (("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer


def build(work: Path, package: str, version: str) -> bytes:
    """A package of our own, built with abuild in Alpine's image."""
    (work / "build.sh").write_text(BUILD, encoding="utf-8", newline="\n")
    built = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--volume",
            f"{work}:/out",
            IMAGES["3.24"],
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
    return (work / f"{package}-{version}-r0.apk").read_bytes()


@pytest.fixture(scope="module")
def published(repositories, tmp_path_factory) -> Path:
    """Our package, built with abuild and uploaded to each release's `main` for x86_64.
    Returns where the repository's public key is saved, under the name apk finds it by."""
    work = tmp_path_factory.mktemp("apk")
    package = build(work, PACKAGE, "1.0")
    for release in IMAGES:
        path = f"{HOSTED}/v{release}/main/x86_64/{PACKAGE}-1.0-r0.apk"
        status, answer = send("PUT", path, package)
        assert status == 201, answer
    status, key = send("GET", f"{HOSTED}/{KEY}")
    assert status == 200
    (work / KEY).write_bytes(key)
    return work


@pytest.mark.parametrize("release", sorted(IMAGES))
def test_apk_installs_a_package_uploaded_to_a_hosted_repository(published, release):
    installed = apk(
        release,
        published,
        f"with_apk {HOSTED}/v{release}/main /src/{KEY} && apk add {PACKAGE}=1.0-r0 && {PACKAGE}",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == f"hello from {PACKAGE} 1.0"


@pytest.mark.parametrize("release", sorted(IMAGES))
def test_apk_refuses_an_index_signed_with_a_key_it_was_not_given(published, release):
    refused = apk(release, published, f"with_apk {HOSTED}/v{release}/main && apk update")

    assert refused.returncode != 0, said(refused)
    assert "UNTRUSTED signature" in refused.stdout + refused.stderr, said(refused)


@pytest.mark.parametrize("release", sorted(IMAGES))
def test_apk_installs_a_public_package_through_a_proxy_of_its_mirror(published, release):
    installed = apk(
        release,
        published,
        f"with_apk apk-alpine/v{release}/main && apk add bc && echo '6 * 7' | bc",
    )

    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == "42"

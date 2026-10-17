"""Chocolatey's `choco`, of its Linux image, against the built image: over V2 and over V3,
through a V2 proxy of the Chocolatey community feed, and through a group of both.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the image, and for the proxy of the community feed. Each run of `choco` is a new
container beside the stack, whose only source is one of the stack's. On Linux, `choco
install` puts a package's files in place and runs none of its scripts.
"""

from pathlib import Path

import pytest

from tests.containers import call
from tests.nuget_stack import ADDRESS, PASSWORD, USERNAME, fetch, hosted, prepare, proxy, run, said

pytestmark = pytest.mark.docker

IMAGE = "chocolatey/choco:v2.7.4-linux"
HOSTED = "nuget-hosted"
COMMUNITY = "choco-community"
GROUP = "choco-public"
PACKAGE = "megooarti-choco"
# A package of the community feed with nothing to run: Chocolatey's own extension.
FROM_COMMUNITY = "chocolatey-compatibility.extension"

NUSPEC = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2015/06/nuspec.xsd">
  <metadata>
    <id>{PACKAGE}</id>
    <version>1.0.0</version>
    <title>MegooArti Choco</title>
    <authors>MegooArti</authors>
    <description>Says hello to Chocolatey.</description>
    <tags>megooarti hello</tags>
  </metadata>
  <files>
    <file src="tools/**" target="tools" />
  </files>
</package>
"""


@pytest.fixture(scope="module")
def work(administrator, tmp_path_factory) -> tuple[Path, str]:
    """The folder `choco` works in, with the package's `.nuspec`; and the token to push
    with. A hosted repository, a V2 proxy of the community feed, and a group of both."""
    token = prepare(
        administrator,
        hosted(HOSTED),
        proxy(COMMUNITY, "https://community.chocolatey.org/api/v2/", protocol="v2"),
        {
            "name": GROUP,
            "format": "nuget",
            "type": "group",
            "group": {"members": [HOSTED, COMMUNITY]},
        },
    )
    folder = tmp_path_factory.mktemp("choco")
    (folder / f"{PACKAGE}.nuspec").write_text(NUSPEC, encoding="utf-8", newline="\n")
    (folder / "tools").mkdir()
    (folder / "tools" / "readme.txt").write_text("hello\n", encoding="utf-8", newline="\n")
    return folder, token


def choco(work: tuple[Path, str], source: str, script: str, *arguments: str):
    """A script of `choco` commands, with `source` as the one source, signed in as `ci`."""
    folder, _ = work
    setup = (
        f'choco source add --name=megooarti --source="{source}" '
        f'--user="{USERNAME}" --password="{PASSWORD}" > /dev/null && '
        "choco source disable --name=chocolatey > /dev/null && "
    )
    return run(IMAGE, folder, ["bash", "-c", setup + script, "script", *arguments])


@pytest.mark.parametrize(
    ("source", "version"),
    [(f"{ADDRESS}/{HOSTED}/", "1.0.0"), (f"{ADDRESS}/{HOSTED}/index.json", "2.0.0")],
    ids=["v2", "v3"],
)
def test_choco_packs_pushes_finds_and_installs(work, source, version):
    _, token = work
    # Over plain HTTP, `choco push` wants --force. Over V3 it reads the service index
    # with the source's credentials, saved first.
    script = (
        f"choco pack {PACKAGE}.nuspec --version {version} --outputdirectory out && "
        f'choco push out/{PACKAGE}.{version}.nupkg --source "$1" --api-key "$2" --force && '
        f"choco search {PACKAGE} --exact && "
        f"choco install {PACKAGE} --version {version} --yes && "
        f"cat /opt/chocolatey/lib/{PACKAGE}/tools/readme.txt"
    )

    done = choco(work, source, script, source, token)

    assert done.returncode == 0, said(done)
    assert f"{PACKAGE} {version}" in done.stdout
    assert "Chocolatey installed 1/1 packages." in done.stdout
    assert done.stdout.rstrip().endswith("hello")
    assert fetch(f"package/{PACKAGE}/{version}", HOSTED) == 200


def test_choco_installs_from_a_proxy_of_the_community_feed(work, administrator):
    installed = choco(work, f"{ADDRESS}/{COMMUNITY}/", f"choco install {FROM_COMMUNITY} --yes")

    assert installed.returncode == 0, said(installed)
    assert "Chocolatey installed 1/1 packages." in installed.stdout
    status, _, components = call("GET", f"/content/{COMMUNITY}/components", None, administrator)
    assert status == 200, components
    assert [item["name"] for item in components["items"]] == [FROM_COMMUNITY]


def test_choco_finds_and_installs_through_a_group_of_both(work):
    _, token = work
    # Pushed to the hosted member; found and installed, with a package of the community
    # feed's, through the group.
    script = (
        f"choco pack {PACKAGE}.nuspec --version 3.0.0 --outputdirectory out && "
        f'choco push out/{PACKAGE}.3.0.0.nupkg --source "$1" --api-key "$2" --force && '
        f"choco search {PACKAGE} --exact && "
        f"choco install {PACKAGE} --version 3.0.0 --yes && "
        f"choco install {FROM_COMMUNITY} --yes"
    )

    done = choco(work, f"{ADDRESS}/{GROUP}/", script, f"{ADDRESS}/{HOSTED}/", token)

    assert done.returncode == 0, said(done)
    assert f"{PACKAGE} 3.0.0" in done.stdout
    assert done.stdout.count("Chocolatey installed 1/1 packages.") == 2

"""`nuget.exe` under Mono, against the built image: over V2 and over V3.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access, to pull
Mono's image and to download `nuget.exe`, whose hash is checked. Each run of `nuget.exe`
is a new container beside the stack.
"""

import hashlib
import urllib.request
from pathlib import Path

import pytest

from tests.nuget_stack import ADDRESS, PASSWORD, USERNAME, fetch, hosted, prepare, run, said

pytestmark = pytest.mark.docker

IMAGE = "mono:6.12"
NUGET_EXE = "https://dist.nuget.org/win-x86-commandline/v6.14.0/nuget.exe"
NUGET_EXE_SHA256 = "92dbed160ddee0f64b901e907439e021211b428e57c089ecc12fc38dcc4bd9a5"
HOSTED = "nuget-hosted"
PACKAGE = "MegooArti.Mono"

NUSPEC = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">
  <metadata>
    <id>{PACKAGE}</id>
    <version>1.0.0</version>
    <authors>MegooArti</authors>
    <description>Says hello under Mono.</description>
  </metadata>
  <files>
    <file src="readme.txt" target="content/readme.txt" />
  </files>
</package>
"""


def config(source: str) -> str:
    """The one source, with the account `ci`: plain HTTP, which NuGet allows only to a
    source marked so."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="megooarti" value="{source}" allowInsecureConnections="true" />
  </packageSources>
  <packageSourceCredentials>
    <megooarti>
      <add key="Username" value="{USERNAME}" />
      <add key="ClearTextPassword" value="{PASSWORD}" />
    </megooarti>
  </packageSourceCredentials>
</configuration>
"""


@pytest.fixture(scope="module")
def tools(tmp_path_factory) -> Path:
    """A folder with `nuget.exe`, as dist.nuget.org has it."""
    folder = tmp_path_factory.mktemp("tools")
    with urllib.request.urlopen(NUGET_EXE, timeout=300) as response:
        data = response.read()
    assert hashlib.sha256(data).hexdigest() == NUGET_EXE_SHA256
    (folder / "nuget.exe").write_bytes(data)
    return folder


@pytest.fixture(scope="module")
def work(administrator, tools, tmp_path_factory) -> tuple[Path, str]:
    """The folder `nuget.exe` works in: the package's `.nuspec`, the sources over V2 (the
    repository's address) and over V3 (its `index.json`); and the token to push with."""
    token = prepare(administrator, hosted(HOSTED))
    folder = tmp_path_factory.mktemp("nuget")
    (folder / "Hello.nuspec").write_text(NUSPEC, encoding="utf-8", newline="\n")
    (folder / "readme.txt").write_text("hello\n", encoding="utf-8", newline="\n")
    for name, source in (("v2", f"{ADDRESS}/{HOSTED}/"), ("v3", f"{ADDRESS}/{HOSTED}/index.json")):
        written = config(source)
        (folder / f"{name}.config").write_text(written, encoding="utf-8", newline="\n")
    return folder, token


def nuget(work: tuple[Path, str], tools: Path, *arguments: str):
    folder, _ = work
    command = ["mono", "/tools/nuget.exe", *arguments, "-NonInteractive"]
    return run(IMAGE, folder, command, volumes={tools: "/tools"})


@pytest.mark.parametrize(("protocol", "version"), [("v2", "1.0.0"), ("v3", "2.0.0")])
def test_nuget_exe_packs_and_pushes(work, tools, protocol, version):
    _, token = work
    packed = nuget(
        work, tools, "pack", "Hello.nuspec", "-Version", version, "-OutputDirectory", "out"
    )
    package = f"out/{PACKAGE}.{version}.nupkg"
    pushed = nuget(
        work, tools, "push", package, "-Source", "megooarti", "-ApiKey", token,
        "-ConfigFile", f"{protocol}.config",
    )  # fmt: skip

    assert packed.returncode == 0, said(packed)
    assert pushed.returncode == 0, said(pushed)
    lower = PACKAGE.lower()
    assert fetch(f"v3/package/{lower}/{version}/{lower}.{version}.nupkg", HOSTED) == 200


@pytest.mark.parametrize("protocol", ["v2", "v3"])
def test_nuget_exe_installs_a_version_and_the_newest(work, tools, protocol):
    pinned = nuget(
        work, tools, "install", PACKAGE, "-Version", "1.0.0", "-Source", "megooarti",
        "-ConfigFile", f"{protocol}.config", "-OutputDirectory", f"pinned-{protocol}",
    )  # fmt: skip
    newest = nuget(
        work, tools, "install", PACKAGE, "-Source", "megooarti",
        "-ConfigFile", f"{protocol}.config", "-OutputDirectory", f"newest-{protocol}",
    )  # fmt: skip

    folder, _ = work
    assert pinned.returncode == 0, said(pinned)
    assert (folder / f"pinned-{protocol}" / f"{PACKAGE}.1.0.0" / "content" / "readme.txt").exists()
    assert newest.returncode == 0, said(newest)
    assert (folder / f"newest-{protocol}" / f"{PACKAGE}.2.0.0").exists()


def test_nuget_exe_lists_over_v2(work, tools):
    listed = nuget(
        work, tools, "list", "MegooArti", "-Source", "megooarti", "-ConfigFile", "v2.config",
        "-AllVersions", "-Prerelease",
    )  # fmt: skip

    assert listed.returncode == 0, said(listed)
    assert f"{PACKAGE} 1.0.0" in listed.stdout
    assert f"{PACKAGE} 2.0.0" in listed.stdout


@pytest.mark.parametrize(("protocol", "version"), [("v2", "1.0.0"), ("v3", "2.0.0")])
def test_nuget_exe_deletes_a_version(work, tools, protocol, version):
    _, token = work
    deleted = nuget(
        work, tools, "delete", PACKAGE, version, "-Source", "megooarti", "-ApiKey", token,
        "-ConfigFile", f"{protocol}.config",
    )  # fmt: skip

    assert deleted.returncode == 0, said(deleted)
    lower = PACKAGE.lower()
    assert fetch(f"v3/package/{lower}/{version}/{lower}.{version}.nupkg", HOSTED) == 404

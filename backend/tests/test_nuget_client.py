"""dotnet, of the .NET SDKs 10 and 8, against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access to pull
the two images. Each run of dotnet is a new container beside the stack, whose
`nuget.config` has no source but the stack's: nothing is fetched from nuget.org.
"""

import base64
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

# The two SDKs, by the version each was tested with.
IMAGES = {"10": "mcr.microsoft.com/dotnet/sdk:10.0", "8": "mcr.microsoft.com/dotnet/sdk:8.0"}
NETWORK = f"{PROJECT}_default"
HOSTED = "nuget-hosted"
SOURCE = f"http://gateway/repository/{HOSTED}/index.json"
# What an account that pushes and restores gets: everything on NuGet repositories.
USERNAME = "ci"
PASSWORD = "restores-dotnet-packages"
VERSION = "1.0.0"

# The stack as the one source, with the account dotnet signs in with. Plain HTTP, which
# NuGet allows only to a source marked so.
CONFIG = f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="megooarti" value="{SOURCE}" allowInsecureConnections="true" />
  </packageSources>
  <packageSourceCredentials>
    <megooarti>
      <add key="Username" value="{USERNAME}" />
      <add key="ClearTextPassword" value="{PASSWORD}" />
    </megooarti>
  </packageSourceCredentials>
</configuration>
"""

# Builds `/work/out/<id>.1.0.0.nupkg` and its `.snupkg`: a library that says hello.
PACK = f"""
set -e
cd /work
dotnet new classlib -n "$1" -o lib --force > /dev/null
cat > lib/Greeting.cs <<CODE
namespace MegooArti;
public static class Greeting {{ public static string Say() => "hello from $1"; }}
CODE
rm -f lib/Class1.cs
dotnet pack lib -c Release -o out -p:Version={VERSION} -p:Description="Says hello." \\
  -p:IncludeSymbols=true -p:SymbolPackageFormat=snupkg > /dev/null
ls out
"""

# A console project that restores the package and runs it.
RESTORE = f"""
set -e
cd /work
dotnet new console -n App -o "app-$1" --force > /dev/null
cd "app-$1"
dotnet add package "$1" --version {VERSION}
cat > Program.cs <<CODE
System.Console.WriteLine(MegooArti.Greeting.Say());
CODE
dotnet run
"""


def dotnet(sdk: str, work: Path, script: str, *arguments: str):
    """Run a shell script in an SDK's image, beside the stack, in `work` (as /work)."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{work}:/work",
        "--env",
        "DOTNET_CLI_TELEMETRY_OPTOUT=1",
        "--env",
        "DOTNET_NOLOGO=1",
        "--env",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1",
        IMAGES[sdk],
        "bash",
        "-c",
        script,
        "script",
        *arguments,
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


def fetch(path: str) -> int:
    """The status of a read of the repository from outside, as `ci`."""
    credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/{path}",
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted NuGet repository, the account `ci`, and an API token of it to push with."""
    status, _, answer = call(
        "POST",
        "/repositories",
        {"name": HOSTED, "format": "nuget", "type": "hosted"},
        administrator,
    )
    assert status == 201, answer
    role = {"name": "nuget-users", "permissions": ["repository:nuget"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["nuget-users"],
        "must_change_password": False,
    }
    for path, body in (("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer
    status, headers, session = call(
        "POST", "/auth/login", {"username": USERNAME, "password": PASSWORD}
    )
    assert status == 200, session
    signed_in = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }
    status, _, created = call("POST", "/me/tokens", {"name": "pushing"}, signed_in)
    assert status == 201, created
    return created["token"]


@pytest.fixture(scope="module")
def work(token, tmp_path_factory) -> dict[str, Path]:
    """Each SDK's own folder, with the `nuget.config` that leads to the stack, and a
    package of its own (`MegooArti.Hello.Sdk<n>`) packed there."""
    folders = {}
    for sdk in IMAGES:
        folder = tmp_path_factory.mktemp(f"dotnet{sdk}")
        (folder / "nuget.config").write_text(CONFIG, encoding="utf-8", newline="\n")
        packed = dotnet(sdk, folder, PACK, package_id(sdk))
        assert packed.returncode == 0, said(packed)
        folders[sdk] = folder
    return folders


def package_id(sdk: str) -> str:
    return f"MegooArti.Hello.Sdk{sdk}"


def lower(sdk: str) -> str:
    return package_id(sdk).lower()


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_pushes_a_package_and_its_symbols_with_an_api_key(work, token, sdk):
    pushed = dotnet(
        sdk,
        work[sdk],
        f'cd /work && dotnet nuget push "out/$1.{VERSION}.nupkg" --source megooarti --api-key "$2"',
        package_id(sdk),
        token,
    )

    assert pushed.returncode == 0, said(pushed)
    folder = f"v3/package/{lower(sdk)}/{VERSION}"
    assert fetch(f"{folder}/{lower(sdk)}.{VERSION}.nupkg") == 200
    # Pushed beside it, as the service index offers symbol packages a place.
    assert fetch(f"{folder}/{lower(sdk)}.{VERSION}.snupkg") == 200


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_a_second_push_is_refused_and_skip_duplicate_passes_over_it(work, token, sdk):
    script = (
        f'cd /work && dotnet nuget push "out/$1.{VERSION}.nupkg" --source megooarti '
        '--api-key "$2" --no-symbols'
    )
    again = dotnet(sdk, work[sdk], script, package_id(sdk), token)
    skipped = dotnet(sdk, work[sdk], f"{script} --skip-duplicate", package_id(sdk), token)

    assert again.returncode != 0, said(again)
    assert "409" in again.stdout + again.stderr or "Conflict" in again.stdout + again.stderr
    assert skipped.returncode == 0, said(skipped)


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_finds_the_package_and_restores_it_into_a_project(work, sdk):
    found = dotnet(
        sdk, work[sdk], 'cd /work && dotnet package search "$1" --source megooarti', package_id(sdk)
    )
    restored = dotnet(sdk, work[sdk], RESTORE, package_id(sdk))

    assert found.returncode == 0, said(found)
    assert package_id(sdk) in found.stdout
    assert restored.returncode == 0, said(restored)
    assert restored.stdout.splitlines()[-1] == f"hello from {package_id(sdk)}"


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_deletes_a_version(work, token, sdk):
    deleted = dotnet(
        sdk,
        work[sdk],
        f'cd /work && dotnet nuget delete "$1" {VERSION} --source megooarti --api-key "$2" '
        "--non-interactive",
        package_id(sdk),
        token,
    )

    assert deleted.returncode == 0, said(deleted)
    assert fetch(f"v3/package/{lower(sdk)}/index.json") == 404

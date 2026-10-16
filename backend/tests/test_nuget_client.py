"""dotnet, of the .NET SDKs 10 and 8, against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the two images, and for the proxy of nuget.org. Each run of dotnet is a new container
beside the stack, whose `nuget.config` has no source but one of the stack's: dotnet
reaches nuget.org only through the proxy.
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
PROXY = "nuget-org"
# What an account that pushes and restores gets: everything on NuGet repositories.
USERNAME = "ci"
PASSWORD = "restores-dotnet-packages"
VERSION = "1.0.0"


def config(repository: str, name: str = "megooarti") -> str:
    """A repository of the stack as the one source, with the account dotnet signs in
    with. Plain HTTP, which NuGet allows only to a source marked so."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="{name}" value="http://gateway/repository/{repository}/index.json"
         allowInsecureConnections="true" />
  </packageSources>
  <packageSourceCredentials>
    <{name}>
      <add key="Username" value="{USERNAME}" />
      <add key="ClearTextPassword" value="{PASSWORD}" />
    </{name}>
  </packageSourceCredentials>
</configuration>
"""


# The version of nuget.org's Json.NET the proxy's tests restore: not its newest.
JSON_NET = "13.0.1"
# A project that restores Json.NET through the proxy, and runs.
THROUGH_PROXY = f"""
set -e
cd /work
dotnet new console -n App -o app --force > /dev/null
cd app
dotnet add package Newtonsoft.Json --version {JSON_NET}
cat > Program.cs <<CODE
System.Console.WriteLine(Newtonsoft.Json.JsonConvert.SerializeObject(new {{ through = "proxy" }}));
CODE
dotnet run
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


def fetch(path: str, repository: str = HOSTED) -> int:
    """The status of a read of a repository from outside, as `ci`."""
    credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{repository}/{path}",
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted NuGet repository, a proxy of nuget.org, the account `ci`, and an API token
    of it to push with."""
    proxy = {
        "name": PROXY,
        "format": "nuget",
        "type": "proxy",
        # Not left alone after one failure: the internet may be slow once.
        "proxy": {"remote_url": "https://api.nuget.org/v3/index.json", "auto_block": False},
    }
    for body in ({"name": HOSTED, "format": "nuget", "type": "hosted"}, proxy):
        status, _, answer = call("POST", "/repositories", body, administrator)
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
        (folder / "nuget.config").write_text(config(HOSTED), encoding="utf-8", newline="\n")
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


@pytest.fixture(scope="module")
def through(token, tmp_path_factory) -> dict[str, Path]:
    """Each SDK's own folder whose one source is the proxy of nuget.org."""
    folders = {}
    for sdk in IMAGES:
        folder = tmp_path_factory.mktemp(f"proxy{sdk}")
        written = config(PROXY, "nuget-org")
        (folder / "nuget.config").write_text(written, encoding="utf-8", newline="\n")
        folders[sdk] = folder
    return folders


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_restores_a_package_of_nuget_org_through_the_proxy(through, sdk):
    restored = dotnet(sdk, through[sdk], THROUGH_PROXY)

    assert restored.returncode == 0, said(restored)
    assert restored.stdout.splitlines()[-1] == '{"through":"proxy"}'
    folder = f"v3/package/newtonsoft.json/{JSON_NET}"
    assert fetch(f"{folder}/newtonsoft.json.{JSON_NET}.nupkg", PROXY) == 200  # kept


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_searches_and_finds_newer_versions_through_the_proxy(through, sdk):
    found = dotnet(
        sdk, through[sdk], "cd /work && dotnet package search Newtonsoft.Json --source nuget-org"
    )
    # Read from the registration the proxy passes on, with its own addresses in it.
    outdated = dotnet(sdk, through[sdk], "cd /work/app && dotnet list package --outdated")

    assert found.returncode == 0, said(found)
    assert "Newtonsoft.Json" in found.stdout
    assert outdated.returncode == 0, said(outdated)
    (line,) = [line for line in outdated.stdout.splitlines() if "Newtonsoft.Json" in line]
    requested, resolved, latest = line.split()[-3:]
    assert (requested, resolved) == (JSON_NET, JSON_NET)
    assert latest != JSON_NET

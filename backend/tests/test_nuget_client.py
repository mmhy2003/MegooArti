"""dotnet, of the .NET SDKs 10 and 8, against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the two images, and for the proxy of nuget.org. Each run of dotnet is a new container
beside the stack, whose `nuget.config` has no source but one of the stack's: dotnet
reaches nuget.org only through the proxy.
"""

import subprocess
import zipfile
from pathlib import Path

import pytest

from tests import nuget_stack
from tests.containers import call
from tests.nuget_stack import PASSWORD, USERNAME, hosted, prepare, proxy, said

pytestmark = pytest.mark.docker

# The two SDKs, by the version each was tested with.
IMAGES = {"10": "mcr.microsoft.com/dotnet/sdk:10.0", "8": "mcr.microsoft.com/dotnet/sdk:8.0"}
HOSTED = "nuget-hosted"
PROXY = "nuget-org"
GROUP = "nuget-public"
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

# A version of Json.NET with a known vulnerability, of which NuGet Audit warns: NU1903.
VULNERABLE = "12.0.3"
# A project that restores it.
AUDITED = f"""
set -e
cd /work
dotnet new console -n Old -o old --force > /dev/null
cd old
dotnet add package Newtonsoft.Json --version {VULNERABLE} > /dev/null
dotnet restore --force
"""

# A project that restores a package of the hosted repository's and one of nuget.org's
# through the group, and runs.
GROUPED = f"""
set -e
cd /work
dotnet new console -n App -o app --force > /dev/null
cd app
dotnet add package "$1" --version {VERSION}
dotnet add package Newtonsoft.Json --version {JSON_NET}
cat > Program.cs <<CODE
var through = Newtonsoft.Json.JsonConvert.SerializeObject(new {{ through = "group" }});
System.Console.WriteLine(MegooArti.Greeting.Say() + " " + through);
CODE
dotnet run
"""

# dotnet-symbol, installed through the proxy of nuget.org, fetches the PDB of the SDK's
# package, `$1`, for its DLL, from the symbol server of the repository `$3`, signed in
# with the API token `$2`, as it signs in: with no user name.
DOTNET_SYMBOL = "10.0.750501"
SYMBOLS = f"""
set -e
cd /work
dotnet tool install --global dotnet-symbol --version {DOTNET_SYMBOL} \\
  --configfile tools.config > /dev/null
export PATH="$PATH:/root/.dotnet/tools"
dotnet-symbol --authenticated-server-path "$2" "http://gateway/repository/$3/symbols/" \\
  --symbols --output "symbols-$3" lib/bin/Release/*/"$1.dll"
ls "symbols-$3"
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


def dotnet(sdk: str, work: Path, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in an SDK's image, beside the stack, in `work` (as /work)."""
    return nuget_stack.run(
        IMAGES[sdk],
        work,
        ["bash", "-c", script, "script", *arguments],
        environment={"DOTNET_NOLOGO": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1"},
    )


def fetch(path: str, repository: str = HOSTED) -> int:
    """The status of a read of a repository from outside, as `ci`."""
    return nuget_stack.fetch(path, repository)


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted NuGet repository, a proxy of nuget.org, the account `ci`, and an API token
    of it to push with."""
    return prepare(
        administrator, hosted(HOSTED), proxy(PROXY, "https://api.nuget.org/v3/index.json")
    )


@pytest.fixture(scope="module")
def work(token, tmp_path_factory) -> dict[str, Path]:
    """Each SDK's own folder, with the `nuget.config` that leads to the stack, and a
    package of its own (`MegooArti.Hello.Sdk<n>`) packed there."""
    folders = {}
    for sdk in IMAGES:
        folder = tmp_path_factory.mktemp(f"dotnet{sdk}")
        (folder / "nuget.config").write_text(config(HOSTED), encoding="utf-8", newline="\n")
        tools = config(PROXY, "nuget-org")
        (folder / "tools.config").write_text(tools, encoding="utf-8", newline="\n")
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
def test_dotnet_symbol_fetches_the_packages_pdb(work, token, sdk):
    fetched, kept, pushed = symbols_of(sdk, work[sdk], token, HOSTED)

    assert fetched.returncode == 0, said(fetched)
    assert kept == pushed


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


def symbols_of(sdk: str, work: Path, token: str, repository: str):
    """The PDB dotnet-symbol fetched of the SDK's package, and the one its symbol package has."""
    fetched = dotnet(sdk, work, SYMBOLS, package_id(sdk), token, repository)
    with zipfile.ZipFile(work / "out" / f"{package_id(sdk)}.{VERSION}.snupkg") as packed:
        (name,) = [entry for entry in packed.namelist() if entry.endswith(".pdb")]
        pushed = packed.read(name)
    kept = work / f"symbols-{repository}" / f"{package_id(sdk)}.pdb"
    return fetched, kept.read_bytes() if kept.exists() else None, pushed


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


@pytest.fixture(scope="module")
def grouped(work, token, administrator, tmp_path_factory) -> dict[str, Path]:
    """A group of the hosted repository and the proxy, each SDK's package pushed to the
    hosted one (again, if it was deleted), and each SDK's own folder whose one source is
    the group."""
    group = {"name": GROUP, "format": "nuget", "type": "group"}
    group["group"] = {"members": [HOSTED, PROXY]}
    status, _, answer = call("POST", "/repositories", group, administrator)
    assert status == 201, answer
    folders = {}
    for sdk in IMAGES:
        pushed = dotnet(
            sdk,
            work[sdk],
            f'cd /work && dotnet nuget push "out/$1.{VERSION}.nupkg" --source megooarti '
            '--api-key "$2" --skip-duplicate',
            package_id(sdk),
            token,
        )
        assert pushed.returncode == 0, said(pushed)
        folder = tmp_path_factory.mktemp(f"group{sdk}")
        written = config(GROUP, GROUP)
        (folder / "nuget.config").write_text(written, encoding="utf-8", newline="\n")
        folders[sdk] = folder
    return folders


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_restores_a_pushed_package_and_one_of_nuget_org_through_a_group(grouped, sdk):
    restored = dotnet(sdk, grouped[sdk], GROUPED, package_id(sdk))

    assert restored.returncode == 0, said(restored)
    last = restored.stdout.splitlines()[-1]
    assert last == f'hello from {package_id(sdk)} {{"through":"group"}}'


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_searches_and_finds_newer_versions_through_a_group(grouped, sdk):
    found = dotnet(
        sdk,
        grouped[sdk],
        f'cd /work && dotnet package search "$1" --source {GROUP} '
        f"&& dotnet package search Newtonsoft.Json --source {GROUP}",
        package_id(sdk),
    )
    # Read from the registration the group writes from its members'.
    outdated = dotnet(sdk, grouped[sdk], "cd /work/app && dotnet list package --outdated")

    assert found.returncode == 0, said(found)
    assert package_id(sdk) in found.stdout
    assert "Newtonsoft.Json" in found.stdout
    assert outdated.returncode == 0, said(outdated)
    (line,) = [line for line in outdated.stdout.splitlines() if "Newtonsoft.Json" in line]
    assert line.split()[-1] != JSON_NET


@pytest.mark.parametrize("sdk", sorted(IMAGES))
@pytest.mark.parametrize("source", ["through", "grouped"], ids=["proxy", "group"])
def test_nuget_audit_warns_of_a_vulnerable_package_with_the_data_passed_on(request, source, sdk):
    restored = dotnet(sdk, request.getfixturevalue(source)[sdk], AUDITED)

    assert restored.returncode == 0, said(restored)
    warned = [line for line in restored.stdout.splitlines() if "NU1903" in line]
    assert warned, said(restored)
    assert "Newtonsoft.Json" in warned[0]
    assert "NU1905" not in restored.stdout  # the source had the data


@pytest.mark.parametrize("sdk", sorted(IMAGES))
def test_dotnet_symbol_fetches_the_packages_pdb_through_a_group(grouped, work, token, sdk):
    fetched, kept, pushed = symbols_of(sdk, work[sdk], token, GROUP)

    assert fetched.returncode == 0, said(fetched)
    assert kept == pushed

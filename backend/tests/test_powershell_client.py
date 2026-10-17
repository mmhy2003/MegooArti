"""PowerShell's PSResourceGet, of PowerShell 7.5, against the built image: over V2 and
over V3, and through a V2 proxy of the PowerShell Gallery.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
the image, and for the proxy of the Gallery. Each run of `pwsh` is a new container
beside the stack.
"""

from pathlib import Path

import pytest

from tests.nuget_stack import ADDRESS, PASSWORD, USERNAME, fetch, hosted, prepare, proxy, run, said

pytestmark = pytest.mark.docker

IMAGE = "mcr.microsoft.com/powershell:7.5-ubuntu-24.04"
HOSTED = "nuget-hosted"
GALLERY = "psgallery"
MODULE = "MegooArtiPS"
# A small module of the Gallery's, at a version it keeps.
FROM_GALLERY, FROM_GALLERY_VERSION = "Microsoft.PowerShell.SecretManagement", "1.1.2"

# Registers the one repository as `megooarti`, with what PSResourceGet needs told, and
# signs in as `ci` with each command.
PREAMBLE = f"""
param([string]$Uri, [string]$ApiVersion, [string]$Token, [string]$Version)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Register-PSResourceRepository -Name megooarti -Uri $Uri -ApiVersion $ApiVersion -Trusted
$password = ConvertTo-SecureString '{PASSWORD}' -AsPlainText -Force
$credential = [pscredential]::new('{USERNAME}', $password)
"""

# Publishes a module of the version asked for, finds it by a range, installs it and runs it.
PUBLISH = f"""{PREAMBLE}
New-Item -ItemType Directory -Force -Path /work/{MODULE} | Out-Null
Set-Content /work/{MODULE}/{MODULE}.psm1 `
  'function Get-MegooArtiGreeting {{ "hello from {MODULE}" }}'
New-ModuleManifest -Path /work/{MODULE}/{MODULE}.psd1 -RootModule {MODULE}.psm1 `
  -ModuleVersion $Version -Author MegooArti -Description 'Says hello.' `
  -FunctionsToExport Get-MegooArtiGreeting
Publish-PSResource -Path /work/{MODULE} -Repository megooarti -ApiKey $Token -Credential $credential
$found = Find-PSResource {MODULE} -Version "[$Version, 9.0.0]" -Repository megooarti `
  -Credential $credential
"found $($found.Name) $($found.Version)"
Install-PSResource {MODULE} -Version $Version -Repository megooarti -Credential $credential
Import-Module {MODULE}
Get-MegooArtiGreeting
"""

INSTALL = f"""{PREAMBLE}
Install-PSResource {FROM_GALLERY} -Version {FROM_GALLERY_VERSION} -Repository megooarti `
  -Credential $credential
"installed $((Get-InstalledPSResource {FROM_GALLERY}).Version)"
"""


@pytest.fixture(scope="module")
def work(administrator, tmp_path_factory) -> tuple[Path, str]:
    """The folder `pwsh` works in, with its scripts; and the token to publish with. A
    hosted repository, and a V2 proxy of the Gallery."""
    token = prepare(
        administrator,
        hosted(HOSTED),
        proxy(GALLERY, "https://www.powershellgallery.com/api/v2/", protocol="v2"),
    )
    folder = tmp_path_factory.mktemp("pwsh")
    for name, script in (("publish.ps1", PUBLISH), ("install.ps1", INSTALL)):
        (folder / name).write_text(script, encoding="utf-8", newline="\n")
    return folder, token


def pwsh(work: tuple[Path, str], script: str, *arguments: str):
    folder, _ = work
    return run(IMAGE, folder, ["pwsh", "-NoProfile", "-File", f"/work/{script}", *arguments])


@pytest.mark.parametrize(
    ("uri", "api_version", "version"),
    [
        # V2's address without its slash: PSResourceGet adds one.
        (f"{ADDRESS}/{HOSTED}", "v2", "1.0.0"),
        (f"{ADDRESS}/{HOSTED}/index.json", "v3", "2.0.0"),
    ],
    ids=["v2", "v3"],
)
def test_psresourceget_publishes_finds_and_installs_a_module(work, uri, api_version, version):
    _, token = work

    done = pwsh(
        work, "publish.ps1", "-Uri", uri, "-ApiVersion", api_version, "-Token", token,
        "-Version", version,
    )  # fmt: skip

    assert done.returncode == 0, said(done)
    assert f"found {MODULE} {version}" in done.stdout
    assert done.stdout.rstrip().endswith(f"hello from {MODULE}")
    assert fetch(f"package/{MODULE}/{version}", HOSTED) == 200


def test_psresourceget_installs_from_a_proxy_of_the_gallery(work):
    installed = pwsh(work, "install.ps1", "-Uri", f"{ADDRESS}/{GALLERY}", "-ApiVersion", "v2")

    assert installed.returncode == 0, said(installed)
    assert f"installed {FROM_GALLERY_VERSION}" in installed.stdout
    lower = FROM_GALLERY.lower()
    kept = f"v3/package/{lower}/{FROM_GALLERY_VERSION}/{lower}.{FROM_GALLERY_VERSION}.nupkg"
    assert fetch(kept, GALLERY) == 404  # kept, and served at V2's address alone
    assert fetch(f"package/{FROM_GALLERY}/{FROM_GALLERY_VERSION}", GALLERY) == 200

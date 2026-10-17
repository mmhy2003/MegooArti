"""What the tests of NuGet's clients share: the account they sign in as, its API token,
and a client run in its own image beside the stack."""

import base64
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from tests.containers import HTTP_PORT, PROJECT, call

NETWORK = f"{PROJECT}_default"
# What an account that pushes and restores gets: everything on NuGet repositories.
USERNAME = "ci"
PASSWORD = "restores-dotnet-packages"
# The stack's address, as each client is given it beside the stack.
ADDRESS = "http://gateway/repository"


def prepare(administrator: dict[str, str], *repositories: dict) -> str:
    """The repositories, the account `ci` with a role on NuGet repositories, and an API
    token of it to push with, which this returns."""
    for body in repositories:
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


def hosted(name: str = "nuget-hosted") -> dict:
    return {"name": name, "format": "nuget", "type": "hosted"}


def proxy(name: str, remote_url: str, protocol: str = "v3") -> dict:
    return {
        "name": name,
        "format": "nuget",
        "type": "proxy",
        "format_config": {"protocol": protocol},
        # Not left alone after one failure: the internet may be slow once.
        "proxy": {"remote_url": remote_url, "auto_block": False},
    }


def run(
    image: str,
    work: Path,
    command: list[str],
    *,
    volumes: dict[Path, str] | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command in a client's image, beside the stack, in `work` (as /work)."""
    mounts = [f"{work}:/work", *(f"{path}:{at}" for path, at in (volumes or {}).items())]
    settings = {
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
        **(environment or {}),
    }
    arguments = ["docker", "run", "--rm", "--network", NETWORK, "--workdir", "/work"]
    for mount in mounts:
        arguments += ["--volume", mount]
    for name, value in settings.items():
        arguments += ["--env", f"{name}={value}"]
    return subprocess.run(
        [*arguments, image, *command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def fetch(path: str, repository: str) -> int:
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

"""npm's own client against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access the
first time, to pull the Node image. Everything npm asks for comes from MegooArti.
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "node:22-slim"
NETWORK = f"{PROJECT}_default"
# The backend as a container on the Compose network sees it, and as this test does.
INSIDE = "backend:8000/repository/npm-hosted/"
OUTSIDE = f"http://127.0.0.1:{HTTP_PORT}/repository/npm-hosted"
# What a publishing account gets: everything on npm repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "publishes-and-unpublishes-npm-packages"
PLAIN = "megooarti-greeter"
SCOPED = "@megooarti/greeter"


def package(name: str, version: str, **fields) -> dict[str, str]:
    """The files of a package whose only export says which version it is."""
    manifest = {"name": name, "version": version, "main": "index.js", **fields}
    return {
        "package.json": json.dumps(manifest, indent=2),
        "index.js": f'module.exports = () => "hello from {name}@{version}";\n',
    }


def write(directory: Path, projects: dict[str, dict[str, str]], token: str) -> Path:
    """A directory with one sub-directory for each project, and npm's configuration."""
    directory.mkdir(parents=True)
    settings = [
        f"registry=http://{INSIDE}",
        f"//{INSIDE}:_authToken={token}",
        "update-notifier=false",
        "fund=false",
    ]
    (directory / "npmrc").write_text("\n".join(settings) + "\n", encoding="utf-8", newline="\n")
    for project, files in projects.items():
        for name, content in files.items():
            target = directory / project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
    return directory


def npm(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Node image, in a copy of `directory`, beside the stack."""
    setup = "cp -r /src /work && cd /work && export NPM_CONFIG_USERCONFIG=/work/npmrc"
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        IMAGE,
        "sh",
        "-c",
        f"{setup} && {script}",
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


def request(method: str, path: str, token: str | None = None, body: dict | None = None):
    """A request to the repository from outside: (status, parsed JSON body or None)."""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    sent = urllib.request.Request(
        f"{OUTSIDE}/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(sent, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted npm repository, a publishing account, and a token from signing in."""
    repository = {
        "name": "npm-hosted",
        "format": "npm",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    role = {"name": "npm-publishers", "permissions": ["repository:npm"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["npm-publishers"],
        "must_change_password": False,
    }
    for path, body in (("/repositories", repository), ("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer

    # The request `npm login` sends once it has asked for the name and the password.
    credentials = {"_id": f"org.couchdb.user:{USERNAME}", "name": USERNAME, "password": PASSWORD}
    status, answer = request("PUT", f"-/user/org.couchdb.user:{USERNAME}", body=credentials)
    assert status == 201, answer
    return answer["token"]


def test_npm_publishes_installs_changes_and_unpublishes(token, tmp_path):
    projects = {
        "first": package(PLAIN, "1.0.0", description="Says hello"),
        "second": package(PLAIN, "1.1.0", description="Says hello, again"),
        "scoped": package(SCOPED, "2.0.0"),
        "consumer": {
            "package.json": json.dumps(
                {
                    "name": "consumer",
                    "version": "1.0.0",
                    "private": True,
                    "dependencies": {PLAIN: "1.0.0", SCOPED: "^2.0.0"},
                }
            ),
            "main.js": f'console.log(require("{PLAIN}")(), require("{SCOPED}")());\n',
        },
    }
    work = write(tmp_path / "npm", projects, token)

    # Who we are, by the token that signing in gave.
    who = npm(work, "npm whoami && npm ping")
    assert who.returncode == 0, said(who)
    assert who.stdout.splitlines()[0] == USERNAME

    # Publish two versions of one package and one scoped package.
    published = npm(
        work,
        "(cd first && npm publish) && (cd scoped && npm publish)"
        " && (cd second && npm publish --tag next)",
    )
    assert published.returncode == 0, said(published)
    again = npm(work, "cd first && npm publish")
    assert again.returncode != 0, "a version was published twice despite disable_redeploy"

    # What the registry says about them.
    viewed = npm(work, f"npm view {PLAIN} versions dist-tags description --json")
    assert viewed.returncode == 0, said(viewed)
    about = json.loads(viewed.stdout)
    assert about["versions"] == ["1.0.0", "1.1.0"]
    assert about["dist-tags"] == {"latest": "1.0.0", "next": "1.1.0"}
    assert about["description"] == "Says hello"
    found = npm(work, "npm search megooarti --json")
    assert found.returncode == 0, said(found)
    assert {entry["name"] for entry in json.loads(found.stdout)} == {PLAIN, SCOPED}

    # Dist-tags and deprecation.
    changed = npm(
        work,
        f"npm dist-tag add {PLAIN}@1.1.0 stable && npm dist-tag ls {PLAIN}"
        f' && npm deprecate {PLAIN}@1.0.0 "use 1.1.0"',
    )
    assert changed.returncode == 0, said(changed)
    assert "stable: 1.1.0" in changed.stdout

    # Install both into a project, from an empty cache, and run them.
    installed = npm(work, "cd consumer && npm install && node main.js")
    assert installed.returncode == 0, said(installed)
    assert f"hello from {PLAIN}@1.0.0 hello from {SCOPED}@2.0.0" in installed.stdout
    assert "use 1.1.0" in installed.stderr  # npm warns that the version is deprecated

    # Remove one version, then a whole package.
    removed = npm(work, f"npm unpublish {PLAIN}@1.1.0 && npm unpublish {SCOPED} --force")
    assert removed.returncode == 0, said(removed)
    status, document = request("GET", PLAIN, token)
    assert (status, list(document["versions"])) == (200, ["1.0.0"])
    assert document["dist-tags"] == {"latest": "1.0.0"}
    assert request("GET", SCOPED.replace("/", "%2f"), token)[0] == 404

    # Signing out revokes the token npm was using.
    out = npm(work, "npm logout")
    assert out.returncode == 0, said(out)
    assert request("GET", "-/whoami", token)[0] == 401


def test_npm_login_itself_gets_a_token_that_works(token, tmp_path):
    """The `npm login` command, typed into a terminal, with a revoked token still saved."""
    work = write(tmp_path / "login", {}, token="mga_revoked-long-ago")
    # npm reads the answers from a terminal, so `script` gives it one, and the answers
    # are typed with pauses, as a person would.
    typing = f"(sleep 3; echo {USERNAME}; sleep 2; echo {PASSWORD}; sleep 5)"
    login = 'script --quiet --return --command "npm login --auth-type=legacy" /dev/null'

    signed_in = npm(work, f"{typing} | {login} && npm whoami")

    assert signed_in.returncode == 0, said(signed_in)
    assert signed_in.stdout.rstrip().endswith(USERNAME)

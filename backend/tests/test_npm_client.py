"""npm's own clients against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: the
first time to pull the Node image, and every time for the proxy of registry.npmjs.org
that the last test installs through. Everything a client asks for comes from MegooArti.
"""

import base64
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call, upload

pytestmark = pytest.mark.docker

IMAGE = "node:22-slim"
NETWORK = f"{PROJECT}_default"
HOSTED = "npm-hosted"
PROXY = "npm-proxy"
GROUP = "npm-public"
# What a publishing account gets: everything on npm repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "publishes-and-unpublishes-npm-packages"
PLAIN = "megooarti-greeter"
SCOPED = "@megooarti/greeter"
# Published to the hosted repository and installed through the group.
OURS = "megooarti-grouped"
# A real public package with no dependencies, and the name of another one.
PUBLIC = "is-number"
TAKEN = "is-odd"


def inside(repository: str) -> str:
    """A repository's address as a container on the Compose network writes it in .npmrc."""
    return f"gateway/repository/{repository}/"


def package(name: str, version: str, **fields) -> dict[str, str]:
    """The files of a package whose only export says which version it is."""
    manifest = {"name": name, "version": version, "main": "index.js", **fields}
    return {
        "package.json": json.dumps(manifest, indent=2),
        "index.js": f'module.exports = () => "hello from {name}@{version}";\n',
    }


def write(
    directory: Path, projects: dict[str, dict[str, str]], token: str, repository: str = HOSTED
) -> Path:
    """A directory with one sub-directory for each project, and the clients' configuration."""
    directory.mkdir(parents=True)
    settings = [
        f"registry=http://{inside(repository)}",
        f"//{inside(repository)}:_authToken={token}",
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
    """Run a shell script in the Node image, in a copy of `directory`, beside the stack.

    Every run is a new container, so every client starts with an empty cache.
    """
    # pnpm and Yarn read the same file as npm, from the home directory.
    setup = (
        "cp -r /src /work && cd /work && cp npmrc ~/.npmrc"
        " && export NPM_CONFIG_USERCONFIG=/work/npmrc"
    )
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


def request(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    repository: str = HOSTED,
):
    """A request to a repository from outside: (status, parsed JSON body or None)."""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    sent = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{repository}/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(sent, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def sign_in(repository: str = HOSTED) -> str:
    """A token, by the request `npm login` sends once it has asked for name and password."""
    credentials = {"_id": f"org.couchdb.user:{USERNAME}", "name": USERNAME, "password": PASSWORD}
    status, answer = request(
        "PUT", f"-/user/org.couchdb.user:{USERNAME}", body=credentials, repository=repository
    )
    assert status == 201, answer
    return answer["token"]


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted npm repository, a publishing account, and a token from signing in."""
    repository = {
        "name": HOSTED,
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
    return sign_in()


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


@pytest.fixture(scope="module")
def group_token(token, administrator) -> str:
    """A proxy of the public registry and a group of the hosted repository and it.

    Returns a token from signing in at the group, which is where developers point npm.
    """
    proxy = {
        "name": PROXY,
        "format": "npm",
        "type": "proxy",
        "proxy": {"remote_url": "https://registry.npmjs.org"},
    }
    public = {
        "name": GROUP,
        "format": "npm",
        "type": "group",
        "group": {"members": [HOSTED, PROXY]},
    }
    for body in (proxy, public):
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    return sign_in(GROUP)


def test_npm_pnpm_and_yarn_install_through_a_group(group_token, tmp_path):
    consumer = {
        "package.json": json.dumps(
            {
                "name": "consumer",
                "version": "1.0.0",
                "private": True,
                "dependencies": {OURS: "1.0.0", PUBLIC: "7.0.0"},
            }
        ),
        "main.js": f'console.log(require("{OURS}")(), require("{PUBLIC}")(5));\n',
    }
    # Our own package, and our own package under a name the public registry has too.
    publishing = write(
        tmp_path / "publish",
        {"ours": package(OURS, "1.0.0"), "taken": package(TAKEN, "99.0.0")},
        group_token,
    )
    published = npm(publishing, "(cd ours && npm publish) && (cd taken && npm publish)")
    assert published.returncode == 0, said(published)

    # What the group says: the public package from the proxy, with its links here, and
    # under the name we host only what we host.
    status, public = request("GET", PUBLIC, group_token, repository=GROUP)
    assert status == 200
    assert "7.0.0" in public["versions"] and len(public["versions"]) > 5
    assert public["versions"]["7.0.0"]["dist"]["tarball"] == (
        f"http://127.0.0.1:{HTTP_PORT}/repository/{GROUP}/{PUBLIC}/-/{PUBLIC}-7.0.0.tgz"
    )
    assert request("HEAD", PUBLIC, group_token, repository=GROUP)[0] == 200
    status, taken = request("GET", TAKEN, group_token, repository=GROUP)
    assert (status, list(taken["versions"])) == (200, ["99.0.0"])
    status, upstream = request("GET", TAKEN, group_token, repository=PROXY)
    assert status == 200 and "99.0.0" not in upstream["versions"]

    # Each client installs the project from an empty cache, through the group.
    work = write(tmp_path / "install", {"consumer": consumer}, group_token, GROUP)
    expected = f"hello from {OURS}@1.0.0 true"
    clients = {
        "npm": "cd consumer && npm install && node main.js",
        # pnpm is itself installed through the group: a large package from the proxy.
        "pnpm": "npm install --global pnpm@9 && cd consumer && pnpm install && node main.js",
        # Yarn 1 sends a token for an unscoped package only when told to always send it.
        "yarn": "echo always-auth=true >> ~/.npmrc"
        " && cd consumer && yarn install --non-interactive && node main.js",
    }
    for client, script in clients.items():
        installed = npm(work, script)
        assert installed.returncode == 0, f"{client}: {said(installed)}"
        assert expected in installed.stdout, f"{client}: {said(installed)}"

    # What was installed came through the proxy, and is cached there.
    status, found = request("GET", f"-/v1/search?text={PUBLIC}", group_token, repository=PROXY)
    assert status == 200
    cached = {entry["package"]["name"]: entry["package"]["version"] for entry in found["objects"]}
    assert cached.get(PUBLIC) == "7.0.0"


def test_a_tarball_uploaded_through_the_api_installs_like_a_published_one(token, tmp_path):
    """`npm pack` writes the tarball, the content API takes it, and npm installs it."""
    name = "megooarti-uploaded"
    fresh = sign_in()  # the first test signs out of the token it was given
    signed_in = {"Authorization": f"Bearer {fresh}"}
    packing = write(
        tmp_path / "pack", {"package": package(name, "1.0.0", description="Uploaded")}, fresh
    )
    packed = npm(packing, "cd package && npm pack --silent > /dev/null && base64 -w0 *.tgz")
    assert packed.returncode == 0, said(packed)
    tarball = base64.b64decode(packed.stdout.strip())

    status, stored = upload(HOSTED, {}, [("file", f"{name}-1.0.0.tgz", tarball)], signed_in)
    assert status == 201, stored
    assert [file["path"] for file in stored["files"]] == [f"{name}/-/{name}-1.0.0.tgz"]
    status, again = upload(HOSTED, {}, [("file", f"{name}-1.0.0.tgz", tarball)], signed_in)
    assert (status, again["error"]["code"]) == (409, "redeploy_disabled")

    # The detail of what was stored says how to install it.
    component = stored["components"][0]["id"]
    status, _, detail = call("GET", f"/content/{HOSTED}/components/{component}", None, signed_in)
    assert status == 200, detail
    assert [entry["text"] for entry in detail["usage"]] == [
        f"npm install {name}@1.0.0 --registry=http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/"
    ]

    consumer = {
        "package.json": json.dumps(
            {
                "name": "consumer",
                "version": "1.0.0",
                "private": True,
                "dependencies": {name: "1.0.0"},
            }
        ),
        "main.js": f'console.log(require("{name}")());\n',
    }
    work = write(tmp_path / "install", {"consumer": consumer}, fresh)
    installed = npm(
        work,
        f"npm view {name} description dist-tags.latest && cd consumer && npm install"
        " && node main.js",
    )
    assert installed.returncode == 0, said(installed)
    assert "Uploaded" in installed.stdout
    assert f"hello from {name}@1.0.0" in installed.stdout

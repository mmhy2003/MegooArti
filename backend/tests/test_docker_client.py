"""Real container clients against the built image.

Run with `pytest -m docker`. This drives the Docker client and the daemon of the
machine it runs on, which is the one that also runs the stack: images are built from
nothing, pushed to MegooArti at 127.0.0.1, removed, and pulled back. A daemon that keeps
its images in containerd uses containerd's own registry client for that. The last
test uses skopeo, which is built on the image library Podman uses; its image is pulled
from quay.io, so that test needs internet access. So does the test of proxies: the
backend container fetches from Docker Hub and from registry.k8s.io.

The Docker client is given a configuration directory of its own, so the user's sign-ins
and settings are neither read nor changed.
"""

import functools
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

REGISTRY = f"127.0.0.1:{HTTP_PORT}"
NETWORK = f"{PROJECT}_default"
SKOPEO = "quay.io/skopeo/stable:latest"
HOSTED = "docker-hosted"
RELEASES = "docker-releases"  # tags cannot be moved
USERNAME = "ci"
PASSWORD = "pushes-and-pulls-container-images"
READER = "reader"
IMAGE = f"{REGISTRY}/{HOSTED}/megooarti-test/hello"


@functools.cache
def daemon() -> str:
    """Where the Docker daemon in use listens. A configuration of our own does not say."""
    asked = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return asked.stdout.strip()


def configuration(directory: Path) -> Path:
    """A Docker client configuration of our own, so that the user's is left alone.

    It names a registry already, which makes the client keep what `docker login` learns
    in this directory and not in the credential store of the machine.
    """
    directory.mkdir()
    (directory / "config.json").write_text('{"auths": {"registry.invalid": {}}}', "utf-8")
    return directory


def docker(
    config: Path, *arguments: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the Docker client with a configuration of our own."""
    return subprocess.run(
        ["docker", "--config", str(config), "--host", daemon(), *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def registry(method: str, path: str, username: str = USERNAME, secret: str = PASSWORD):
    """A request to the registry API from outside: (status, headers, body)."""
    credentials = b64encode(f"{username}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"http://{REGISTRY}/v2/{path}",
        method=method,
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def build(config: Path, directory: Path, tag: str, text: str) -> None:
    """Build an image from nothing whose one file says `text`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "hello.txt").write_text(text, encoding="utf-8", newline="\n")
    (directory / "Dockerfile").write_text(
        "FROM scratch\nCOPY hello.txt /hello.txt\n", encoding="utf-8", newline="\n"
    )
    built = docker(config, "build", "--tag", tag, str(directory))
    assert built.returncode == 0, said(built)


def file_in(config: Path, image: str, directory: Path) -> str:
    """What `/hello.txt` says in an image the daemon holds."""
    made = docker(config, "create", image, "/nothing")
    assert made.returncode == 0, said(made)
    container = made.stdout.strip()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        copied = docker(config, "cp", f"{container}:/hello.txt", str(directory / "hello.txt"))
        assert copied.returncode == 0, said(copied)
        return (directory / "hello.txt").read_text(encoding="utf-8")
    finally:
        docker(config, "rm", container)


def sign_in(config: Path, username: str, password: str) -> subprocess.CompletedProcess[str]:
    return docker(
        config, "login", REGISTRY, "--username", username, "--password-stdin", stdin=password
    )


@pytest.fixture(scope="module")
def accounts(administrator) -> None:
    """Two Docker repositories, an account that may do everything in them, and a reader."""
    hosted = {"name": HOSTED, "format": "docker", "type": "hosted"}
    releases = {
        "name": RELEASES,
        "format": "docker",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    roles = [
        {"name": "docker-pushers", "permissions": ["repository:docker"]},
        {"name": "docker-readers", "permissions": [f"repository:docker:{HOSTED}:read"]},
    ]
    users = [
        {"username": USERNAME, "roles": ["docker-pushers"]},
        {"username": READER, "roles": ["docker-readers"]},
    ]
    for body in (hosted, releases):
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    for body in roles:
        status, _, answer = call("POST", "/roles", body, administrator)
        assert status == 201, answer
    for user in users:
        body = {**user, "display_name": "CI", "password": PASSWORD, "must_change_password": False}
        status, _, answer = call("POST", "/users", body, administrator)
        assert status == 201, answer


@pytest.fixture
def signed_in(accounts, tmp_path):
    """A Docker client configuration signed in as the pushing account."""
    config = configuration(tmp_path / "docker-config")
    login = sign_in(config, USERNAME, PASSWORD)
    assert login.returncode == 0, said(login)
    assert REGISTRY in json.loads((config / "config.json").read_text("utf-8"))["auths"]
    yield config
    for depth in ("*/*", "*/*/*"):
        held = docker(config, "image", "ls", "--quiet", "--filter", f"reference={REGISTRY}/{depth}")
        for image in set(held.stdout.split()):
            docker(config, "rmi", "--force", image)


def test_docker_signs_in_pushes_and_pulls(signed_in, tmp_path):
    config = signed_in
    build(config, tmp_path / "v1", f"{IMAGE}:1.0", "hello from version one")

    # Push, forget the image, and pull it back.
    pushed = docker(config, "push", f"{IMAGE}:1.0")
    assert pushed.returncode == 0, said(pushed)
    assert docker(config, "rmi", f"{IMAGE}:1.0").returncode == 0
    pulled = docker(config, "pull", f"{IMAGE}:1.0")
    assert pulled.returncode == 0, said(pulled)
    assert file_in(config, f"{IMAGE}:1.0", tmp_path / "out1") == "hello from version one"

    # What the registry says of it is what the daemon was given.
    status, headers, _ = registry("HEAD", f"{HOSTED}/megooarti-test/hello/manifests/1.0")
    digest = headers["Docker-Content-Digest"]
    assert (status, digest in pushed.stdout, digest in pulled.stdout) == (200, True, True)
    status, _, tags = registry("GET", f"{HOSTED}/megooarti-test/hello/tags/list")
    assert (status, json.loads(tags)["tags"]) == (200, ["1.0"])
    status, _, catalog = registry("GET", "_catalog")
    assert f"{HOSTED}/megooarti-test/hello" in json.loads(catalog)["repositories"]

    # The same image under another tag, and by its digest.
    assert docker(config, "tag", f"{IMAGE}:1.0", f"{IMAGE}:latest").returncode == 0
    again = docker(config, "push", f"{IMAGE}:latest")
    assert again.returncode == 0, said(again)
    _, headers, _ = registry("HEAD", f"{HOSTED}/megooarti-test/hello/manifests/latest")
    assert headers["Docker-Content-Digest"] == digest
    by_digest = docker(config, "pull", f"{IMAGE}@{digest}")
    assert by_digest.returncode == 0, said(by_digest)

    # A tag moves, here. Where tags cannot be moved, the second push is refused.
    build(config, tmp_path / "v2", f"{IMAGE}:1.0", "hello from version two")
    moved = docker(config, "push", f"{IMAGE}:1.0")
    assert moved.returncode == 0, said(moved)
    release = f"{REGISTRY}/{RELEASES}/megooarti-test/hello:1.0"
    for text in ("the release", "not the release"):
        build(config, tmp_path / "release", release, text)
        kept = docker(config, "push", release)
        assert (kept.returncode == 0) == (text == "the release"), said(kept)

    # Without signing in there is nothing to pull, and a reader cannot push.
    nobody = configuration(tmp_path / "nobody")
    refused = docker(nobody, "pull", f"{IMAGE}:latest")
    assert refused.returncode != 0, "pulled without signing in"
    reader = configuration(tmp_path / "reader")
    login = sign_in(reader, READER, PASSWORD)
    assert login.returncode == 0, said(login)
    assert docker(reader, "pull", f"{IMAGE}:latest").returncode == 0
    # Docker does not send what a registry already has, so the reader pushes a new tag.
    assert docker(reader, "tag", f"{IMAGE}:latest", f"{IMAGE}:mine").returncode == 0
    denied = docker(reader, "push", f"{IMAGE}:mine")
    assert denied.returncode != 0, "pushed with the right to read only"
    assert "do not have permission" in denied.stderr, said(denied)  # our own words
    assert registry("HEAD", f"{HOSTED}/megooarti-test/hello/manifests/mine")[0] == 404
    wrong = sign_in(nobody, USERNAME, "not the password")
    assert wrong.returncode != 0, "signed in with a wrong password"

    # Deleting an image gives back the layers nothing else uses.
    status, headers, manifest = registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/latest")
    first = headers["Docker-Content-Digest"]
    listed = json.loads(manifest)
    children = [entry["digest"] for entry in listed.get("manifests", [])]
    layers = []
    for child in children or [first]:
        _, _, raw = registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/{child}")
        layers += [entry["digest"] for entry in json.loads(raw).get("layers", [])]
    assert layers, listed
    assert registry("DELETE", f"{HOSTED}/megooarti-test/hello/manifests/{first}")[0] == 202
    for gone in layers:
        assert registry("HEAD", f"{HOSTED}/megooarti-test/hello/blobs/{gone}")[0] == 404
    assert registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/latest")[0] == 404
    assert registry("GET", f"{HOSTED}/megooarti-test/hello/manifests/1.0")[0] == 200  # version two


def test_anyone_pulls_what_the_anonymous_user_may_read(signed_in, administrator, tmp_path):
    public = f"{REGISTRY}/{HOSTED}/megooarti-test/public:1.0"
    build(signed_in, tmp_path / "public", public, "hello to everyone")
    pushed = docker(signed_in, "push", public)
    assert pushed.returncode == 0, said(pushed)
    assert docker(signed_in, "rmi", public).returncode == 0
    nobody = configuration(tmp_path / "nobody")
    assert docker(nobody, "pull", public).returncode != 0, "pulled before it was made public"

    status, _, users = call("GET", "/users", None, administrator)
    anonymous = next(user for user in users["items"] if user["username"] == "anonymous")
    path = f"/users/{anonymous['id']}"
    status, _, answer = call("PATCH", path, {"roles": ["docker-readers"]}, administrator)
    assert status == 200, answer
    status, _, answer = call("PUT", "/settings/anonymous-access", {"enabled": True}, administrator)
    assert status == 200, answer

    try:
        pulled = docker(nobody, "pull", public)
        assert pulled.returncode == 0, said(pulled)
        assert file_in(nobody, public, tmp_path / "out") == "hello to everyone"
        # Reading is all that was given, and only in that repository.
        assert docker(nobody, "tag", public, f"{public}-mine").returncode == 0
        assert docker(nobody, "push", f"{public}-mine").returncode != 0, "pushed without signing in"
        elsewhere = docker(nobody, "pull", f"{REGISTRY}/{RELEASES}/megooarti-test/hello:1.0")
        assert elsewhere.returncode != 0, "pulled from a repository that is not public"
    finally:
        call("PUT", "/settings/anonymous-access", {"enabled": False}, administrator)
    assert docker(nobody, "pull", public).returncode != 0, "pulled after it stopped being public"


def test_images_are_pulled_through_proxies_of_public_registries(signed_in, administrator, tmp_path):
    config = signed_in
    # Docker Hub signs a proxy in at another host and keeps its official images under
    # `library/`. registry.k8s.io asks for no sign-in and sends every request elsewhere.
    remotes = {"docker-hub": "https://registry-1.docker.io", "k8s": "https://registry.k8s.io"}
    for name, remote in remotes.items():
        body = {"name": name, "format": "docker", "type": "proxy", "proxy": {"remote_url": remote}}
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    hello = f"{REGISTRY}/docker-hub/hello-world:latest"
    pause = f"{REGISTRY}/k8s/pause:3.10"

    for image in (hello, pause):
        pulled = docker(config, "pull", image)
        assert pulled.returncode == 0, said(pulled)
    ran = docker(config, "run", "--rm", hello)
    assert ran.returncode == 0 and "Hello from Docker!" in ran.stdout, said(ran)

    # What was pulled is listed, with the tags the remote has.
    status, _, catalog = registry("GET", "_catalog")
    assert {"docker-hub/hello-world", "k8s/pause"} <= set(json.loads(catalog)["repositories"])
    status, _, tags = registry("GET", "docker-hub/hello-world/tags/list")
    assert status == 200 and "latest" in json.loads(tags)["tags"], tags

    # It is kept: with the remote blocked, the image is pulled again, by tag and by digest.
    status, headers, _ = registry("HEAD", "docker-hub/hello-world/manifests/latest")
    digest = headers["Docker-Content-Digest"]
    blocked = {"proxy": {"remote_url": remotes["docker-hub"], "blocked": True}}
    status, _, answer = call("PUT", "/repositories/docker-hub", blocked, administrator)
    assert status == 200, answer
    assert docker(config, "rmi", hello).returncode == 0
    again = docker(config, "pull", hello)
    assert again.returncode == 0, said(again)
    pinned = docker(config, "pull", f"{REGISTRY}/docker-hub/hello-world@{digest}")
    assert pinned.returncode == 0, said(pinned)
    never_fetched = docker(config, "pull", f"{REGISTRY}/docker-hub/busybox:latest")
    assert never_fetched.returncode != 0, "pulled what was never fetched from a blocked remote"

    # Nothing is pushed to a proxy.
    assert docker(config, "tag", hello, f"{REGISTRY}/docker-hub/mine:1.0").returncode == 0
    pushed = docker(config, "push", f"{REGISTRY}/docker-hub/mine:1.0")
    assert pushed.returncode != 0, "pushed to a proxy"


def test_a_group_serves_what_was_pushed_and_what_is_public_and_what_was_pushed_wins(
    signed_in, administrator, tmp_path
):
    config = signed_in
    # Not left alone after one failure: the internet may be slow once (L7).
    hub = {"remote_url": "https://registry-1.docker.io", "auto_block": False}
    repositories = [
        {"name": "team-images", "format": "docker", "type": "hosted"},
        {"name": "hub-mirror", "format": "docker", "type": "proxy", "proxy": hub},
        # The proxy first: the order must not decide whose image a name is.
        {
            "name": "everything",
            "format": "docker",
            "type": "group",
            "group": {"members": ["hub-mirror", "team-images"]},
        },
    ]
    for body in repositories:
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    group = f"{REGISTRY}/everything"

    # A public image comes through the group from Docker Hub.
    pulled = docker(config, "pull", f"{group}/hello-world:latest")
    assert pulled.returncode == 0, said(pulled)
    ran = docker(config, "run", "--rm", f"{group}/hello-world:latest")
    assert ran.returncode == 0 and "Hello from Docker!" in ran.stdout, said(ran)

    # Our own image, under a name Docker Hub has too, is the one the group serves.
    mine = f"{REGISTRY}/team-images/busybox:latest"
    build(config, tmp_path / "ours", mine, "this is ours, not the public busybox")
    pushed = docker(config, "push", mine)
    assert pushed.returncode == 0, said(pushed)
    assert docker(config, "rmi", mine).returncode == 0
    through = docker(config, "pull", f"{group}/busybox:latest")
    assert through.returncode == 0, said(through)
    text = file_in(config, f"{group}/busybox:latest", tmp_path / "out")
    assert text == "this is ours, not the public busybox"

    # Nothing of the public image of that name is offered: not its tags, not a pull.
    status, _, tags = registry("GET", "everything/busybox/tags/list")
    assert (status, json.loads(tags)["tags"]) == (200, ["latest"])
    theirs = docker(config, "pull", f"{group}/busybox:stable")
    assert theirs.returncode != 0, "pulled a public tag of a name that is ours"
    status, _, catalog = registry("GET", "_catalog")
    assert {"everything/busybox", "everything/hello-world"} <= set(
        json.loads(catalog)["repositories"]
    )

    # Nothing is pushed to a group.
    assert docker(config, "tag", f"{group}/busybox:latest", f"{group}/mine:1.0").returncode == 0
    refused = docker(config, "push", f"{group}/mine:1.0")
    assert refused.returncode != 0, "pushed to a group"


def layer_holding(text: str) -> tuple[bytes, str]:
    """A layer with one file, as a compressed archive, and the digest of it uncompressed."""
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode="w") as archive:
        entry = tarfile.TarInfo("hello.txt")
        entry.size = len(text.encode())
        archive.addfile(entry, io.BytesIO(text.encode()))
    return gzip.compress(plain.getvalue(), mtime=0), _digest(plain.getvalue())


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_layout(directory: Path, name: str) -> tuple[bytes, set[str]]:
    """An OCI image layout holding one image for two platforms. Returns its index and blobs."""
    blobs: dict[str, bytes] = {}

    def keep(data: bytes) -> dict:
        blobs[_digest(data)] = data
        return {"digest": _digest(data), "size": len(data)}

    platforms = []
    for architecture in ("amd64", "arm64"):
        archive, diff_id = layer_holding(f"hello from {architecture}")
        config = json.dumps(
            {
                "architecture": architecture,
                "os": "linux",
                "rootfs": {"type": "layers", "diff_ids": [diff_id]},
            }
        ).encode()
        manifest = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {"mediaType": "application/vnd.oci.image.config.v1+json", **keep(config)},
                "layers": [
                    {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", **keep(archive)}
                ],
            }
        ).encode()
        platforms.append(
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                **keep(manifest),
                "platform": {"architecture": architecture, "os": "linux"},
            }
        )
    index = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": platforms,
        }
    ).encode()
    described = {"mediaType": "application/vnd.oci.image.index.v1+json", **keep(index)}
    described["annotations"] = {"org.opencontainers.image.ref.name": name}
    (directory / "blobs" / "sha256").mkdir(parents=True)
    for digest, data in blobs.items():
        (directory / "blobs" / "sha256" / digest.partition(":")[2]).write_bytes(data)
    (directory / "oci-layout").write_text('{"imageLayoutVersion": "1.0.0"}', encoding="utf-8")
    top = {"schemaVersion": 2, "manifests": [described]}
    (directory / "index.json").write_text(json.dumps(top), encoding="utf-8")
    return index, set(blobs)


def skopeo(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the skopeo image, in a copy of `directory`, beside the stack."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        "--entrypoint",
        "sh",
        SKOPEO,
        "-c",
        f"cp -r /src /work && cd /work && {script}",
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


def test_an_image_for_several_platforms_is_copied_in_and_out(accounts, tmp_path):
    work = tmp_path / "skopeo"
    work.mkdir()
    index, blobs = write_layout(work / "layout", "multi")
    # With its port: a first part without a dot or a port is read as a name at Docker
    # Hub, not as a registry.
    there = f"docker://gateway:80/{HOSTED}/megooarti-test/multi:1.0"
    creds = f"{USERNAME}:{PASSWORD}"

    copied = skopeo(
        work,
        # What skopeo says as it works goes to the error stream: the output is ours.
        f"skopeo copy --all --dest-tls-verify=false --dest-creds {creds}"
        f" oci:layout:multi {there} >&2"
        f" && skopeo inspect --raw --tls-verify=false --creds {creds} {there} > /tmp/index.json"
        f" && skopeo copy --all --src-tls-verify=false --src-creds {creds}"
        f" {there} oci:back:multi >&2"
        " && cat /tmp/index.json && echo && ls back/blobs/sha256",
    )

    assert copied.returncode == 0, said(copied)
    served, _, listing = copied.stdout.partition("\n")
    assert served.encode() == index  # the manifest for both platforms, as it was pushed
    assert {f"sha256:{name}" for name in listing.split()} >= blobs  # and everything it needs
    status, headers, _ = registry("HEAD", f"{HOSTED}/megooarti-test/multi/manifests/1.0")
    assert (status, headers["Docker-Content-Digest"]) == (200, _digest(index))
    assert headers["Content-Type"] == "application/vnd.oci.image.index.v1+json"

"""Backup and restore, done with the scripts an operator is given (NFR-12).

The one that runs them needs a Docker daemon and a POSIX shell (`sh`): on Windows, Git's.
"""

import base64
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import pytest

from megooarti import __version__
from tests.containers import ENVIRONMENT, HTTP_PORT, PROJECT, REPOSITORY_ROOT, call, compose, upload
from tests.repositories.docker.conftest import config_for, digest_of, image_manifest, layer
from tests.repositories.npm.conftest import publish_body, tarball_of
from tests.repositories.pypi.conftest import content_of

SCRIPTS = REPOSITORY_ROOT / "scripts"
SHELL = shutil.which("sh")
HOST = f"http://127.0.0.1:{HTTP_PORT}"
WHEEL = "megooarti_kept-1.0.0-py3-none-any.whl"
JAR = "releases/com/acme/app/1.0/app-1.0.jar"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def script(name: str, *arguments: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    """Run one of the scripts as an operator would, against the tests' own stack."""
    assert SHELL, "sh is not on the PATH: the scripts are shell scripts (on Windows, Git has one)"
    return subprocess.run(
        [SHELL, (SCRIPTS / name).as_posix(), *arguments],
        env={**ENVIRONMENT, "COMPOSE_PROJECT_NAME": PROJECT},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


@pytest.mark.parametrize("name", ["backup.sh", "restore.sh"])
def test_the_scripts_are_shell_scripts_with_unix_line_endings(name):
    text = (SCRIPTS / name).read_bytes()

    assert text.startswith(b"#!/bin/sh\n")
    assert b"\r" not in text
    assert b"set -eu\n" in text


@pytest.mark.skipif(SHELL is None, reason="needs a POSIX shell")
@pytest.mark.parametrize("name", ["backup.sh", "restore.sh"])
def test_a_script_given_nothing_says_how_it_is_used(name):
    result = script(name, timeout=30)

    assert result.returncode != 0
    assert f"usage: {name} <directory>" in result.stderr


@pytest.mark.skipif(SHELL is None, reason="needs a POSIX shell")
def test_restoring_from_a_directory_that_holds_no_backup_touches_nothing(tmp_path):
    result = script("restore.sh", tmp_path.as_posix(), timeout=30)

    assert result.returncode == 2
    assert "has no database.dump and data.tar" in result.stderr


def send(method: str, address: str, data: bytes | None = None, headers: dict | None = None):
    """One request to the published gateway: (status, headers, body)."""
    request = urllib.request.Request(
        urllib.parse.urljoin(HOST, address), method=method, data=data, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def push_image(headers: dict, tag: str, *texts: str) -> bytes:
    """An image pushed to `images/app` as a registry client pushes it. Returns its manifest."""
    config = config_for(*texts)
    layers = [layer(text) for text in texts]
    for data in (config, *layers):
        status, begun, _ = send("POST", "/v2/images/app/blobs/uploads/", headers=headers)
        assert status == 202
        status, sent, _ = send("PATCH", begun["Location"], data, headers)
        assert status == 202
        status, _, body = send("PUT", f"{sent['Location']}?digest={digest_of(data)}", None, headers)
        assert status == 201, body
    manifest = image_manifest(config, *layers)
    status, _, body = send(
        "PUT",
        f"/v2/images/app/manifests/{tag}",
        manifest,
        {**headers, "Content-Type": OCI_MANIFEST},
    )
    assert status == 201, body
    return manifest


@pytest.mark.docker
def test_a_backup_restored_into_a_new_installation_has_everything(administrator, tmp_path):
    status, _, created = call("POST", "/me/tokens", {"name": "backup-test"}, administrator)
    assert status == 201, created
    token = created["token"]
    basic = base64.b64encode(f"__token__:{token}".encode()).decode()
    client = {"Authorization": f"Basic {basic}"}

    # A blob store whose files are not under the data directory: the backup cannot have them.
    status, _, body = call(
        "POST", "/blob-stores", {"name": "elsewhere", "path": "/tmp/elsewhere"}, administrator
    )
    assert status == 201, body
    repositories = [
        {"name": "files", "format": "raw", "type": "hosted"},
        {"name": "releases", "format": "maven", "type": "hosted"},
        {"name": "packages", "format": "npm", "type": "hosted"},
        {"name": "wheels", "format": "pypi", "type": "hosted"},
        {"name": "images", "format": "docker", "type": "hosted"},
        {
            # A proxy of this installation's own repository, which it reaches with a
            # secret: sealed with the key that is in the data directory.
            "name": "mirror",
            "format": "raw",
            "type": "proxy",
            "proxy": {
                "remote_url": "http://gateway/repository/files",
                "remote_auth": {"type": "bearer", "secret": token},
            },
        },
    ]
    for repository in repositories:
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body

    # Something of every format, each put there as its own clients put it.
    for path in ("docs/cached.txt", "docs/never-fetched.txt"):
        assert send("PUT", f"/repository/files/{path}", path.encode(), client)[0] == 201
    assert send("PUT", f"/repository/{JAR}", b"PK the jar", client)[0] == 201
    published = json.dumps(publish_body("megooarti-kept", "1.0.0")).encode()
    status, _, body = send(
        "PUT",
        "/repository/packages/megooarti-kept",
        published,
        {**client, "Content-Type": "application/json"},
    )
    assert status in (200, 201), body
    status, stored = upload("wheels", {}, [("file", WHEEL, content_of(WHEEL))], client)
    assert status == 201, stored
    manifest = push_image(client, "1.0", "one layer", "another")
    # The proxy has fetched one of the two files, and not the other.
    assert send("GET", "/repository/mirror/docs/cached.txt", headers=client)[0] == 200

    target = tmp_path / "backup"
    backed_up = script("backup.sh", target.as_posix())
    assert backed_up.returncode == 0, backed_up.stderr
    assert (target / "database.dump").stat().st_size > 10_000
    assert (target / "data.tar").stat().st_size > 10_000
    assert (target / "VERSION").read_text(encoding="utf-8").strip() == __version__
    assert "the blob store elsewhere at /tmp/elsewhere" in backed_up.stderr
    assert "NOT in this backup" in backed_up.stderr

    # What comes after the backup is not in it.
    assert send("PUT", "/repository/files/docs/after.txt", b"after", client)[0] == 201

    compose("down", "--volumes")
    restored = script("restore.sh", target.as_posix())
    assert restored.returncode == 0, restored.stderr + restored.stdout[-2000:]

    # The session that was open and the token that was made are those of the backup.
    status, _, session = call("GET", "/auth/session", headers=administrator)
    assert (status, session["authenticated"]) == (200, True)
    for path in ("docs/cached.txt", "docs/never-fetched.txt"):
        status, _, body = send("GET", f"/repository/files/{path}", headers=client)
        assert (status, body) == (200, path.encode())
    assert send("GET", "/repository/files/docs/after.txt", headers=client)[0] == 404
    assert send("GET", f"/repository/{JAR}", headers=client)[2] == b"PK the jar"
    status, _, document = send("GET", "/repository/packages/megooarti-kept", headers=client)
    assert list(json.loads(document)["versions"]) == ["1.0.0"]
    status, _, tarball = send(
        "GET", "/repository/packages/megooarti-kept/-/megooarti-kept-1.0.0.tgz", headers=client
    )
    assert (status, tarball) == (200, tarball_of("megooarti-kept", "1.0.0"))
    status, _, page = send("GET", "/repository/wheels/simple/megooarti-kept/", headers=client)
    assert status == 200 and WHEEL.encode() in page
    status, _, wheel = send(
        "GET", f"/repository/wheels/packages/megooarti-kept/1.0.0/{WHEEL}", headers=client
    )
    assert (status, wheel) == (200, content_of(WHEEL))
    status, _, pulled = send(
        "GET", "/v2/images/app/manifests/1.0", headers={**client, "Accept": OCI_MANIFEST}
    )
    assert (status, pulled) == (200, manifest)
    for data in (layer("one layer"), layer("another")):
        status, _, blob = send("GET", f"/v2/images/app/blobs/{digest_of(data)}", headers=client)
        assert (status, blob) == (200, data)
    # The proxy's secret is read with the key that came back with the data directory:
    # what it had not fetched before is fetched now.
    status, _, body = send("GET", "/repository/mirror/docs/never-fetched.txt", headers=client)
    assert (status, body) == (200, b"docs/never-fetched.txt")
    status, _, shown = call("GET", "/repositories/mirror", headers=administrator)
    assert shown["status"]["last_error"] is None

    # And an installation that has something in it is not written over.
    again = script("restore.sh", target.as_posix())
    assert again.returncode == 3
    assert "is not empty" in again.stderr
    assert send("GET", "/repository/files/docs/cached.txt", headers=client)[0] == 200

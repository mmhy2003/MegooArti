"""Backup and restore, done with the scripts an operator is given (NFR-12).

The one that runs them needs a Docker daemon and a POSIX shell (`sh`): on Windows, Git's.
"""

import base64
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

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


def script(
    name: str,
    *arguments: str,
    timeout: int = 900,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one of the scripts as an operator would, against the tests' own stack."""
    assert SHELL, "sh is not on the PATH: the scripts are shell scripts (on Windows, Git has one)"
    return subprocess.run(
        [SHELL, (SCRIPTS / name).as_posix(), *arguments],
        env=environment or {**ENVIRONMENT, "COMPOSE_PROJECT_NAME": PROJECT},
        cwd=cwd,
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


# A stand-in for `docker`, for the scripts' own decisions without a daemon. It writes
# down what it was asked, and answers as the FAKE_* variables say: a status, or what a
# command prints. What it is not told, it does as a healthy installation would.
FAKE_DOCKER = r"""#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_LOG"
down() { echo "service \"$1\" is not running" >&2; exit 1; }
case "$*" in
  "compose exec -T db true") [ "${FAKE_DB:-0}" = 0 ] || down db ;;
  "compose exec -T backend true") [ "${FAKE_BACKEND:-0}" = 0 ] || down backend ;;
  "compose exec -T db pg_dump "*)
    [ "${FAKE_DUMP:-0}" = 0 ] && printf 'PGDMP a new dump'
    exit "${FAKE_DUMP:-0}" ;;
  "compose exec -T backend sh -c "*tar*)
    [ "${FAKE_BACKEND:-0}" = 0 ] || down backend
    if [ "${FAKE_TAR:-0}" = cut ]; then printf 'half a t'; exit 137; fi
    printf 'a new tar'
    echo "tar: ./blobs/default/tmp/x: file changed as we read it" >&2
    echo "tar-status:${FAKE_TAR:-0}" >&2 ;;
  "compose exec -T backend tar "*)
    [ "${FAKE_BACKEND:-0}" = 0 ] || down backend
    if [ "${FAKE_TAR:-0}" = cut ]; then printf 'half a t'; exit 137; fi
    printf 'a new tar'
    exit "${FAKE_TAR:-0}" ;;
  "compose exec -T backend python "*)
    [ "${FAKE_BACKEND:-0}" = 0 ] || down backend
    printf '%s\r\n' "${FAKE_VERSION-1.2.3}" ;;
  "compose exec -T db psql "*blob_stores*)
    printf '%s' "${FAKE_OUTSIDE:-}"
    exit "${FAKE_PSQL:-0}" ;;
  "compose exec -T db psql "*information_schema*)
    printf '%s\r\n' "${FAKE_TABLES-0}"
    exit "${FAKE_PSQL:-0}" ;;
  "compose run --rm --no-deps -T --entrypoint sh backend "*)
    printf '%s\r\n' "${FAKE_FOUND-0}"
    exit "${FAKE_RUN:-0}" ;;
  "compose exec -T db pg_restore --list") cat > /dev/null; exit "${FAKE_DUMP_READ:-0}" ;;
  "compose run --rm --no-deps -T --entrypoint tar backend --list "*)
    cat > /dev/null
    exit "${FAKE_TAR_READ:-0}" ;;
  "compose exec -T db pg_restore --username "*) cat > /dev/null; exit "${FAKE_RESTORE:-0}" ;;
  "compose run --rm --no-deps -T --entrypoint tar backend --extract "*)
    cat > /dev/null
    exit "${FAKE_EXTRACT:-0}" ;;
  "compose up --detach --wait db") ;;
  "compose up --detach --wait") exit "${FAKE_UP:-0}" ;;
  *) echo "fake docker: not expected: $*" >&2; exit 97 ;;
esac
"""

without_a_daemon = pytest.mark.skipif(SHELL is None, reason="needs a POSIX shell")


class Faked:
    """A place where `docker` is the stand-in, and what it was asked."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        (directory / "bin").mkdir()
        stand_in = directory / "bin" / "docker"
        stand_in.write_text(FAKE_DOCKER, encoding="utf-8", newline="\n")
        stand_in.chmod(0o755)
        self._log = directory / "docker.log"
        self._log.write_text("", encoding="utf-8")

    def run(self, name: str, *arguments: str, cwd: Path | None = None, **answers):
        environment = {
            **os.environ,
            "PATH": f"{self.directory / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LOG": self._log.as_posix(),
            **{f"FAKE_{name.upper()}": str(value) for name, value in answers.items()},
        }
        return script(name, *arguments, timeout=60, environment=environment, cwd=cwd)

    @property
    def asked(self) -> str:
        return self._log.read_text(encoding="utf-8")


@pytest.fixture
def faked(tmp_path) -> Faked:
    return Faked(tmp_path)


def a_backup(directory: Path, said: str = "of yesterday") -> Path:
    """A directory that holds a backup already."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("database.dump", "data.tar", "VERSION"):
        (directory / name).write_text(f"{name} {said}", encoding="utf-8")
    return directory


def held(directory: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(directory.iterdir())
    }


@without_a_daemon
@pytest.mark.parametrize(
    ("answers", "why"),
    [
        ({"backend": 1}, "the backend is not running"),
        ({"db": 1}, "the database is not running"),
        ({"dump": 1}, "the database could not be dumped"),
        ({"tar": 2}, "the data directory could not be read (tar ended with 2)"),
        ({"tar": "cut"}, "the copy of the data directory was cut off"),
        ({"version": ""}, "the backend named no version"),
        ({"psql": 1}, "the blob stores could not be listed"),
    ],
)
def test_a_backup_that_is_not_whole_is_not_called_done_and_replaces_nothing(faked, answers, why):
    # As a job that runs every night meets a backend that is down, or being upgraded.
    target = a_backup(faked.directory / "backup")
    before = held(target)

    result = faked.run("backup.sh", target.as_posix(), **answers)

    assert result.returncode != 0
    assert f"backup: {why}" in result.stderr
    assert "NOT done" in result.stderr and "done, version" not in result.stdout
    # Yesterday's backup is all there is in the directory, as it was.
    assert held(target) == before


@without_a_daemon
def test_a_backup_made_while_a_file_changed_is_whole_and_takes_the_place_of_the_last(faked):
    target = a_backup(faked.directory / "backup")

    # 1 is how tar ends when a file changed while it was read: an upload going on.
    result = faked.run("backup.sh", target.as_posix(), tar=1)

    assert result.returncode == 0, result.stderr
    assert held(target) == {
        "VERSION": "1.2.3\n",
        "data.tar": "a new tar",
        "database.dump": "PGDMP a new dump",
    }
    assert "backup: done, version 1.2.3, in " in result.stdout
    # What tar said is passed on, and its status line is not.
    assert "file changed as we read it" in result.stderr
    assert "tar-status" not in result.stderr


@without_a_daemon
def test_a_backup_goes_where_whoever_ran_it_said(faked):
    # A path that is not whole is from where the script was run, not from where it is.
    elsewhere = faked.directory / "elsewhere"
    elsewhere.mkdir()

    stray = SCRIPTS.parent / "night"
    try:
        result = faked.run("backup.sh", "night/1", cwd=elsewhere)

        assert result.returncode == 0, result.stderr
        assert sorted(held(elsewhere / "night" / "1")) == ["VERSION", "data.tar", "database.dump"]
        assert not stray.exists()
    finally:
        shutil.rmtree(stray, ignore_errors=True)  # where a script that got it wrong wrote


@without_a_daemon
@pytest.mark.skipif(os.name == "nt", reason="Windows keeps no such permissions")
def test_a_backup_is_for_its_owner_alone(faked):
    # The dump has every password's hash, and the copy has the key.
    target = faked.directory / "backup"

    assert faked.run("backup.sh", target.as_posix()).returncode == 0

    for path in target.iterdir():
        assert path.stat().st_mode & 0o077 == 0, path.name


@without_a_daemon
def test_the_stores_a_backup_cannot_have_are_named_and_no_store_is_left_out_by_a_pattern(faked):
    target = faked.directory / "backup"

    result = faked.run("backup.sh", target.as_posix(), outside="fast at /mnt/fast\r\n")

    assert result.returncode == 0, result.stderr
    assert "NOT in this backup" in result.stderr
    assert "backup:   the blob store fast at /mnt/fast" in result.stderr
    # A store whose directory is given whole and is under the data directory is in the
    # copy: it is not asked for.
    assert "not like '/var/lib/megooarti/%'" in faked.asked
    # And nothing is left out by a pattern, which a store called `cache/tmp` would match.
    assert "--exclude" not in faked.asked


@without_a_daemon
@pytest.mark.parametrize(
    ("answers", "which"),
    [({"dump_read": 1}, "database.dump"), ({"tar_read": 2}, "data.tar")],
)
def test_a_backup_that_cannot_be_read_through_is_not_begun(faked, answers, which):
    source = a_backup(faked.directory / "backup")

    result = faked.run("restore.sh", source.as_posix(), **answers)

    assert result.returncode == 2
    assert f"restore: {which} cannot be read. Nothing was restored." in result.stderr
    # Neither half was written: the installation is as empty as it was.
    assert "pg_restore --username" not in faked.asked
    assert "--extract" not in faked.asked


@without_a_daemon
@pytest.mark.parametrize("answers", [{"restore": 1}, {"extract": 2}])
def test_a_restore_that_stops_between_its_halves_says_what_is_left_and_what_to_do(faked, answers):
    source = a_backup(faked.directory / "backup")

    result = faked.run("restore.sh", source.as_posix(), **answers)

    assert result.returncode == 1
    assert "it stopped half way" in result.stderr
    assert "docker compose down --volumes" in result.stderr
    assert "restore: done" not in result.stdout
    assert "compose up --detach --wait\n" not in faked.asked


@without_a_daemon
@pytest.mark.parametrize(
    ("answers", "status", "said"),
    [
        ({"tables": 14}, 3, "the database is not empty"),
        ({"found": 2}, 3, "the data directory is not empty"),
        # Not being able to look is not the same as having found something.
        ({"psql": 1}, 1, "the database could not be asked"),
        ({"run": 125}, 1, "the backend's image could not be run"),
    ],
)
def test_an_installation_that_is_not_empty_or_cannot_be_looked_at_is_left_alone(
    faked, answers, status, said
):
    source = a_backup(faked.directory / "backup")

    result = faked.run("restore.sh", source.as_posix(), **answers)

    assert result.returncode == status
    assert f"restore: {said}" in result.stderr
    assert "pg_restore" not in faked.asked and "--extract" not in faked.asked


@without_a_daemon
def test_a_restore_reads_both_halves_through_then_writes_the_database_whole_then_the_files(faked):
    source = a_backup(faked.directory / "backup", said="1.2.3")
    (source / "VERSION").write_text("1.2.3\r\n", encoding="utf-8")

    result = faked.run("restore.sh", source.as_posix())

    assert result.returncode == 0, result.stderr
    assert "restore: a backup of version 1.2.3\n" in result.stdout
    steps = (
        "compose up --detach --wait db\n",
        "pg_restore --list",
        "backend --list",
        "pg_restore --username",
        "backend --extract",
        "compose up --detach --wait\n",
    )
    order = [faked.asked.index(step) for step in steps]
    assert order == sorted(order)
    # All of the database or none of it.
    assert "--single-transaction" in faked.asked
    assert result.stdout.rstrip().endswith("restore: done")


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
    # And one whose directory ends as the folder for unfinished uploads is called: a
    # pattern that left those folders out of the copy took this store with them.
    status, _, body = call(
        "POST", "/blob-stores", {"name": "nested", "path": "cache/tmp"}, administrator
    )
    assert status == 201, body
    repositories = [
        {"name": "files", "format": "raw", "type": "hosted"},
        {"name": "apart", "format": "raw", "type": "hosted", "blob_store": "nested"},
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
    assert send("PUT", "/repository/apart/a.txt", b"kept apart", client)[0] == 201
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
    # With the backend stopped there is nothing to copy, and nothing is called a backup.
    compose("stop", "backend")
    stopped = script("backup.sh", target.as_posix())
    assert stopped.returncode != 0
    assert "backup: the backend is not running" in stopped.stderr
    assert list(target.iterdir()) == []
    compose("up", "--detach", "--wait")

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
    # A copy of the backup whose second half is no archive: found before anything is
    # written, so that the restore of the whole one that follows finds nothing there.
    broken = tmp_path / "broken"
    shutil.copytree(target, broken)
    (broken / "data.tar").write_bytes(b"this is no archive" * 100)
    refused = script("restore.sh", broken.as_posix())
    assert refused.returncode == 2, refused.stderr
    assert "restore: data.tar cannot be read. Nothing was restored." in refused.stderr

    restored = script("restore.sh", target.as_posix())
    assert restored.returncode == 0, restored.stderr + restored.stdout[-2000:]
    assert f"restore: a backup of version {__version__}" in restored.stdout

    # The session that was open and the token that was made are those of the backup.
    status, _, session = call("GET", "/auth/session", headers=administrator)
    assert (status, session["authenticated"]) == (200, True)
    for path in ("docs/cached.txt", "docs/never-fetched.txt"):
        status, _, body = send("GET", f"/repository/files/{path}", headers=client)
        assert (status, body) == (200, path.encode())
    assert send("GET", "/repository/files/docs/after.txt", headers=client)[0] == 404
    status, _, body = send("GET", "/repository/apart/a.txt", headers=client)
    assert (status, body) == (200, b"kept apart")
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

"""Tests of the built image. The `docker` ones run only with `pytest -m docker`."""

import hashlib
import json
import os
import urllib.request

import pytest

from tests.containers import BACKEND_DIR, DATA_FILE, HTTP_PORT, call, compose, run_in_backend

UNREACHABLE = "MEGOOARTI_DATABASE_URL=postgresql://megooarti:megooarti@nowhere.invalid:5432/m"


def test_entrypoint_has_unix_line_endings():
    script = (BACKEND_DIR / "docker-entrypoint.sh").read_bytes()
    assert script.startswith(b"#!/bin/sh\n")
    assert b"\r" not in script


@pytest.mark.docker
def test_stack_starts_ready_with_the_schema_at_head(stack):
    url = f"http://127.0.0.1:{HTTP_PORT}/api/v1/status/ready"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = json.load(response)
    assert body == {"status": "ok", "checks": {"database": "ok", "schema": "ok"}}


@pytest.mark.docker
def test_starting_again_against_a_migrated_database_is_safe(stack):
    result = run_in_backend("backend", "echo", "started")
    assert result.returncode == 0, result.stderr
    assert "started" in result.stdout


@pytest.mark.docker
def test_unreachable_database_stops_the_container_before_the_app_starts(stack):
    result = run_in_backend(
        "-e", UNREACHABLE, "-e", "MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS=3", "backend", "echo", "started"
    )
    assert result.returncode != 0
    assert "started" not in result.stdout
    assert "database not reachable" in result.stdout + result.stderr


@pytest.mark.docker
def test_migrations_can_be_switched_off(stack):
    result = run_in_backend(
        "-e", UNREACHABLE, "-e", "MEGOOARTI_RUN_MIGRATIONS=false", "backend", "echo", "started"
    )
    assert result.returncode == 0, result.stderr
    assert "started" in result.stdout


@pytest.mark.docker
def test_container_does_not_run_as_root(stack):
    result = run_in_backend("--entrypoint", "id", "backend", "-u")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10001"


@pytest.mark.docker
def test_the_first_start_administrator_can_sign_in_and_change_the_password(administrator):
    status, _, listed = call("GET", "/users", headers=administrator)

    assert status == 200
    assert {user["username"] for user in listed["items"]} == {"admin", "anonymous"}
    still_there = compose("exec", "-T", "backend", "test", "-e", DATA_FILE, check=False)
    assert still_there.returncode != 0


@pytest.mark.docker
def test_a_file_is_uploaded_and_downloaded_with_an_api_token(administrator):
    status, _, created = call("POST", "/me/tokens", {"name": "container-test"}, administrator)
    assert status == 201
    token = {"Authorization": f"Bearer {created['token']}"}
    status, _, _ = call(
        "POST", "/repositories", {"name": "files", "format": "raw", "type": "hosted"}, administrator
    )
    assert status == 201

    content = os.urandom(3 * 1024 * 1024 + 17)
    url = f"http://127.0.0.1:{HTTP_PORT}/repository/files/big/blob.bin"

    upload = urllib.request.Request(url, data=content, method="PUT", headers=token)
    with urllib.request.urlopen(upload, timeout=60) as response:
        assert response.status == 201

    with urllib.request.urlopen(urllib.request.Request(url, headers=token), timeout=60) as response:
        assert response.read() == content
        assert response.headers["X-Checksum-Sha256"] == hashlib.sha256(content).hexdigest()

    part = urllib.request.Request(url, headers={**token, "Range": "bytes=10-19"})
    with urllib.request.urlopen(part, timeout=60) as response:
        assert response.status == 206
        assert response.read() == content[10:20]

    count = "find /var/lib/megooarti/blobs/default/content -type f | wc -l"
    stored = compose("exec", "-T", "backend", "sh", "-c", count)
    assert stored.stdout.strip() == "1"


@pytest.mark.docker
def test_a_group_serves_a_file_through_a_proxy_of_a_hosted_repository(administrator):
    status, _, created = call("POST", "/me/tokens", {"name": "proxy-test"}, administrator)
    assert status == 201
    token = {"Authorization": f"Bearer {created['token']}"}
    origin = {"name": "origin", "format": "raw", "type": "hosted"}
    mirror = {
        "name": "origin-mirror",
        "format": "raw",
        "type": "proxy",
        "proxy": {
            # The container talks to itself: the remote is its own hosted repository.
            "remote_url": "http://127.0.0.1:8000/repository/origin",
            "remote_auth": {"type": "bearer", "secret": created["token"]},
        },
    }
    everything = {
        "name": "everything",
        "format": "raw",
        "type": "group",
        "group": {"members": ["origin-mirror"]},
    }
    for repository in (origin, mirror, everything):
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body
    assert body["group"] == {"members": ["origin-mirror"]}

    content = os.urandom(64 * 1024 + 3)
    base = f"http://127.0.0.1:{HTTP_PORT}/repository"
    upload = urllib.request.Request(
        f"{base}/origin/dist/app.bin", data=content, method="PUT", headers=token
    )
    with urllib.request.urlopen(upload, timeout=60) as response:
        assert response.status == 201

    through_group = urllib.request.Request(f"{base}/everything/dist/app.bin", headers=token)
    with urllib.request.urlopen(through_group, timeout=60) as response:
        assert response.read() == content

    # Remove the original. The proxy keeps serving what it cached.
    remove = urllib.request.Request(f"{base}/origin/dist/app.bin", method="DELETE", headers=token)
    with urllib.request.urlopen(remove, timeout=60) as response:
        assert response.status == 204
    with urllib.request.urlopen(through_group, timeout=60) as response:
        assert response.read() == content

    status, _, shown = call("GET", "/repositories/origin-mirror", headers=administrator)
    assert status == 200
    assert shown["proxy"]["remote_auth"] == {"type": "bearer", "username": "", "has_secret": True}
    assert shown["status"]["failures"] == 0
    key = compose(
        "exec", "-T", "backend", "test", "-s", "/var/lib/megooarti/secret.key", check=False
    )
    assert key.returncode == 0

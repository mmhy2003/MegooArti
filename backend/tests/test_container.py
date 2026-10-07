"""Tests of the built image. The `docker` ones run only with `pytest -m docker`."""

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
PROJECT = "megooarti-test"
HTTP_PORT = "18000"
ENVIRONMENT = {**os.environ, "MEGOOARTI_HTTP_PORT": HTTP_PORT, "MEGOOARTI_DB_PORT": "15432"}
UNREACHABLE = "MEGOOARTI_DATABASE_URL=postgresql://megooarti:megooarti@nowhere.invalid:5432/m"


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=REPOSITORY_ROOT,
        env=ENVIRONMENT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def run_in_backend(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Start a throwaway backend container; `arguments` are `docker compose run` arguments."""
    return compose("run", "--rm", "--no-deps", "-T", *arguments, check=False)


@pytest.fixture(scope="module")
def stack():
    compose("down", "--volumes", check=False)
    compose("build", "backend")
    compose("up", "--detach", "--wait", "--wait-timeout", "180")
    yield
    compose("down", "--volumes", check=False)


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


DATA_FILE = "/var/lib/megooarti/admin.password"


def call(method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    """A JSON request to the published backend port: (status, headers, body)."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1{path}",
        method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, response.headers, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, error.headers, json.loads(error.read() or b"null")


@pytest.mark.docker
def test_the_first_start_administrator_can_sign_in_and_change_the_password(stack):
    password = compose("exec", "-T", "backend", "cat", DATA_FILE).stdout.strip()
    assert password

    status, headers, session = call(
        "POST", "/auth/login", {"username": "admin", "password": password}
    )
    assert status == 200
    assert session["must_change_password"] is True
    credentials = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }

    status, _, _ = call(
        "PUT",
        "/me/password",
        {"current_password": password, "new_password": "a brand new password"},
        credentials,
    )
    assert status == 204

    status, _, listed = call("GET", "/users", headers=credentials)
    assert status == 200
    assert {user["username"] for user in listed["items"]} == {"admin", "anonymous"}
    still_there = compose("exec", "-T", "backend", "test", "-e", DATA_FILE, check=False)
    assert still_there.returncode != 0

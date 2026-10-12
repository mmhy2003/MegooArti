"""Helpers for tests that run the built image. They need a Docker daemon."""

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
PROJECT = "megooarti-test"
HTTP_PORT = "18000"
ENVIRONMENT = {**os.environ, "MEGOOARTI_HTTP_PORT": HTTP_PORT, "MEGOOARTI_DB_PORT": "15432"}
DATA_FILE = "/var/lib/megooarti/admin.password"


class ComposeFailed(RuntimeError):
    """A Compose command that did not succeed, with what Docker said.

    `subprocess` says only that the exit status was not zero, which is no reason: a
    build that could not reach a registry and one that could not compile look alike.
    """

    def __init__(self, arguments: tuple[str, ...], result: subprocess.CompletedProcess[str]):
        self.returncode, self.stdout, self.stderr = result.returncode, result.stdout, result.stderr
        said = (result.stderr or result.stdout or "").strip()[-4000:]
        command = " ".join(arguments)
        super().__init__(f"docker compose {command} exited with {result.returncode}:\n{said}")


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=REPOSITORY_ROOT,
        env=ENVIRONMENT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise ComposeFailed(arguments, result)
    return result


def run_in_backend(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Start a throwaway backend container; `arguments` are `docker compose run` arguments."""
    return compose("run", "--rm", "--no-deps", "-T", *arguments, check=False)


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


def upload(
    repository: str,
    fields: dict[str, str],
    files: list[tuple[str, str, bytes]],
    headers: dict | None = None,
):
    """An upload form sent to the content API of the published backend: (status, body).

    `files` are (the name of the part, the file's name, its content).
    """
    boundary = "megooarti-test-upload-4dZ1u8RkQ2"
    body = b""
    for name, value in fields.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
        body += f"{head}{value}\r\n".encode()
    for part, filename, content in files:
        disposition = f'form-data; name="{part}"; filename="{filename}"'
        head = (
            f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        )
        body += head.encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1/content/{repository}/upload",
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")

"""The web UI in a real browser, and the gateway in front of it, against the built images.

Run with `pytest -m docker`. Besides a Docker daemon this needs Node.js and pnpm, the
frontend's dependencies and a browser for Playwright, once:

    cd frontend && pnpm install && pnpm exec playwright install chromium

The browser tests themselves are in `frontend/e2e/`. They begin with the first sign-in
of a fresh installation, so they need the stack this module starts and the password it
generated.
"""

import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

from tests.containers import DATA_FILE, HTTP_PORT, REPOSITORY_ROOT, compose

pytestmark = pytest.mark.docker

FRONTEND = REPOSITORY_ROOT / "frontend"


def get(path: str) -> tuple[int, str, str]:
    """A request to the published address: (status, content type, body)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}{path}", timeout=30) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode(),
            )
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read().decode()


@pytest.mark.parametrize(
    ("path", "status", "kind", "said"),
    [
        ("/api/v1/status/ready", 200, "application/json", '"status":"ok"'),
        ("/api/docs", 200, "text/html", "swagger"),
        ("/repository/no-such-repository/file", 404, "application/json", "not_found"),
        ("/v2/", 401, "application/json", "UNAUTHORIZED"),
        ("/login", 200, "text/html", "<html"),
        ("/", 200, "text/html", "<html"),
        ("/healthz", 200, "text/plain", "ok"),
        ("/no/such/screen", 404, "text/html", "<html"),
    ],
    ids=["api", "api-docs", "repository", "registry", "sign-in", "home", "health", "nothing"],
)
def test_the_gateway_sends_each_kind_of_address_to_its_place(stack, path, status, kind, said):
    answered, content_type, body = get(path)

    assert (answered, content_type.partition(";")[0]) == (status, kind)
    assert said.lower() in body.lower()


def test_the_frontend_container_is_not_root_and_is_given_nothing_to_keep(stack):
    user = compose("exec", "-T", "frontend", "id", "-u").stdout.strip()
    environment = compose("exec", "-T", "frontend", "env").stdout

    assert user.isdigit() and user != "0"
    assert "MEGOOARTI_" not in environment
    assert "NEXT_TELEMETRY_DISABLED=1" in environment


def test_the_ui_in_a_real_browser(stack):
    pnpm = shutil.which("pnpm")
    assert pnpm, "pnpm is not installed: see the first lines of this file"
    password = compose("exec", "-T", "backend", "cat", DATA_FILE).stdout.strip()
    assert password
    environment = {
        **os.environ,
        # `localhost`: a browser keeps the session cookie, which is Secure, over plain
        # HTTP only there.
        "MEGOOARTI_UI_URL": f"http://localhost:{HTTP_PORT}",
        "MEGOOARTI_INITIAL_PASSWORD": password,
        "CI": "1",
    }

    result = subprocess.run(
        [pnpm, "exec", "playwright", "test"],
        cwd=FRONTEND,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )

    said = f"exit {result.returncode}\n{result.stdout[-6000:]}\n{result.stderr[-2000:]}"
    assert result.returncode == 0, said
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed[1]) >= 51, said
    assert not re.search(r"\d+ (failed|skipped|did not run)", result.stdout), said


def test_a_client_cannot_say_which_address_it_comes_from(stack):
    """The sign-in limit is counted by address, and the log names it: neither may be forged."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1/auth/login",
        method="POST",
        data=b'{"username": "nobody-at-all", "password": "wrong"}',
        headers={"Content-Type": "application/json", "X-Forwarded-For": "203.0.113.77"},
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=30)

    logged = compose("logs", "--no-color", "backend").stdout
    assert refused.value.code == 401
    assert "login_failed" in logged
    assert "203.0.113.77" not in logged

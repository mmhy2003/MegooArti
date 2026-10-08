"""Python's own packaging tools against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to
pull the Python image, and to install twine and uv into it from pypi.org. Everything
those tools then upload or install goes to MegooArti.
"""

import subprocess
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "python:3.13-slim"
NETWORK = f"{PROJECT}_default"
HOSTED = "pypi-hosted"
# What a publishing account gets: everything on PyPI repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "uploads-and-installs-python-packages"
PROJECT_NAME = "megooarti-greeter"

# Writes a wheel and a source distribution of one small package into dist/, with the
# standard library only: `make_dist.py <version>`.
MAKE_DIST = """
import base64, hashlib, io, sys, tarfile, zipfile
from pathlib import Path

version = sys.argv[1]
name, module = "megooarti-greeter", "megooarti_greeter"
metadata = (
    "Metadata-Version: 2.1\\n"
    f"Name: {name}\\nVersion: {version}\\nSummary: Says hello\\nRequires-Python: >=3.9\\n"
)
code = f'def hello():\\n    return "hello from {name} {version}"\\n'
dist = Path("dist")
dist.mkdir(exist_ok=True)

info = f"{module}-{version}.dist-info"
files = {
    f"{module}/__init__.py": code,
    f"{info}/METADATA": metadata,
    f"{info}/WHEEL": (
        "Wheel-Version: 1.0\\nGenerator: megooarti\\n"
        "Root-Is-Purelib: true\\nTag: py3-none-any\\n"
    ),
}
record = ""
for path, text in files.items():
    digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=")
    record += f"{path},sha256={digest.decode()},{len(text.encode())}\\n"
files[f"{info}/RECORD"] = record + f"{info}/RECORD,,\\n"
with zipfile.ZipFile(dist / f"{module}-{version}-py3-none-any.whl", "w") as wheel:
    for path, text in files.items():
        wheel.writestr(path, text)

project = (
    '[build-system]\\nrequires = ["setuptools"]\\nbuild-backend = "setuptools.build_meta"\\n'
    f'[project]\\nname = "{name}"\\nversion = "{version}"\\n'
)
sources = {"PKG-INFO": metadata, "pyproject.toml": project, f"{module}/__init__.py": code}
with tarfile.open(dist / f"{module}-{version}.tar.gz", "w:gz") as sdist:
    for path, text in sources.items():
        entry = tarfile.TarInfo(f"{module}-{version}/{path}")
        entry.size = len(text.encode())
        sdist.addfile(entry, io.BytesIO(text.encode()))
"""


def inside(repository: str) -> str:
    """A repository's address as a container on the Compose network reaches it."""
    return f"http://backend:8000/repository/{repository}/"


def python(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Python image, in a copy of `directory`, beside the stack.

    Every run is a new container, so every tool starts with an empty cache.
    """
    setup = "cp -r /src /work && cd /work && export PIP_DISABLE_PIP_VERSION_CHECK=1"
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


# A shell function for a script that goes on after a failure: `command; report <step>`
# prints the command's exit code on a line of its own.
REPORT = 'report() { code=$?; printf \'\\n%s=%s\\n\' "$1" "$code"; }'


def exits(result: subprocess.CompletedProcess[str]) -> dict[str, int]:
    """The exit codes a script reported with `report <step>`."""
    lines = (line.partition("=") for line in result.stdout.splitlines())
    return {step: int(code) for step, _, code in lines if code.isdigit() and " " not in step}


def fetch(path: str, username: str = USERNAME, secret: str = PASSWORD) -> tuple[int, str]:
    """A GET to the hosted repository from outside: (status, body as text)."""
    credentials = b64encode(f"{username}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/{path}",
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, ""


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted PyPI repository, a publishing account, and an API token of that account."""
    repository = {
        "name": HOSTED,
        "format": "pypi",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    role = {"name": "pypi-publishers", "permissions": ["repository:pypi"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["pypi-publishers"],
        "must_change_password": False,
    }
    for path, body in (("/repositories", repository), ("/roles", role), ("/users", user)):
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
    status, _, created = call("POST", "/me/tokens", {"name": "publishing"}, signed_in)
    assert status == 201, created
    return created["token"]


def test_twine_and_uv_publish_and_pip_installs(token, tmp_path):
    work = tmp_path / "pypi"
    work.mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    index = f"http://{USERNAME}:{PASSWORD}@backend:8000/repository/{HOSTED}/simple/"
    token_index = f"http://__token__:{token}@backend:8000/repository/{HOSTED}/simple/"

    # twine uploads a wheel and a source distribution with a user name and a password.
    # A second upload of the same files is refused.
    twine = (
        f"twine upload --non-interactive --disable-progress-bar --repository-url {inside(HOSTED)}"
    )
    account = f"-u {USERNAME} -p {PASSWORD}"
    published = python(
        work,
        f"{REPORT}; pip install --quiet twine && python make_dist.py 1.0.0"
        f" && {twine} {account} dist/*; report first"
        f"; {twine} {account} dist/*; report again",
    )
    codes = exits(published)
    assert codes.get("first") == 0, said(published)
    assert codes.get("again") not in (0, None), "uploaded twice despite disable_redeploy"

    # uv publishes the next version with nothing but a token, as the user `__token__`.
    # Told where the index is, it passes over files that are already there. It does not
    # send the token to the index by itself, so the address carries it.
    uv = f"uv publish --publish-url {inside(HOSTED)} --token {token}"
    by_token = python(
        work,
        f"{REPORT}; pip install --quiet uv && python make_dist.py 1.1.0"
        f" && {uv} dist/*; report first"
        f"; {uv} dist/*; report again"
        f"; {uv} --check-url {token_index} dist/*; report checked",
    )
    codes = exits(by_token)
    assert codes.get("first") == 0, said(by_token)
    assert codes.get("again") not in (0, None), "uploaded twice despite disable_redeploy"
    assert codes.get("checked") == 0, said(by_token)

    # What the index says now.
    status, root_index = fetch("simple/")
    assert (status, f'<a href="{PROJECT_NAME}/">' in root_index) == (200, True)
    status, page = fetch(f"simple/{PROJECT_NAME}/", "__token__", token)
    assert status == 200
    for version in ("1.0.0", "1.1.0"):
        assert f">megooarti_greeter-{version}-py3-none-any.whl</a>" in page
        assert f">megooarti_greeter-{version}.tar.gz</a>" in page
    assert page.count('data-requires-python="&gt;=3.9"') == 4
    assert page.count("#sha256=") == 4

    # pip installs the newest version from an empty cache, then one it is asked for.
    pip = f"pip install --quiet --index-url {index} --trusted-host backend"
    run_it = 'python -c "import megooarti_greeter; print(megooarti_greeter.hello())"'
    installed = python(
        work, f"{pip} {PROJECT_NAME} && {run_it} && {pip} {PROJECT_NAME}==1.0.0 && {run_it}"
    )
    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-2:] == [
        f"hello from {PROJECT_NAME} 1.1.0",
        f"hello from {PROJECT_NAME} 1.0.0",
    ]

    # uv installs it too, with the token.
    with_uv = python(
        work,
        "pip install --quiet uv"
        f" && uv pip install --system --index-url {token_index} {PROJECT_NAME}==1.1.0"
        f" && {run_it}",
    )
    assert with_uv.returncode == 0, said(with_uv)
    assert with_uv.stdout.splitlines()[-1] == f"hello from {PROJECT_NAME} 1.1.0"

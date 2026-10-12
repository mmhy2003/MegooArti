"""Python's own packaging tools against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to
pull the Python image, to install twine and uv into it from pypi.org for the first
test, and for the proxy of pypi.org that the second test installs everything through.
"""

import subprocess
import urllib.error
import urllib.request
from base64 import b64decode, b64encode
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call, upload

pytestmark = pytest.mark.docker

IMAGE = "python:3.13-slim"
NETWORK = f"{PROJECT}_default"
HOSTED = "pypi-hosted"
PROXY = "pypi-proxy"
GROUP = "pypi-public"
# What a publishing account gets: everything on PyPI repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "uploads-and-installs-python-packages"
PROJECT_NAME = "megooarti-greeter"
# Uploaded to the hosted repository and installed through the group. It requires PUBLIC.
OURS = "megooarti-grouped"
# A real public package with no dependencies, and the name of another one.
PUBLIC = "six"
TAKEN = "sampleproject"

# Writes a wheel and a source distribution of one small package into dist/, with the
# standard library only: `make_dist.py <name> <version> [<requirement> ...]`.
MAKE_DIST = """
import base64, hashlib, io, sys, tarfile, zipfile
from pathlib import Path

name, version, requirements = sys.argv[1], sys.argv[2], sys.argv[3:]
module = name.replace("-", "_")
metadata = (
    "Metadata-Version: 2.1\\n"
    f"Name: {name}\\nVersion: {version}\\nSummary: Says hello\\nRequires-Python: >=3.9\\n"
    + "".join(f"Requires-Dist: {requirement}\\n" for requirement in requirements)
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
    return f"http://gateway/repository/{repository}/"


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


def fetch(
    path: str,
    username: str = USERNAME,
    secret: str = PASSWORD,
    *,
    repository: str = HOSTED,
    method: str = "GET",
) -> tuple[int, str]:
    """A request to a repository from outside: (status, body as text)."""
    credentials = b64encode(f"{username}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{repository}/{path}",
        method=method,
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
    index = f"http://{USERNAME}:{PASSWORD}@gateway/repository/{HOSTED}/simple/"
    token_index = f"http://__token__:{token}@gateway/repository/{HOSTED}/simple/"

    # twine uploads a wheel and a source distribution with a user name and a password.
    # A second upload of the same files is refused.
    twine = (
        f"twine upload --non-interactive --disable-progress-bar --repository-url {inside(HOSTED)}"
    )
    account = f"-u {USERNAME} -p {PASSWORD}"
    published = python(
        work,
        f"{REPORT}; pip install --quiet twine && python make_dist.py {PROJECT_NAME} 1.0.0"
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
        f"{REPORT}; pip install --quiet uv && python make_dist.py {PROJECT_NAME} 1.1.0"
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
    pip = f"pip install --quiet --index-url {index} --trusted-host gateway"
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


@pytest.fixture(scope="module")
def group_index(token, administrator) -> str:
    """A proxy of pypi.org and a group of the hosted repository and it.

    Returns the group's index address as a container reaches it, with the token in it.
    """
    proxy = {
        "name": PROXY,
        "format": "pypi",
        "type": "proxy",
        "proxy": {"remote_url": "https://pypi.org"},
    }
    public = {
        "name": GROUP,
        "format": "pypi",
        "type": "group",
        "group": {"members": [HOSTED, PROXY]},
    }
    for body in (proxy, public):
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    return f"http://__token__:{token}@gateway/repository/{GROUP}/simple/"


def test_pip_uv_and_poetry_install_through_a_group(token, group_index, tmp_path):
    work = tmp_path / "group"
    (work / "consumer").mkdir(parents=True)
    (work / "published").mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    source = f'[[tool.poetry.source]]\nname = "megooarti"\nurl = "{inside(GROUP)}simple/"\n'
    (work / "consumer" / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "consumer"\nversion = "1.0.0"\ndescription = ""\n'
        'authors = ["CI <ci@example.com>"]\npackage-mode = false\n\n'
        f'[tool.poetry.dependencies]\npython = ">=3.9"\n{OURS} = "1.0.0"\n\n'
        f'{source}priority = "primary"\n',
        encoding="utf-8",
        newline="\n",
    )
    (work / "published" / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "megooarti-poetic"\nversion = "1.0.0"\ndescription = "x"\n'
        'authors = ["CI <ci@example.com>"]\npackages = [{include = "megooarti_poetic.py"}]\n\n'
        '[build-system]\nrequires = ["poetry-core"]\nbuild-backend = "poetry.core.masonry.api"\n',
        encoding="utf-8",
        newline="\n",
    )
    (work / "published" / "megooarti_poetic.py").write_text("VALUE = 1\n", encoding="utf-8")
    # Every tool is itself installed through the group: many real packages by the proxy.
    pip = f"pip install --quiet --index-url {group_index} --trusted-host gateway"
    twine = (
        "twine upload --non-interactive --disable-progress-bar"
        f" --repository-url {inside(HOSTED)} -u __token__ -p {token}"
    )
    run_it = (
        f'python -c "import megooarti_grouped, {PUBLIC};'
        f' print(megooarti_grouped.hello(), {PUBLIC}.__name__)"'
    )
    expected = f"hello from {OURS} 1.0.0 {PUBLIC}"

    # Our own package, which requires a public one, and our own package under a name
    # the public index has too. twine sends the token as Python tools do.
    published = python(
        work,
        f"{pip} twine && python make_dist.py {OURS} 1.0.0 {PUBLIC}"
        f" && python make_dist.py {TAKEN} 99.0.0 && {twine} dist/*",
    )
    assert published.returncode == 0, said(published)

    # What the group says: the public project from the proxy, with its links here, and
    # under the name we host only what we host.
    status, public = fetch(f"simple/{PUBLIC}/", repository=GROUP)
    assert status == 200
    assert public.count(f'href="../../packages/{PUBLIC}/') > 10
    assert "pythonhosted.org" not in public and "data-core-metadata" in public
    assert fetch(f"simple/{PUBLIC}/", repository=GROUP, method="HEAD")[0] == 200
    status, taken = fetch(f"simple/{TAKEN}/", repository=GROUP)
    assert (status, taken.count("<a ")) == (200, 2)
    assert f">{TAKEN}-99.0.0-py3-none-any.whl</a>" in taken
    status, upstream = fetch(f"simple/{TAKEN}/", repository=PROXY)
    assert status == 200 and "99.0.0" not in upstream and upstream.count("<a ") > 2

    # Each client installs our package, and through it the public one, from an empty cache.
    clients = {
        "pip": f"{pip} {OURS} && {run_it}",
        "uv": f"{pip} uv && uv pip install --system --index-url {group_index} {OURS} && {run_it}",
        "poetry": (
            f"{pip} poetry && export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring"
            f" && poetry config http-basic.megooarti __token__ {token}"
            " && cd consumer && poetry install --no-interaction"
            f" && poetry run {run_it}"
        ),
    }
    for client, script in clients.items():
        installed = python(work, script)
        assert installed.returncode == 0, f"{client}: {said(installed)}"
        assert installed.stdout.splitlines()[-1] == expected, f"{client}: {said(installed)}"

    # What was installed came through the proxy, and is cached there.
    status, cached = fetch("simple/", repository=PROXY)
    assert status == 200 and f'<a href="{PUBLIC}/">' in cached

    # Poetry builds a package of its own and publishes it to the hosted repository.
    by_poetry = python(
        work,
        f"{pip} poetry && export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring"
        f" && cd published && poetry config repositories.hosted {inside(HOSTED)}"
        f" && poetry publish --build --no-interaction -r hosted -u __token__ -p {token}",
    )
    assert by_poetry.returncode == 0, said(by_poetry)
    status, poetic = fetch("simple/megooarti-poetic/")
    assert (status, poetic.count("<a ")) == (200, 2)


def test_files_uploaded_through_the_api_are_installed_by_pip(token, tmp_path):
    """A wheel and a source distribution go in through the content API, and pip installs."""
    name = "megooarti-uploaded"
    work = tmp_path / "uploaded"
    work.mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    made = python(
        work,
        f"python make_dist.py {name} 1.0.0 > /dev/null"
        ' && for file in dist/*; do echo "$(basename $file) $(base64 -w0 $file)"; done',
    )
    assert made.returncode == 0, said(made)
    files = {
        filename: b64decode(encoded)
        for filename, _, encoded in (line.partition(" ") for line in made.stdout.splitlines())
    }
    wheel, sdist = "megooarti_uploaded-1.0.0-py3-none-any.whl", "megooarti_uploaded-1.0.0.tar.gz"
    assert sorted(files) == [wheel, sdist]
    signed_in = {"Authorization": f"Bearer {token}"}
    parts = [("file", filename, content) for filename, content in files.items()]

    status, stored = upload(HOSTED, {"requires_python": ">=3.9"}, parts, signed_in)
    assert status == 201, stored
    assert sorted(file["path"] for file in stored["files"]) == [
        f"packages/{name}/1.0.0/{wheel}",
        f"packages/{name}/1.0.0/{sdist}",
    ]
    assert [found["name"] for found in stored["components"]] == [name]
    status, again = upload(HOSTED, {}, parts[:1], signed_in)
    assert (status, again["error"]["code"]) == (409, "redeploy_disabled")

    status, page = fetch(f"simple/{name}/", "__token__", token)
    assert status == 200
    assert page.count('data-requires-python="&gt;=3.9"') == 2
    component = stored["components"][0]["id"]
    status, _, detail = call("GET", f"/content/{HOSTED}/components/{component}", None, signed_in)
    assert status == 200, detail
    address = f"http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/"
    assert [entry["text"] for entry in detail["usage"]] == [
        f"pip install --index-url {address}simple/ {name}==1.0.0"
    ]

    # pip installs it from an empty cache, by the index's own pages.
    index = f"http://{USERNAME}:{PASSWORD}@gateway/repository/{HOSTED}/simple/"
    pip = f"pip install --quiet --index-url {index} --trusted-host gateway"
    run_it = 'python -c "import megooarti_uploaded; print(megooarti_uploaded.hello())"'
    installed = python(work, f"{pip} {name}==1.0.0 && {run_it}")
    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-1] == f"hello from {name} 1.0.0"

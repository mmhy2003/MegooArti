"""What the guides say, held against what the code is.

A guide is read by somebody who has nothing else. Where a guide names a variable, an
address of the API, a member of the format interface, a file or another guide, that
thing is looked up here, so that a guide cannot name what is not there, and what an
operator must know cannot be added to the code without being written down.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from pydantic_core import PydanticUndefined

from megooarti import __version__
from megooarti import main as _main  # noqa: F401  (registers every format)
from megooarti.config import Settings
from megooarti.repositories.formats import Format, format_names

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
# The guides a release is published with (NFR-18), and what else there is to read.
GUIDES = [
    "docs/installation.md",
    "docs/configuration.md",
    "docs/upgrade.md",
    "docs/backup.md",
    "docs/administration.md",
    "docs/repositories.md",
    "docs/formats/maven.md",
    "docs/formats/npm.md",
    "docs/formats/pypi.md",
    "docs/formats/docker.md",
    "docs/formats/raw.md",
    "docs/web-ui.md",
    "docs/api.md",
    "docs/development.md",
    "docs/adding-a-format.md",
]
DOCUMENTS = ["README.md", "CHANGELOG.md", *GUIDES]
# Variables a guide may name that are neither a setting nor read by Compose.
OTHER_VARIABLES = {
    "MEGOOARTI_RUN_MIGRATIONS",  # the entrypoint's
    "MEGOOARTI_TEST_DATABASE_URL",  # the tests'
    "MEGOOARTI_UPDATE_OPENAPI",  # the test that writes the API's description
    "MEGOOARTI_TOKEN",  # a shell variable of the examples: an API token
}


def read(document: str) -> str:
    return (ROOT / document).read_text(encoding="utf-8")


def prose(text: str) -> str:
    """A document without its blocks of code: a `#` there is a comment, not a heading."""
    return re.sub(r"^```.*?^```", "", text, flags=re.DOTALL | re.MULTILINE)


def slug(heading: str) -> str:
    """The address a heading gets where the guides are read (GitHub's rule)."""
    kept = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return kept.replace(" ", "-")


def anchors(document: str) -> set[str]:
    return {slug(found) for found in re.findall(r"^#+ (.+)$", prose(read(document)), re.MULTILINE)}


def rows(text: str, heading: str) -> list[list[str]]:
    """The rows of the first table under a heading, each as its cells."""
    under = text.split(f"\n{heading}\n", 1)[1]
    table = re.search(r"((?:^\|.*\|\n)+)", under, flags=re.MULTILINE)[1]
    cells = [[cell.strip() for cell in line.strip("|\n").split("|")] for line in table.splitlines()]
    return cells[2:]  # without the names of the columns and the line under them


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_guide_is_there_and_says_something(document):
    text = read(document)

    assert text.startswith("# ")
    assert len(text.splitlines()) > 10
    assert text.endswith("\n") and "\r" not in text


def test_the_readme_is_a_quick_start_and_a_map_of_every_guide():
    readme = read("README.md")

    assert len(readme.splitlines()) <= 100
    assert "## Quick start" in readme and "docker compose up" in readme
    for guide in GUIDES:
        assert f"]({guide})" in readme, guide


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_link_to_a_file_or_a_heading_of_this_repository_leads_somewhere(document):
    here = (ROOT / document).parent
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", prose(read(document))):
        if re.match(r"[a-z]+:", target):
            continue  # another site: not looked up, by a test that reaches no network
        path, _, anchor = target.partition("#")
        file = (here / path).resolve() if path else ROOT / document
        if not file.exists():
            broken.append(target)
        elif anchor and anchor not in anchors(file.relative_to(ROOT).as_posix()):
            broken.append(target)

    assert broken == []


@pytest.mark.parametrize("document", DOCUMENTS)
def test_tables_are_written_as_the_editors_check_wants_them(document):
    under_the_names = re.findall(r"^\|[\s:|-]+\|$", prose(read(document)), flags=re.MULTILINE)

    assert [line for line in under_the_names if not re.fullmatch(r"\|( --- \|)+", line)] == []


# --- configuration ---------------------------------------------------------------------


def written(default: object, name: str) -> str:
    """A setting's default as the guide writes it."""
    if default is PydanticUndefined:
        return "required"
    if name == "secret_key":
        return "generated"
    if default is None:
        return "unset"
    if isinstance(default, bool):
        return f"`{str(default).lower()}`"
    if isinstance(default, float):
        return f"`{default:g}`"
    return f"`{Path(default).as_posix() if isinstance(default, Path) else default}`"


def test_every_setting_is_in_the_guide_with_the_default_it_has():
    documented = {
        row[0].strip("`"): row[1]
        for row in rows(read("docs/configuration.md"), "## The backend's environment")
    }
    expected = {
        f"MEGOOARTI_{name.upper()}": written(field.default, name)
        for name, field in Settings.model_fields.items()
    }

    assert documented.pop("MEGOOARTI_RUN_MIGRATIONS") == "`true`"  # the entrypoint's own
    assert documented == expected


def compose_reads() -> set[str]:
    whole = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend = yaml.safe_load(whole)["services"]["backend"]["environment"]
    passed_on = {name for name, value in backend.items() if value is None}
    return set(re.findall(r"\$\{(MEGOOARTI_[A-Z_]+)", whole)) | passed_on


def test_everything_compose_reads_is_in_the_guide():
    documented = {
        row[0].strip("`") for row in rows(read("docs/configuration.md"), "## What Compose reads")
    }

    assert documented == compose_reads()


@pytest.mark.parametrize("document", DOCUMENTS)
def test_a_guide_names_no_variable_that_nothing_reads(document):
    settings = {f"MEGOOARTI_{name.upper()}" for name in Settings.model_fields}
    known = settings | compose_reads() | OTHER_VARIABLES

    assert set(re.findall(r"MEGOOARTI_[A-Z_]+", read(document))) - known == set()


# --- the API ---------------------------------------------------------------------------


def api_paths() -> list[list[str]]:
    described = json.loads((ROOT / "frontend" / "openapi.json").read_text(encoding="utf-8"))
    return [path.removeprefix("/api/v1").strip("/").split("/") for path in described["paths"]]


def is_described(mentioned: str, paths: list[list[str]]) -> bool:
    """Whether an address a guide names is one the API has. `<name>` stands for any part."""
    asked = mentioned.split("?")[0].removeprefix("/api/v1").strip("/").split("/")
    for path in paths:
        if len(path) != len(asked):
            continue
        if all(
            ours.startswith("{") or theirs.startswith(("<", "{")) or ours == theirs
            for ours, theirs in zip(path, asked, strict=True)
        ):
            return True
    return False


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_address_of_the_api_that_a_guide_names_is_one_the_api_has(document):
    paths = api_paths()
    mentioned = set(re.findall(r"/api/v1/[A-Za-z0-9_/<>{}.?=*+%:-]*", read(document)))
    mentioned = {address.rstrip(".:") for address in mentioned}
    # The description itself is served by the application, and is no operation of it.
    mentioned.discard("/api/v1/openapi.json")

    assert sorted(address for address in mentioned if not is_described(address, paths)) == []


def test_the_check_of_addresses_knows_one_that_is_not_there():
    paths = api_paths()

    assert is_described("/api/v1/repositories/<name>/rebuild-index", paths)
    assert is_described("/api/v1/content/maven-releases/tree?path=com/acme", paths)
    assert is_described("/api/v1/users/{id}/password", paths)
    assert not is_described("/api/v1/repositories/<name>/rebuild", paths)
    assert not is_described("/api/v1/setting", paths)


def test_the_guide_sends_each_kind_of_address_where_the_gateway_sends_it():
    gateway = (ROOT / "gateway" / "nginx.conf").read_text(encoding="utf-8")
    routes = dict(re.findall(r"location (\S+) \{\s*proxy_pass \$(\w+);\s*\}", gateway))
    table = rows(read("docs/installation.md"), "## Behind your own reverse proxy")
    said = {row[0].strip("`"): row[1].split(",")[0] for row in table}

    assert said.pop("everything else") == routes.pop("/")
    assert said == routes


# --- formats ---------------------------------------------------------------------------

CLIENTS = {
    "maven": ["Maven", "Gradle", "sbt"],
    "npm": ["npm", "pnpm", "Yarn"],
    "pypi": ["pip", "uv", "Poetry", "twine"],
    "docker": ["Docker", "skopeo"],
    "raw": ["curl"],
}


def test_every_format_has_a_guide_that_the_readme_leads_to():
    assert sorted(format_names()) == sorted(CLIENTS)
    for name in format_names():
        assert (DOCS / "formats" / f"{name}.md").is_file(), name
        assert f"](docs/formats/{name}.md)" in read("README.md")


@pytest.mark.parametrize(("name", "clients"), sorted(CLIENTS.items()))
def test_a_formats_guide_names_every_client_it_is_tested_with(name, clients):
    guide = read(f"docs/formats/{name}.md")

    assert [client for client in clients if client not in guide] == []


def test_the_guide_to_adding_a_format_names_every_member_of_the_interface():
    guide = read("docs/adding-a-format.md")
    members = [name for name in vars(Format) if not name.startswith("_")]

    assert len(members) > 20
    assert [name for name in members if f"| `{name}` |" not in guide] == []
    # And none that the interface no longer has.
    listed = [row[0].strip("`") for row in rows(guide, "## What a format says of itself")]
    assert sorted(listed) == sorted(members)


# --- what a guide points at ------------------------------------------------------------

# Folders that are not in the repository: tools make them where they are used.
MADE_WHEN_USED = {"backend/.test-failures/", "frontend/node_modules/next/dist/docs/"}


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_file_of_the_repository_that_a_guide_names_is_there(document):
    named = set(
        re.findall(r"`((?:backend|frontend|scripts|gateway|docs)/[\w./<>-]+)`", read(document))
    )
    named |= set(re.findall(r"(?<![\w/])(scripts/\w+\.(?:sh|py))", read(document)))
    missing = []
    for path in named - MADE_WHEN_USED:
        if "<" in path:
            continue  # a pattern of a name, not a name
        at_root, in_backend = ROOT / path, ROOT / "backend" / path
        if not at_root.exists() and not in_backend.exists():
            missing.append(path)

    assert sorted(missing) == []


def test_the_changelog_begins_with_this_version():
    versions = re.findall(r"^## (.+)$", read("CHANGELOG.md"), flags=re.MULTILINE)

    assert versions[0] == __version__
    assert "### Known issues" in read("CHANGELOG.md")

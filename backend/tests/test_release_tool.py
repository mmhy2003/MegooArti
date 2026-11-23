"""The release tool (tools/release/versions.py), on a git repository of its own."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "versions", ROOT / "tools" / "release" / "versions.py"
)
versions = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(versions)


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def write(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")


def set_version(repo: Path, version: str) -> None:
    write(repo, "VERSION", f"{version}\n")
    write(repo, "backend/pyproject.toml", f'[project]\nname = "megooarti"\nversion = "{version}"\n')
    write(
        repo,
        "backend/src/megooarti/__init__.py",
        f'"""MegooArti."""\n\n__version__ = "{version}"\n',
    )
    write(
        repo,
        "frontend/package.json",
        json.dumps({"name": "megooarti-frontend", "version": version}),
    )


def commit(repo: Path, message: str = "a change") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    set_version(tmp_path, "0.1.0")
    write(tmp_path, "gateway/Caddyfile", ":80 {\n}\n")
    write(tmp_path, "docs/releases/v0.1.0.md", "The first release.\n")
    commit(tmp_path, "first")
    return tmp_path


def test_a_release_version_is_exactly_three_numbers():
    assert versions.parse("0.1.0") == (0, 1, 0)
    assert versions.parse("v1.2.3") == (1, 2, 3)
    assert versions.parse("dev") is None
    assert versions.parse("0.1.0-dev+abc") is None
    assert versions.parse("1.0") is None


def test_versions_are_ordered_as_numbers():
    assert versions.parse("0.10.0") > versions.parse("0.9.0")


def test_check_passes_when_the_four_places_agree(repo):
    assert versions.check(repo) == []


@pytest.mark.parametrize("path", list(versions.PLACES))
def test_check_names_the_place_that_differs(repo, path):
    text = (repo / path).read_text(encoding="utf-8")
    write(repo, path, text.replace("0.1.0", "0.2.0"))

    errors = versions.check(repo)

    assert len(errors) == 1
    assert path in errors[0]


def test_check_refuses_a_version_that_is_not_a_release(repo):
    set_version(repo, "dev")

    assert any("not a release version" in error for error in versions.check(repo))


def test_before_the_first_release_there_is_nothing_to_guard(repo):
    assert versions.guard(repo) == []


def test_a_change_since_the_last_release_needs_a_new_version(repo):
    git(repo, "tag", "v0.1.0")
    write(repo, "backend/app.py", "print('new')\n")
    commit(repo)

    errors = versions.guard(repo)

    assert len(errors) == 1
    assert "backend/app.py" in errors[0]
    assert "bump it" in errors[0]

    set_version(repo, "0.1.1")
    commit(repo, "0.1.1")

    assert versions.guard(repo) == []


@pytest.mark.parametrize("path", ["docker-compose.yml", "gateway/Caddyfile", ".env.example"])
def test_the_compose_file_the_gateway_and_the_example_are_part_of_it(repo, path):
    git(repo, "tag", "v0.1.0")
    write(repo, path, "# changed\n")
    commit(repo)

    assert versions.guard(repo) != []


def test_a_change_to_the_guides_needs_no_new_version(repo):
    git(repo, "tag", "v0.1.0")
    write(repo, "docs/installation.md", "# Installation\n")
    commit(repo)

    assert versions.guard(repo) == []


def test_a_version_lower_than_the_last_release_is_refused(repo):
    git(repo, "tag", "v0.2.0")

    errors = versions.guard(repo)

    assert any("lower than the last release v0.2.0" in error for error in errors)


def test_plan_before_any_release_releases_this_version(repo):
    assert versions.plan(repo) == {"app": "true", "app_version": "0.1.0"}


def test_plan_releases_nothing_for_a_version_already_tagged(repo):
    git(repo, "tag", "v0.1.0")

    assert versions.plan(repo)["app"] == "false"


def test_plan_fails_without_the_note(repo, capsys):
    git(repo, "rm", "-q", "docs/releases/v0.1.0.md")
    commit(repo)

    with pytest.raises(SystemExit):
        versions.plan(repo)

    assert "docs/releases/v0.1.0.md" in capsys.readouterr().err


def test_plan_wants_the_note_known_to_git(repo):
    git(repo, "tag", "v0.1.0")
    set_version(repo, "0.1.1")
    commit(repo, "0.1.1")
    write(repo, "docs/releases/v0.1.1.md", "A fix.\n")

    with pytest.raises(SystemExit):
        versions.plan(repo)

    git(repo, "add", "docs/releases/v0.1.1.md")

    assert versions.plan(repo) == {"app": "true", "app_version": "0.1.1"}


def test_the_command_prints_lines_for_github_output(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)

    assert versions.main(["plan"]) == 0
    assert capsys.readouterr().out == "app=true\napp_version=0.1.0\n"
    assert versions.main(["guard"]) == 2

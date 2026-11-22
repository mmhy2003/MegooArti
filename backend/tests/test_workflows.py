"""The GitHub Actions workflows run only on GitHub, so their text is checked here."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def runs(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def test_ci_runs_on_pushes_pull_requests_and_for_the_release():
    ci = workflow("ci.yml")
    # PyYAML reads the key `on` as the boolean True.
    assert set(ci[True]) == {"push", "pull_request", "workflow_call"}
    assert ci["permissions"] == {"contents": "read"}


def test_ci_runs_the_fast_suites_and_the_version_check():
    jobs = workflow("ci.yml")["jobs"]
    backend = runs(jobs["backend"])
    joined = "\n".join(backend)
    for command in (
        "uv sync --locked",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pytest",
        "tools/release/versions.py check",
    ):
        assert command in joined
    assert not any("-m docker" in line for line in backend)

    frontend = runs(jobs["frontend"])
    for command in (
        "pnpm install --frozen-lockfile",
        "pnpm test",
        "pnpm lint",
        "pnpm typecheck",
        "pnpm build",
    ):
        assert command in frontend


def test_ci_gives_the_tests_the_database_they_expect():
    postgres = workflow("ci.yml")["jobs"]["backend"]["services"]["postgres"]
    assert postgres["image"] == "postgres:17-alpine"
    assert postgres["env"] == {
        "POSTGRES_USER": "megooarti",
        "POSTGRES_PASSWORD": "megooarti",
        "POSTGRES_DB": "megooarti",
    }


def test_only_a_push_to_main_releases_and_one_release_at_a_time():
    release = workflow("release.yml")
    assert release[True] == {"push": {"branches": ["main"]}}
    assert release["concurrency"] == {"group": "release", "cancel-in-progress": False}
    assert release["permissions"] == {"contents": "write", "packages": "write"}


def test_the_release_runs_ci_and_the_start_up_check_before_pushing():
    jobs = workflow("release.yml")["jobs"]
    assert jobs["tests"]["uses"] == "./.github/workflows/ci.yml"
    assert set(jobs["images"]["needs"]) == {"plan", "tests", "app"}
    assert "images" in jobs["publish"]["needs"]
    for name, job in jobs.items():
        if name != "plan":
            assert job["if"] == "needs.plan.outputs.app == 'true'", name


def test_the_start_up_check_runs_the_images_just_built():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    # Without --pull missing, Compose would fetch the published images over the ones just built.
    ups = [line for line in text.splitlines() if "docker compose" in line and " up " in line]
    assert ups
    for line in ups:
        assert "--pull missing" in line
        assert "-f docker-compose.yml" in line


def test_a_rerun_finds_the_release_already_made():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert re.search(
        r'gh release view "v\$VERSION" > /dev/null 2>&1 \|\| gh release create "v\$VERSION"', text
    )
    assert '--notes-file "docs/releases/v$VERSION.md"' in text
    assert '--title "MegooArti $VERSION"' in text


def test_both_platforms_are_built_on_their_own_machines():
    jobs = workflow("release.yml")["jobs"]
    assert jobs["images"]["strategy"]["matrix"]["include"] == [
        {"arch": "amd64", "os": "ubuntu-latest"},
        {"arch": "arm64", "os": "ubuntu-24.04-arm"},
    ]
    publish = "\n".join(runs(jobs["publish"]))
    assert '-t "$name:$VERSION"' in publish
    assert '-t "$name:latest"' in publish

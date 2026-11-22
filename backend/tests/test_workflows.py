"""The GitHub Actions workflows run only on GitHub, so their text is checked here."""

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

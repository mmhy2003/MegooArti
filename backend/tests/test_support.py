"""Tests of the test support code that every later test relies on."""

import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI

from tests import containers
from tests.clients import client_for
from tests.databases import reset_schema
from tests.failures import KEPT, keep_failure


async def test_client_for_runs_the_application_lifespan():
    events = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    async with client_for(app):
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]


@pytest.mark.parametrize("name", ["megooarti", "production", "megooarti_test_backup"])
def test_reset_schema_refuses_a_database_not_named_for_tests(name):
    url = f"postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/{name}"

    with pytest.raises(ValueError, match="_test"):
        reset_schema(url)


def test_what_a_failed_setup_said_is_kept_in_a_file_of_its_own(tmp_path):
    kept = keep_failure(
        tmp_path / "failures",
        "tests/security/test_roles.py::test_a_role[a/b c]",
        "setup",
        "OSError: [WinError 64] The specified network name is no longer available",
        now=datetime(2026, 10, 13, 8, 30, tzinfo=UTC),
    )

    assert kept.parent == tmp_path / "failures"
    assert kept.name == (
        "20261013T083000000000-setup-tests_security_test_roles.py_test_a_role_a_b_c_.txt"
    )
    said = kept.read_text(encoding="utf-8")
    assert said.startswith("tests/security/test_roles.py::test_a_role[a/b c] (setup)\n")
    assert "WinError 64" in said


def test_only_the_newest_failures_are_kept(tmp_path):
    start = datetime(2026, 10, 13, tzinfo=UTC)
    for minute in range(KEPT + 3):
        keep_failure(
            tmp_path, f"test_{minute}", "setup", "x", now=start + timedelta(minutes=minute)
        )

    names = sorted(path.name for path in tmp_path.iterdir())

    assert len(names) == KEPT
    assert names[0].endswith("-setup-test_3.txt")
    assert names[-1].endswith(f"-setup-test_{KEPT + 2}.txt")


def test_a_setup_that_fails_is_kept_and_a_test_that_fails_is_not(pytester):
    pytester.makeconftest(
        """
        from pathlib import Path
        from tests.failures import keep_broken_setup

        def pytest_runtest_logreport(report):
            keep_broken_setup(report, Path("kept"))
        """
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def broken():
            raise OSError("the database went away")

        def test_needs_it(broken):
            pass

        def test_fails_by_itself():
            assert 1 == 2
        """
    )

    result = pytester.runpytest_inprocess("-p", "no:cacheprovider", "-p", "no:asyncio")

    result.assert_outcomes(errors=1, failed=1)
    (kept,) = (pytester.path / "kept").iterdir()
    assert "-setup-" in kept.name
    assert "the database went away" in kept.read_text(encoding="utf-8")


def _docker_answers(monkeypatch, returncode: int, stderr: str) -> None:
    def run(command, **_):
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(containers.subprocess, "run", run)


def test_a_compose_command_that_fails_says_what_docker_said(monkeypatch):
    refusal = "failed to solve: python:3.13-slim: failed to resolve source metadata: timeout"
    _docker_answers(monkeypatch, 1, f"#1 [internal] load build definition\n{refusal}\n")

    with pytest.raises(containers.ComposeFailed) as caught:
        containers.compose("build")

    assert str(caught.value).startswith("docker compose build exited with 1:")
    assert refusal in str(caught.value)
    assert caught.value.returncode == 1


def test_a_compose_command_that_may_fail_is_answered_as_it_ended(monkeypatch):
    _docker_answers(monkeypatch, 1, "no such service")

    result = containers.compose("down", "--volumes", check=False)

    assert (result.returncode, result.stderr) == (1, "no such service")

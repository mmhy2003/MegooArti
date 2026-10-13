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
from tests.failures import (
    KEPT,
    keep_broken_setup,
    keep_failure,
    keep_stack_logs,
    say_where,
)


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
        from tests.failures import keep_broken_setup, say_where

        kept = []

        def pytest_runtest_logreport(report):
            path = keep_broken_setup(report, Path("kept"))
            if path is not None:
                kept.append(path)

        def pytest_terminal_summary(terminalreporter):
            say_where(terminalreporter.write_line, kept)
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
    # A file nobody knows of is a file nobody reads: the run says where it is.
    result.stdout.fnmatch_lines(["*1 failed setup kept in *kept*"])


def test_a_failure_that_cannot_be_kept_does_not_cost_the_run(tmp_path):
    # Where the folder should be there is a file: nothing can be written into it.
    (tmp_path / "taken").write_text("not a folder", encoding="utf-8")

    class Report:
        failed, when, nodeid, longreprtext = True, "setup", "tests/test_x.py::test_y", "OSError"

    assert keep_broken_setup(Report(), tmp_path / "taken") is None
    # And nothing is said of failures that were not kept.
    said: list[str] = []
    say_where(said.append, [])
    assert said == []


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


class _Report:
    """What pytest reports of one phase of one test, as far as the hooks look at it."""

    def __init__(self, *, failed: bool, when: str = "call", docker: bool = True) -> None:
        self.failed, self.when = failed, when
        self.nodeid = "tests/test_pypi_client.py::test_pip_installs"
        self.longreprtext = "AssertionError: pip: exit 1"
        self.keywords = {"docker": 1} if docker else {}


def test_what_the_stack_said_is_kept_when_a_test_of_it_fails(tmp_path):
    said = "backend-1  | remote_failed repository=pypi-proxy reason=it did not answer in time\n"

    kept = keep_stack_logs(_Report(failed=True), lambda: said, tmp_path)

    assert kept is not None and "-call-logs-" in kept.name
    assert "remote_failed repository=pypi-proxy" in kept.read_text(encoding="utf-8")


def test_the_stack_is_not_asked_when_nothing_failed_or_the_test_is_not_of_it(tmp_path):
    def asked() -> str:
        raise AssertionError("the stack was asked")

    assert keep_stack_logs(_Report(failed=False), asked, tmp_path) is None
    assert keep_stack_logs(_Report(failed=True, docker=False), asked, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_a_stack_that_says_nothing_or_cannot_be_asked_does_not_cost_the_run(tmp_path):
    def gone() -> str:
        raise FileNotFoundError("docker")

    assert keep_stack_logs(_Report(failed=True, when="setup"), lambda: "  \n", tmp_path) is None
    assert keep_stack_logs(_Report(failed=True), gone, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_the_end_of_the_run_says_how_many_of_each_were_kept(tmp_path):
    said: list[str] = []
    one, two = tmp_path / "a.txt", tmp_path / "b.txt"

    say_where(said.append, [one])
    say_where(said.append, [one, two], "log of the stack", "logs of the stack")

    assert said == [
        f"1 failed setup kept in {tmp_path}",
        f"2 logs of the stack kept in {tmp_path}",
    ]

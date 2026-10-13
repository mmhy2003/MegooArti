"""The script that measures how long answers take (NFR-4): what it asks of the load
generator, and how it reads what the generator reports."""

import importlib.util
import subprocess
import sys

import httpx
import pytest

from tests.containers import BACKEND_DIR, HTTP_PORT, PROJECT, call

SCRIPT = BACKEND_DIR / "scripts" / "latency.py"


def load_script():
    spec = importlib.util.spec_from_file_location("megooarti_latency_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


latency = load_script()

# What oha 1.16 reports, cut to what is read. Times are in seconds.
REPORT = {
    "summary": {"successRate": 1.0, "slowest": 0.5846, "requestsPerSec": 201.34},
    "latencyPercentiles": {"p50": 0.4919, "p95": 0.5576, "p99": 0.5847},
    "statusCodeDistribution": {"200": 2000},
    "errorDistribution": {},
}


def test_the_generator_is_a_container_of_one_version_on_the_network_it_is_told():
    command = latency.command(
        "http://gateway/repository/files/a.txt",
        clients=100,
        total=2000,
        headers={"Authorization": "Basic abc", "Accept": "text/plain"},
        network="megooarti_default",
    )

    assert command[:5] == ["docker", "run", "--rm", "--network", "megooarti_default"]
    assert command[5] == latency.GENERATOR == "ghcr.io/hatoo/oha:1.16.0"
    # Not drawn on a screen, and reported so that it can be read.
    assert command[6:9] == ["--no-tui", "--output-format", "json"]
    assert command[9:13] == ["-n", "2000", "-c", "100"]
    assert command[13:17] == ["-H", "Authorization: Basic abc", "-H", "Accept: text/plain"]
    assert command[-1] == "http://gateway/repository/files/a.txt"


def test_what_the_generator_reports_is_read_in_milliseconds():
    measured = latency.read("session", 2000, REPORT)

    assert (measured.p50, measured.p95, measured.p99) == (491.9, 557.6, 584.7)
    assert (measured.slowest, measured.per_second, measured.failed) == (584.6, 201.34, 0)
    assert measured.line().split() == ["session", "491.9", "557.6", "584.7", "584.6", "201", "0"]
    # The columns stand under their headings.
    assert len(measured.line()) == len(latency.HEADING)


def test_an_answer_that_is_not_what_was_asked_for_has_failed_and_so_has_one_that_never_came():
    refused = {**REPORT, "statusCodeDistribution": {"200": 1900, "401": 60, "502": 30}}

    measured = latency.read("maven metadata", 2000, refused)

    # 90 answers that were not the file, and 10 requests that were not answered at all.
    assert measured.failed == 100
    assert measured.line().split()[-1] == "100"


def test_a_server_that_answered_nothing_is_said_to_have_answered_nothing():
    silent = {
        "summary": {"successRate": 0.0, "slowest": None, "requestsPerSec": 0.0},
        "latencyPercentiles": {"p50": None, "p95": None, "p99": None},
        "statusCodeDistribution": {},
        "errorDistribution": {"connection refused": 40},
    }

    measured = latency.read("raw file", 40, silent)

    assert measured.line() == f"{'raw file':<24} no request was answered (40 failed)"


def _installation(there: set[str], deleted: list[str]) -> httpx.AsyncClient:
    """An installation that has the repositories `there`, and writes down what is deleted."""

    def answer(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            deleted.append(name)
            return httpx.Response(204 if name in there else 404)
        return httpx.Response(200 if name in there else 404, json={"name": name})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://measured")


async def test_the_script_removes_the_repositories_it_makes_and_no_other():
    # `latency-dashboards` is somebody's own: its name begins as the script's do.
    there, deleted = {"latency-dashboards", "latency-raw", "releases"}, []

    async with _installation(there, deleted) as client:
        await latency.clean_up(client)

    assert sorted(deleted) == sorted(latency.NAMES)
    assert latency.NAMES == [
        "latency-maven-proxy",  # first: a proxy before what it is a proxy of
        "latency-raw",
        "latency-maven",
        "latency-npm",
        "latency-pypi",
        "latency-docker",
    ]


async def test_the_script_does_not_begin_where_a_repository_of_its_names_is_there():
    there, deleted = {"latency-npm", "latency-raw"}, []

    async with _installation(there, deleted) as client:
        with pytest.raises(SystemExit) as stopped:
            await latency.claim(client, replace=False)

    # It may be what an earlier run left, and it may be somebody's: the script does not know.
    assert "latency-raw, latency-npm" in str(stopped.value)
    assert "--replace" in str(stopped.value)
    assert deleted == []


async def test_the_script_begins_where_none_is_there_or_where_it_is_told_to_replace_them():
    deleted: list[str] = []
    async with _installation(set(), deleted) as client:
        await latency.claim(client, replace=False)
    assert deleted == []

    async with _installation({"latency-raw"}, deleted) as client:
        await latency.claim(client, replace=True)
    assert "latency-raw" in deleted


@pytest.mark.docker
def test_the_latency_script_measures_every_format_and_leaves_nothing_behind(administrator):
    status, _, created = call("POST", "/me/tokens", {"name": "latency-test"}, administrator)
    assert status == 201

    measured = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *("--url", f"http://127.0.0.1:{HTTP_PORT}"),
            *("--token", created["token"]),
            *("--network", f"{PROJECT}_default", "--inside-url", "http://gateway"),
            *("--clients", "5", "--requests", "3"),
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )

    assert measured.returncode == 0, measured.stdout + measured.stderr
    lines = measured.stdout.splitlines()
    assert lines[0] == "5 clients at once, 3 requests each, of http://gateway"
    names = [" ".join(line.split()[:-6]) for line in lines[2:]]
    assert names == [
        "raw file",
        "maven metadata",
        "npm document",
        "pypi page",
        "docker manifest",
        "maven metadata, proxy",
    ]
    assert all(line.split()[-1] == "0" for line in lines[2:]), measured.stdout  # none failed
    status, _, listed = call("GET", "/repositories", headers=administrator)
    assert not [item["name"] for item in listed["items"] if item["name"].startswith("latency-")]

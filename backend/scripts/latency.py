"""How long a request for metadata takes when many clients ask at once (NFR-4).

Run from the backend/ directory, against an installation that is running, with an API
token of an administrator. Against the Compose stack of this repository:

    uv run python scripts/latency.py --url http://localhost:8000 --token mga_... \\
        --network megooarti_default --inside-url http://gateway

It makes a repository of each format, named `latency-...`, and puts one small thing
into each, as that format's clients would. Then, for each format, `--clients` clients
at once ask, `--requests` times each, for what a client asks for before anything else:
Maven's metadata of an artifact, npm's document of a package, PyPI's page of a project,
a registry's manifest by tag, a Raw file. It prints how long the answers took, and
removes what it made.

The asking is done by `oha`, a load generator, in a container of its own (Docker is
needed where this runs): a program in Python cannot ask fast enough to measure a server
and measures itself instead. `--network` is the Docker network that container joins,
and `--inside-url` the installation's address on it. Without them the container uses
the host's network and `--url`. With `--inside-url`, a Maven proxy of the
installation's own repository is made and asked as well: an answer from a proxy's
cache, which is what NFR-4 names.

The token is on the command line of that container, where whoever may list the
processes of this machine can read it: use one made for the measurement, and revoke it.

The numbers are of the machine the installation runs on, with the load generator
taking its share of it when both are on one machine. They say nothing of another.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass

import httpx

GENERATOR = "ghcr.io/hatoo/oha:1.16.0"
PREFIX = "latency"
PACKAGE = "latency-package"
JAR = "com/acme/latency/1.0/latency-1.0.jar"
MAVEN_METADATA = "com/acme/latency/maven-metadata.xml"
WHEEL = "latency_package-1.0.0-py3-none-any.whl"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"

HEADING = f"{'':<24}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}{'per s':>10}{'failed':>8}"


@dataclass(frozen=True)
class Measured:
    name: str
    # In milliseconds, of every answer; None where there was no answer at all.
    p50: float | None
    p95: float | None
    p99: float | None
    slowest: float | None
    per_second: float
    failed: int  # answers that were not 200, and requests that got none

    def line(self) -> str:
        if self.p50 is None:
            return f"{self.name:<24} no request was answered ({self.failed} failed)"
        numbers = "".join(
            f"{value:>9.1f}" for value in (self.p50, self.p95, self.p99, self.slowest)
        )
        return f"{self.name:<24}{numbers}{self.per_second:>10.0f}{self.failed:>8}"


def command(
    url: str, *, clients: int, total: int, headers: dict[str, str], network: str
) -> list[str]:
    """The load generator, as a container: `total` requests from `clients` at once."""
    said = [argument for name, value in headers.items() for argument in ("-H", f"{name}: {value}")]
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        GENERATOR,
        "--no-tui",
        "--output-format",
        "json",
        "-n",
        str(total),
        "-c",
        str(clients),
        *said,
        url,
    ]


def read(name: str, total: int, report: dict) -> Measured:
    """What the load generator reported of one address, as one line of the table."""
    answered = report.get("statusCodeDistribution") or {}
    percentiles = report.get("latencyPercentiles") or {}
    summary = report.get("summary") or {}

    def milliseconds(seconds: float | None) -> float | None:
        return None if seconds is None else round(seconds * 1000, 3)

    return Measured(
        name=name,
        p50=milliseconds(percentiles.get("p50")),
        p95=milliseconds(percentiles.get("p95")),
        p99=milliseconds(percentiles.get("p99")),
        slowest=milliseconds(summary.get("slowest")),
        per_second=summary.get("requestsPerSec") or 0.0,
        failed=total - int(answered.get("200", 0)),
    )


def measure(
    name: str, url: str, *, clients: int, requests: int, headers: dict[str, str], network: str
) -> Measured:
    total = clients * requests
    asked = subprocess.run(
        command(url, clients=clients, total=total, headers=headers, network=network),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if asked.returncode != 0:
        raise SystemExit(f"the load generator could not be run:\n{asked.stderr[-2000:]}")
    return read(name, total, json.loads(asked.stdout))


def _expect(response: httpx.Response, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        request = response.request
        raise SystemExit(
            f"{request.method} {request.url}: {response.status_code} {response.text[:300]}"
        )
    return response


def _npm_publish(package: str, version: str) -> dict:
    data = f"\x1f\x8b a tarball of {package}@{version}".encode()
    dist = {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": f"http://client.example/{package}/-/{package}-{version}.tgz",
    }
    return {
        "_id": package,
        "name": package,
        "dist-tags": {"latest": version},
        "versions": {version: {"name": package, "version": version, "dist": dist}},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(data).decode(),
                "length": len(data),
            }
        },
    }


async def _push_image(client: httpx.AsyncClient, repository: str) -> None:
    config = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
    layer = b"\x1f\x8b a layer"
    described = []
    for data in (config, layer):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        begun = _expect(await client.post(f"/v2/{repository}/app/blobs/uploads/"), 202)
        sent = _expect(await client.patch(begun.headers["Location"], content=data), 202)
        _expect(await client.put(sent.headers["Location"], params={"digest": digest}), 201)
        described.append({"digest": digest, "size": len(data)})
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json", **described[0]},
        "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", **described[1]}],
    }
    _expect(
        await client.put(
            f"/v2/{repository}/app/manifests/1.0",
            content=json.dumps(manifest).encode(),
            headers={"Content-Type": OCI_MANIFEST},
        ),
        201,
    )


async def set_up(client: httpx.AsyncClient, inside_url: str | None, token: str) -> list[tuple]:
    """Make the repositories and what is in them. Returns (name, path, headers) to ask for."""
    for format in ("raw", "maven", "npm", "pypi", "docker"):
        body = {"name": f"{PREFIX}-{format}", "format": format, "type": "hosted"}
        _expect(await client.post("/api/v1/repositories", json=body), 201)
    _expect(await client.put(f"/repository/{PREFIX}-raw/a/file.txt", content=b"a file"), 201)
    _expect(await client.put(f"/repository/{PREFIX}-maven/{JAR}", content=b"PK a jar"), 201)
    published = _npm_publish(PACKAGE, "1.0.0")
    _expect(await client.put(f"/repository/{PREFIX}-npm/{PACKAGE}", json=published), 200, 201)
    wheel = {"file": (WHEEL, b"PK a wheel", "application/octet-stream")}
    _expect(await client.post(f"/api/v1/content/{PREFIX}-pypi/upload", files=wheel), 201)
    await _push_image(client, f"{PREFIX}-docker")
    targets = [
        ("raw file", f"/repository/{PREFIX}-raw/a/file.txt", {}),
        ("maven metadata", f"/repository/{PREFIX}-maven/{MAVEN_METADATA}", {}),
        ("npm document", f"/repository/{PREFIX}-npm/{PACKAGE}", {}),
        ("pypi page", f"/repository/{PREFIX}-pypi/simple/{PACKAGE}/", {}),
        ("docker manifest", f"/v2/{PREFIX}-docker/app/manifests/1.0", {"Accept": OCI_MANIFEST}),
    ]
    if inside_url:
        proxy = {
            "name": f"{PREFIX}-maven-proxy",
            "format": "maven",
            "type": "proxy",
            "proxy": {
                "remote_url": f"{inside_url.rstrip('/')}/repository/{PREFIX}-maven",
                "remote_auth": {"type": "bearer", "secret": token},
            },
        }
        _expect(await client.post("/api/v1/repositories", json=proxy), 201)
        path = f"/repository/{PREFIX}-maven-proxy/{MAVEN_METADATA}"
        _expect(await client.get(path), 200)  # fetched once: from now on it is the cache's
        targets.append(("maven metadata, proxy", path, {}))
    return targets


async def clean_up(client: httpx.AsyncClient) -> None:
    listed = _expect(await client.get("/api/v1/repositories", params={"limit": 200}), 200)
    ours = [item for item in listed.json()["items"] if item["name"].startswith(f"{PREFIX}-")]
    # A proxy before what it is a proxy of: nothing else here depends on anything.
    for repository in sorted(ours, key=lambda item: item["type"] != "proxy"):
        _expect(await client.delete(f"/api/v1/repositories/{repository['name']}"), 204, 404)


async def run(arguments: argparse.Namespace) -> int:
    basic = base64.b64encode(f"__token__:{arguments.token}".encode()).decode()
    credential = {"Authorization": f"Basic {basic}"}
    asked_at = (arguments.inside_url or arguments.url).rstrip("/")
    how = {"clients": arguments.clients, "network": arguments.network}
    async with httpx.AsyncClient(
        base_url=arguments.url.rstrip("/"), headers=credential, timeout=60.0
    ) as client:
        await clean_up(client)  # of a run that was stopped
        failed = 0
        try:
            targets = await set_up(client, arguments.inside_url, arguments.token)
            print(
                f"{arguments.clients} clients at once, {arguments.requests} requests each, "
                f"of {asked_at}"
            )
            print(HEADING)
            for name, path, headers in targets:
                headers = {**credential, **headers}
                # Once before the clock runs: the connections' first requests are the slow ones.
                measure(name, asked_at + path, requests=1, headers=headers, **how)
                measured = measure(
                    name, asked_at + path, requests=arguments.requests, headers=headers, **how
                )
                print(measured.line())
                failed += measured.failed
        finally:
            if not arguments.keep:
                await clean_up(client)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="the installation, as this machine reaches it")
    parser.add_argument("--token", required=True, help="an API token of an administrator")
    parser.add_argument("--clients", type=int, default=100, help="how many ask at once (100)")
    parser.add_argument("--requests", type=int, default=20, help="how often each asks (20)")
    parser.add_argument("--network", default="host", help="the Docker network of the generator")
    parser.add_argument("--inside-url", help="the installation, as containers on it reach it")
    parser.add_argument("--keep", action="store_true", help="leave the repositories it made")
    return parser


if __name__ == "__main__":
    sys.exit(asyncio.run(run(build_parser().parse_args())))

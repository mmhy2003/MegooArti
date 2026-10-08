"""Maven's own client against the built image.

Run with `pytest -m docker`. Besides a Docker daemon these need internet access: Maven
fetches its plugins from Maven Central.
"""

import hashlib
import re
import subprocess
import urllib.request
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.versions import compare
from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "maven:3.9-eclipse-temurin-21"
NETWORK = f"{PROJECT}_default"
CACHE = f"{PROJECT}-maven-cache"
# The backend as a container on the Compose network sees it, and as this test does.
INSIDE = "http://backend:8000/repository"
OUTSIDE = f"http://127.0.0.1:{HTTP_PORT}/repository"
LIBRARY = "io/megooarti/test/library"
MAVEN = "mvn --batch-mode --settings settings.xml"

# Maven refuses plain HTTP to another host unless its built-in blocking mirror is
# replaced. The stack has no TLS, so the test replaces it with one that matches nothing.
SETTINGS = """<settings>
  <servers>
    <server><id>megooarti</id><username>admin</username><password>{token}</password></server>
    <server>
      <id>megooarti-snapshots</id><username>admin</username><password>{token}</password>
    </server>
  </servers>
  <mirrors>
    <mirror>
      <id>maven-default-http-blocker</id>
      <mirrorOf>external:does-not-match-anything:*</mirrorOf>
      <url>http://0.0.0.0/</url>
      <blocked>false</blocked>
    </mirror>
  </mirrors>
</settings>
"""

LIBRARY_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.megooarti.test</groupId>
  <artifactId>library</artifactId>
  <version>{version}</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <distributionManagement>
    <repository><id>megooarti</id><url>{server}/releases/</url></repository>
    <snapshotRepository><id>megooarti</id><url>{server}/snapshots/</url></snapshotRepository>
  </distributionManagement>
</project>
"""

LIBRARY_SOURCE = """package io.megooarti.test;

public class Library {
    public static String greeting() {
        return "hello";
    }
}
"""

CONSUMER_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.megooarti.test</groupId>
  <artifactId>consumer</artifactId>
  <version>1</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <repositories>
    <repository>
      <id>megooarti</id>
      <url>{server}/releases/</url>
      <snapshots><enabled>false</enabled></snapshots>
    </repository>
    <repository>
      <id>megooarti-snapshots</id>
      <url>{server}/snapshots/</url>
      <releases><enabled>false</enabled></releases>
      <snapshots><enabled>true</enabled></snapshots>
    </repository>
  </repositories>
  <dependencies>
    <dependency>
      <groupId>io.megooarti.test</groupId>
      <artifactId>library</artifactId>
      <version>{version}</version>
    </dependency>
  </dependencies>
</project>
"""

CONSUMER_SOURCE = """package io.megooarti.test.consumer;

import io.megooarti.test.Library;

public class Consumer {
    public static String greeting() {
        return Library.greeting();
    }
}
"""


def write(directory: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return directory


def library(directory: Path, version: str, token: str) -> Path:
    files = {
        "settings.xml": SETTINGS.format(token=token),
        "pom.xml": LIBRARY_POM.format(version=version, server=INSIDE),
        "src/main/java/io/megooarti/test/Library.java": LIBRARY_SOURCE,
    }
    return write(directory, files)


def consumers(directory: Path, versions: dict[str, str], token: str) -> Path:
    """One project per name in `versions`, each depending on that version of the library."""
    files = {"settings.xml": SETTINGS.format(token=token)}
    for name, version in versions.items():
        files[f"{name}/pom.xml"] = CONSUMER_POM.format(version=version, server=INSIDE)
        files[f"{name}/src/main/java/io/megooarti/test/consumer/Consumer.java"] = CONSUMER_SOURCE
    return write(directory, files)


def maven(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Maven image, in a copy of `project`, beside the stack."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{CACHE}:/root/.m2",
        "--volume",
        f"{project}:/src:ro",
        IMAGE,
        "sh",
        "-c",
        f"cp -r /src /work && cd /work && {script}",
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )


def fetch(path: str, token: str) -> bytes:
    request = urllib.request.Request(
        f"{OUTSIDE}/{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


@pytest.fixture(scope="module")
def token(administrator) -> Iterator[str]:
    """An API token for `admin`, with a release and a snapshot repository to deploy to."""
    status, _, created = call("POST", "/me/tokens", {"name": "maven-client"}, administrator)
    assert status == 201
    for name, version_policy, deployment_policy in (
        ("releases", "release", "disable_redeploy"),
        ("snapshots", "snapshot", "allow_redeploy"),
    ):
        repository = {
            "name": name,
            "format": "maven",
            "type": "hosted",
            "hosted": {"deployment_policy": deployment_policy},
            "format_config": {"version_policy": version_policy},
        }
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body
    yield created["token"]
    subprocess.run(["docker", "volume", "rm", "--force", CACHE], capture_output=True, check=False)


def test_maven_deploys_a_release_and_two_snapshot_builds_and_resolves_them(token, tmp_path):
    release = library(tmp_path / "release", "1.0", token)
    snapshot = library(tmp_path / "snapshot", "1.1-SNAPSHOT", token)

    deployed = maven(release, f"{MAVEN} deploy")
    assert deployed.returncode == 0, deployed.stdout[-4000:]
    again = maven(release, f"{MAVEN} deploy")
    assert again.returncode != 0, "a release was deployed twice despite disable_redeploy"
    assert "409" in again.stdout, again.stdout[-4000:]
    for _ in range(2):
        built = maven(snapshot, f"{MAVEN} deploy")
        assert built.returncode == 0, built.stdout[-4000:]

    jar = fetch(f"releases/{LIBRARY}/1.0/library-1.0.jar", token)
    sha1 = fetch(f"releases/{LIBRARY}/1.0/library-1.0.jar.sha1", token)
    assert jar.startswith(b"PK")
    assert sha1.decode() == hashlib.sha1(jar).hexdigest()
    assert b"<artifactId>library</artifactId>" in fetch(
        f"releases/{LIBRARY}/1.0/library-1.0.pom", token
    )
    listed = metadata.parse(fetch(f"releases/{LIBRARY}/maven-metadata.xml", token))
    assert (listed.versions, listed.latest, listed.release) == (("1.0",), "1.0", "1.0")

    directory = f"snapshots/{LIBRARY}/1.1-SNAPSHOT"
    builds = metadata.parse(fetch(f"{directory}/maven-metadata.xml", token))
    newest = {entry.extension: entry.value for entry in builds.snapshot_versions}
    assert builds.snapshot_build == 2
    assert set(newest) == {"jar", "pom"}
    assert newest["jar"].endswith("-2")
    assert fetch(f"{directory}/library-{newest['jar']}.jar", token).startswith(b"PK")

    # A local repository that has never seen the library: everything comes from the server.
    versions = {"release": "1.0", "snapshot": "1.1-SNAPSHOT"}
    projects = consumers(tmp_path / "consumers", versions, token)
    fresh = f"{MAVEN} -Dmaven.repo.local=/tmp/empty-repository"
    resolved = maven(
        projects, f"{fresh} -f release/pom.xml compile && {fresh} -f snapshot/pom.xml compile"
    )
    assert resolved.returncode == 0, resolved.stdout[-4000:]
    assert f"Downloaded from megooarti: {INSIDE}/releases/{LIBRARY}/1.0/library-1.0.jar" in (
        resolved.stdout
    )
    assert (
        f"Downloaded from megooarti-snapshots: {INSIDE}/{directory}/library-{newest['jar']}.jar"
        in resolved.stdout
    )


# Ordinary versions, the qualifiers, and the forms that are easy to get wrong.
VERSIONS = [
    "1.0",
    "1.0-alpha-1",
    "1.0-a2",
    "1.0-beta-1",
    "1.0-m3",
    "1.0-rc1",
    "1.0-cr1",
    "1.0-SNAPSHOT",
    "1.0-final",
    "1.0.0",
    "1",
    "1.0-sp1",
    "1.0-1",
    "1.0.1",
    "1.1",
    "1.10",
    "1.9",
    "2.0-1",
    "2.0.1",
    "1.2.3-jre",
    "1.2.3-android",
    "1.2.3",
    "1.2.3.RELEASE",
    "5.0.0.Final",
    "5.0.0",
    "4.1.0.Beta1",
    "4.1.0.Final",
    "1.0.RC1",
    "1.0-RC1",
    "1.0.RC2",
    "1.foo",
    "1-foo",
    "1-1",
    "1-sp-1",
    "1-ga-1",
    "1-sp.1",
    "1-ga.1",
    "20040616",
    "3.0-M1",
    "3.0",
]


def test_our_version_order_is_mavens():
    """Maven compares each version with the one before it; so do we."""
    java = (
        "java -cp /usr/share/maven/lib/maven-artifact-*.jar "
        "org.apache.maven.artifact.versioning.ComparableVersion"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", IMAGE, "sh", "-c", f"{java} {' '.join(VERSIONS)}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    theirs = re.findall(r"^\s+(\S+) (<|==|>) (\S+)$", result.stdout, re.MULTILINE)
    symbol = {-1: "<", 0: "==", 1: ">"}
    ours = [(one, symbol[compare(one, other)], other) for one, other in pairwise(VERSIONS)]

    assert [tuple(line) for line in theirs] == ours

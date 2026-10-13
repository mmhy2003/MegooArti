"""The clients of a Maven repository against the built image: Maven, Gradle and sbt.

Run with `pytest -m docker`. Besides a Docker daemon these need internet access: each
client fetches its plugins, and what the test libraries depend on, from Maven Central,
through the proxy the tests make.
"""

import base64
import hashlib
import json
import random
import re
import subprocess
import urllib.request
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.versions import compare
from tests.containers import HTTP_PORT, PROJECT, call, upload

pytestmark = pytest.mark.docker

IMAGE = "maven:3.9-eclipse-temurin-21"
NETWORK = f"{PROJECT}_default"
CACHE = f"{PROJECT}-maven-cache"
# The installation as a container on the Compose network reaches it, and as this test
# does: both through the gateway, as every client of a real installation does.
INSIDE = "http://gateway/repository"
OUTSIDE = f"http://127.0.0.1:{HTTP_PORT}/repository"
LIBRARY = "io/megooarti/test/library"
MAVEN = "mvn --batch-mode --settings settings.xml"
# What a CI account gets: it may add and read, and may not edit or delete.
USERNAME = "ci"
PASSWORD = "deploys-with-add-and-read-only"

# Maven refuses plain HTTP to another host unless its built-in blocking mirror is
# replaced. The stack has no TLS, so the test replaces it with one that matches nothing.
SETTINGS = """<settings>
  <servers>
    <server><id>megooarti</id><username>{username}</username><password>{password}</password></server>
    <server>
      <id>megooarti-snapshots</id><username>{username}</username><password>{password}</password>
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

CREDENTIALS = SETTINGS.format(username=USERNAME, password=PASSWORD)

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

# Gradle. It publishes what Maven does and a file of its own beside the POM (the
# "module"), with four checksums of each, and prefers the module when it resolves.
GRADLE_IMAGE = "gradle:8-jdk21"
GRADLE_CACHE = f"{PROJECT}-gradle-cache"
GRADLE = "gradle --no-daemon --console=plain"
GRADLE_LIBRARY = "io/megooarti/test/gradle-library"
# One repository of the installation, as a Gradle build names it. Plain HTTP must be
# allowed by name: the stack has no TLS.
GRADLE_REPOSITORY = """{{
        url = uri('{server}/{name}')
        allowInsecureProtocol = true
        credentials {{
            username = '{username}'
            password = '{password}'
        }}
    }}"""

GRADLE_LIBRARY_BUILD = """plugins {{
    id 'java-library'
    id 'maven-publish'
}}

group = 'io.megooarti.test'
version = '{version}'

java {{
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}}

repositories {{
    maven {everything}
}}

dependencies {{
    api 'org.apache.commons:commons-lang3:3.14.0'
}}

publishing {{
    publications {{
        library(MavenPublication) {{
            from components.java
        }}
    }}
    repositories {{
        maven {target}
    }}
}}
"""

GRADLE_LIBRARY_SOURCE = """package io.megooarti.test;

import org.apache.commons.lang3.StringUtils;

public class GradleLibrary {
    public static String greeting() {
        return StringUtils.capitalize("hello");
    }
}
"""

GRADLE_CONSUMER_BUILD = """plugins {{
    id 'java'
}}

repositories {{
    maven {everything}
}}

dependencies {{
    implementation 'io.megooarti.test:gradle-library:{version}'
}}
"""

GRADLE_CONSUMER_SOURCE = """package io.megooarti.test.consumer;

import io.megooarti.test.GradleLibrary;

public class Consumer {
    public static String greeting() {
        return GradleLibrary.greeting();
    }
}
"""

# sbt. It resolves with Coursier and publishes with Ivy, in Maven's layout. The image
# is the one that has this sbt and this Scala in it, so that only what the build
# depends on is fetched.
SBT_IMAGE = "sbtscala/scala-sbt:eclipse-temurin-21.0.12_8_1.13.0_2.13.18"
SBT = "sbt -batch -Dsbt.color=false -Dsbt.supershell=false"
SBT_LIBRARY = "io/megooarti/test/sbt-library"
# What every sbt build of these tests says of the installation: where everything comes
# from, and who asks. The realm is the one the server names when it asks who is there.
SBT_SERVER = """ThisBuild / scalaVersion := "2.13.18"
ThisBuild / organization := "io.megooarti.test"
ThisBuild / crossPaths := false
ThisBuild / autoScalaLibrary := false
ThisBuild / credentials += Credentials("MegooArti", "gateway", "{username}", "{password}")
ThisBuild / externalResolvers := Seq(
  ("megooarti" at "{server}/maven-public").withAllowInsecureProtocol(true)
)
"""

SBT_LIBRARY_BUILD = """name := "sbt-library"
version := "{version}"
libraryDependencies += "org.apache.commons" % "commons-text" % "1.12.0"
publishMavenStyle := true
publishTo := {{
  val name = if (isSnapshot.value) "snapshots" else "releases"
  Some(("megooarti-" + name at "{server}/" + name).withAllowInsecureProtocol(true))
}}
"""

SBT_LIBRARY_SOURCE = """package io.megooarti.test;

import org.apache.commons.text.WordUtils;

public class SbtLibrary {
    public static String greeting() {
        return WordUtils.capitalize("hello");
    }
}
"""

SBT_CONSUMER_BUILD = """name := "sbt-consumer"
version := "1"
libraryDependencies += "io.megooarti.test" % "sbt-library" % "{version}"
"""

SBT_CONSUMER_SOURCE = """package io.megooarti.test.consumer;

import io.megooarti.test.SbtLibrary;

public class Consumer {
    public static String greeting() {
        return SbtLibrary.greeting();
    }
}
"""

CONSUMER_SOURCE = """package io.megooarti.test.consumer;

import io.megooarti.test.Library;

public class Consumer {
    public static String greeting() {
        return Library.greeting();
    }
}
"""


# Everything Maven asks for goes to one group: nothing comes from Maven Central directly.
MIRRORED = f"""<settings>
  <servers>
    <server>
      <id>megooarti</id><username>{USERNAME}</username><password>{PASSWORD}</password>
    </server>
  </servers>
  <mirrors>
    <mirror>
      <id>megooarti</id>
      <mirrorOf>*</mirrorOf>
      <url>{INSIDE}/maven-public/</url>
    </mirror>
    <mirror>
      <id>maven-default-http-blocker</id>
      <mirrorOf>external:does-not-match-anything:*</mirrorOf>
      <url>http://0.0.0.0/</url>
      <blocked>false</blocked>
    </mirror>
  </mirrors>
</settings>
"""

MIRRORED_CONSUMER_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.megooarti.test</groupId>
  <artifactId>mirrored-consumer</artifactId>
  <version>1</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>io.megooarti.test</groupId>
      <artifactId>library</artifactId>
      <version>2.0</version>
    </dependency>
  </dependencies>
</project>
"""


def write(directory: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return directory


def library(directory: Path, version: str) -> Path:
    files = {
        "settings.xml": CREDENTIALS,
        "pom.xml": LIBRARY_POM.format(version=version, server=INSIDE),
        "src/main/java/io/megooarti/test/Library.java": LIBRARY_SOURCE,
    }
    return write(directory, files)


def consumers(directory: Path, versions: dict[str, str]) -> Path:
    """One project per name in `versions`, each depending on that version of the library."""
    files = {"settings.xml": CREDENTIALS}
    for name, version in versions.items():
        files[f"{name}/pom.xml"] = CONSUMER_POM.format(version=version, server=INSIDE)
        files[f"{name}/src/main/java/io/megooarti/test/consumer/Consumer.java"] = CONSUMER_SOURCE
    return write(directory, files)


def client(
    image: str, cache: str | None, project: Path, script: str
) -> subprocess.CompletedProcess[str]:
    """Run a shell script in a client's image, in a copy of `project`, beside the stack.

    `cache` is a volume and where the client keeps what it fetched, as `name:/path`.
    """
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        *(["--volume", cache] if cache else []),
        "--volume",
        f"{project}:/src:ro",
        image,
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


def maven(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    return client(IMAGE, f"{CACHE}:/root/.m2", project, script)


def gradle(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    return client(GRADLE_IMAGE, f"{GRADLE_CACHE}:/home/gradle/.gradle", project, script)


def sbt(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    # No volume: the image has sbt and the compiler it names, and the rest is fetched.
    return client(SBT_IMAGE, None, project, script)


def fetch(path: str) -> bytes:
    basic = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"{OUTSIDE}/{path}", headers={"Authorization": f"Basic {basic}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


@pytest.fixture(scope="module")
def repositories(administrator) -> Iterator[None]:
    """A release and a snapshot repository, and the CI account that deploys to them."""
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
    central = {
        "name": "central",
        "format": "maven",
        "type": "proxy",
        # Not left alone after one failure: the internet may be slow once (L7).
        "proxy": {"remote_url": "https://repo1.maven.org/maven2", "auto_block": False},
    }
    everything = {
        "name": "maven-public",
        "format": "maven",
        "type": "group",
        "group": {"members": ["releases", "snapshots", "central"]},
    }
    for repository in (central, everything):
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body
    role = {
        "name": "maven-deployers",
        "permissions": ["repository:maven:*:add", "repository:maven:*:read"],
    }
    status, _, body = call("POST", "/roles", role, administrator)
    assert status == 201, body
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["maven-deployers"],
        "must_change_password": False,
    }
    status, _, body = call("POST", "/users", user, administrator)
    assert status == 201, body
    yield
    for volume in (CACHE, GRADLE_CACHE):
        subprocess.run(
            ["docker", "volume", "rm", "--force", volume], capture_output=True, check=False
        )


def test_maven_deploys_a_release_and_two_snapshot_builds_and_resolves_them(repositories, tmp_path):
    release = library(tmp_path / "release", "1.0")
    snapshot = library(tmp_path / "snapshot", "1.1-SNAPSHOT")

    deployed = maven(release, f"{MAVEN} deploy")
    assert deployed.returncode == 0, deployed.stdout[-4000:]
    again = maven(release, f"{MAVEN} deploy")
    assert again.returncode != 0, "a release was deployed twice"
    # 403, not 409: replacing a file needs `edit`, which this account lacks. With `edit`
    # the repository's disable_redeploy policy would refuse it instead.
    assert "status code: 403" in again.stdout, again.stdout[-4000:]
    for _ in range(2):
        built = maven(snapshot, f"{MAVEN} deploy")
        assert built.returncode == 0, built.stdout[-4000:]

    jar = fetch(f"releases/{LIBRARY}/1.0/library-1.0.jar")
    sha1 = fetch(f"releases/{LIBRARY}/1.0/library-1.0.jar.sha1")
    assert jar.startswith(b"PK")
    assert sha1.decode() == hashlib.sha1(jar).hexdigest()
    assert b"<artifactId>library</artifactId>" in fetch(f"releases/{LIBRARY}/1.0/library-1.0.pom")
    listed = metadata.parse(fetch(f"releases/{LIBRARY}/maven-metadata.xml"))
    assert (listed.versions, listed.latest, listed.release) == (("1.0",), "1.0", "1.0")

    directory = f"snapshots/{LIBRARY}/1.1-SNAPSHOT"
    builds = metadata.parse(fetch(f"{directory}/maven-metadata.xml"))
    newest = {entry.extension: entry.value for entry in builds.snapshot_versions}
    assert builds.snapshot_build == 2
    assert set(newest) == {"jar", "pom"}
    assert newest["jar"].endswith("-2")
    assert fetch(f"{directory}/library-{newest['jar']}.jar").startswith(b"PK")

    # A local repository that has never seen the library: everything comes from the server.
    versions = {"release": "1.0", "snapshot": "1.1-SNAPSHOT"}
    projects = consumers(tmp_path / "consumers", versions)
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


def test_maven_builds_from_an_empty_local_repository_through_a_group(
    repositories, administrator, tmp_path
):
    files = {
        "settings.xml": MIRRORED,
        "pom.xml": LIBRARY_POM.format(version="2.0", server=INSIDE),
        "src/main/java/io/megooarti/test/Library.java": LIBRARY_SOURCE,
        "consumer/pom.xml": MIRRORED_CONSUMER_POM,
        "consumer/src/main/java/io/megooarti/test/consumer/Consumer.java": CONSUMER_SOURCE,
    }
    project = write(tmp_path / "mirrored", files)
    # One local repository that starts empty. The library is removed from it between
    # the two builds, so the consumer has to resolve it through the group as well.
    local = f"{MAVEN} -Dmaven.repo.local=/tmp/local-repository"
    forget = "rm -rf /tmp/local-repository/io/megooarti"

    built = maven(project, f"{local} deploy && {forget} && {local} -f consumer/pom.xml compile")

    through = f"Downloaded from megooarti: {INSIDE}/maven-public"
    assert built.returncode == 0, built.stdout[-6000:]
    assert "repo.maven.apache.org" not in built.stdout
    assert f"{through}/org/apache/maven/plugins/" in built.stdout
    assert f"{through}/{LIBRARY}/2.0/library-2.0.jar" in built.stdout

    # What came through the group from Maven Central is now in the proxy, and the
    # checksum the proxy computes is of those bytes.
    proxied = re.search(rf"{re.escape(through)}/(org/apache/maven/\S+\.pom)", built.stdout)
    assert proxied is not None
    pom = fetch(f"central/{proxied[1]}")
    assert pom.lstrip().startswith(b"<")
    assert fetch(f"central/{proxied[1]}.sha1").decode() == hashlib.sha1(pom).hexdigest()

    # Metadata through the group: ours generated, Maven Central's fetched, both merged.
    ours = metadata.parse(fetch(f"maven-public/{LIBRARY}/maven-metadata.xml"))
    assert "2.0" in ours.versions
    compiler = "org/apache/maven/plugins/maven-compiler-plugin"
    theirs = metadata.parse(fetch(f"maven-public/{compiler}/maven-metadata.xml"))
    assert len(theirs.versions) > 10
    assert theirs.release == theirs.versions[-1]

    status, _, shown = call("GET", "/repositories/central", headers=administrator)
    assert status == 200
    assert (shown["status"]["blocked"], shown["status"]["auto_blocked_until"]) == (False, None)


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
    # Pairs a review found we ordered differently from Maven.
    "2.0.0.BUILD-SNAPSHOT",
    "2.0.0.BUILD",
    "1.0.x-SNAPSHOT",
    "1.0.x",
    "1.0.0.Final-SNAPSHOT",
    "1.0.0-SNAPSHOT",
    "4.5.13.redhat-00001",
    "4.5.13-redhat-1",
    "1.0.0",
    "1.0.0-0.1",
    "5.0.0.Final",
    "5.0.0.Final.1",
]
PARTS = ["0", "1", "2", "10", "00", "13", "a", "b", "m", "x", "rc", "cr", "alpha", "beta"]
PARTS += ["milestone", "snapshot", "final", "ga", "release", "sp", "build", "redhat", "jre"]


def made_up_versions(count: int) -> list[str]:
    """Versions assembled from the parts real ones are made of; the same list every run."""
    chooser = random.Random(20261008)
    versions = []
    for _ in range(count):
        pieces = [chooser.choice(["1", "2", "10"])]
        for _ in range(chooser.randint(0, 4)):
            pieces += [chooser.choice([".", "-", ""]), chooser.choice(PARTS)]
        versions.append("".join(pieces))
    return versions


def test_our_version_order_is_mavens():
    """Maven compares each version with the one before it; so do we."""
    versions = VERSIONS + made_up_versions(1500)
    java = (
        "java -cp /usr/share/maven/lib/maven-artifact-*.jar "
        "org.apache.maven.artifact.versioning.ComparableVersion"
    )
    # The versions go in on standard input: there are too many for a command line.
    result = subprocess.run(
        ["docker", "run", "--rm", "--interactive", IMAGE, "sh", "-c", f"{java} $(cat)"],
        input=" ".join(versions),
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
    ours = [(one, symbol[compare(one, other)], other) for one, other in pairwise(versions)]

    assert len(theirs) == len(versions) - 1
    assert [pair for pair in zip(theirs, ours, strict=True) if pair[0] != pair[1]] == []


def test_a_jar_uploaded_through_the_api_is_resolved_by_a_build(repositories, tmp_path):
    """A jar a build made is uploaded with no POM, and another build depends on it."""
    project = library(tmp_path / "built", "3.0")
    built = maven(
        project, f"{MAVEN} --quiet package > /dev/null && base64 -w0 target/library-3.0.jar"
    )
    assert built.returncode == 0, built.stdout[-4000:] + built.stderr[-2000:]
    jar = base64.b64decode(built.stdout.strip())
    assert jar.startswith(b"PK")
    basic = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    account = {"Authorization": f"Basic {basic}"}
    coordinates = {"group": "io.megooarti.test", "artifact": "library", "version": "3.0"}

    status, stored = upload("releases", coordinates, [("file", "library.jar", jar)], account)
    assert status == 201, stored
    assert [file["path"] for file in stored["files"]] == [
        f"{LIBRARY}/3.0/library-3.0.jar",
        f"{LIBRARY}/3.0/library-3.0.pom",
    ]
    # This account may add and may not edit, so it cannot upload the version again.
    status, again = upload("releases", coordinates, [("file", "library.jar", jar)], account)
    assert (status, again["error"]["code"]) == (403, "forbidden")
    status, proxied = upload("central", coordinates, [("file", "library.jar", jar)], account)
    assert (status, proxied["error"]["code"]) == (409, "upload_not_supported")

    assert fetch(f"releases/{LIBRARY}/3.0/library-3.0.jar") == jar
    sha1 = fetch(f"releases/{LIBRARY}/3.0/library-3.0.jar.sha1")
    assert sha1.decode() == hashlib.sha1(jar).hexdigest()
    listed = metadata.parse(fetch(f"releases/{LIBRARY}/maven-metadata.xml"))
    assert "3.0" in listed.versions

    # A local repository that has never seen the library: Maven reads the POM that was
    # written for it, and compiles against the jar.
    projects = consumers(tmp_path / "consumers", {"uploaded": "3.0"})
    resolved = maven(
        projects, f"{MAVEN} -Dmaven.repo.local=/tmp/empty-repository -f uploaded/pom.xml compile"
    )
    assert resolved.returncode == 0, resolved.stdout[-4000:]
    for kind in ("pom", "jar"):
        downloaded = (
            f"Downloaded from megooarti: {INSIDE}/releases/{LIBRARY}/3.0/library-3.0.{kind}"
        )
        assert downloaded in resolved.stdout, resolved.stdout[-4000:]
    assert "The POM for io.megooarti.test:library:jar:3.0 is" not in resolved.stdout


def gradle_repository(name: str) -> str:
    return GRADLE_REPOSITORY.format(server=INSIDE, name=name, username=USERNAME, password=PASSWORD)


def gradle_library(directory: Path, version: str) -> Path:
    target = "snapshots" if version.endswith("-SNAPSHOT") else "releases"
    files = {
        "settings.gradle": "rootProject.name = 'gradle-library'\n",
        "build.gradle": GRADLE_LIBRARY_BUILD.format(
            version=version,
            everything=gradle_repository("maven-public"),
            target=gradle_repository(target),
        ),
        "src/main/java/io/megooarti/test/GradleLibrary.java": GRADLE_LIBRARY_SOURCE,
    }
    return write(directory, files)


def gradle_consumer(directory: Path, version: str) -> Path:
    files = {
        "settings.gradle": "rootProject.name = 'gradle-consumer'\n",
        "build.gradle": GRADLE_CONSUMER_BUILD.format(
            version=version, everything=gradle_repository("maven-public")
        ),
        "src/main/java/io/megooarti/test/consumer/Consumer.java": GRADLE_CONSUMER_SOURCE,
    }
    return write(directory, files)


def test_gradle_publishes_a_release_and_snapshots_and_resolves_them_through_the_group(
    repositories, tmp_path
):
    release = gradle_library(tmp_path / "release", "3.0")
    snapshot = gradle_library(tmp_path / "snapshot", "3.1-SNAPSHOT")

    # The library needs a library of Maven Central's, which comes through the group.
    published = gradle(release, f"{GRADLE} publish")
    assert published.returncode == 0, said(published)
    again = gradle(release, f"{GRADLE} publish")
    assert again.returncode != 0, "a release was published twice"
    assert "status code 403" in again.stdout + again.stderr, said(again)
    for _ in range(2):
        built = gradle(snapshot, f"{GRADLE} publish")
        assert built.returncode == 0, said(built)

    # What Gradle published is there as Gradle left it: the module beside the POM, and
    # each with the checksums a client checks it by.
    directory = f"releases/{GRADLE_LIBRARY}/3.0"
    jar = fetch(f"{directory}/gradle-library-3.0.jar")
    module = fetch(f"{directory}/gradle-library-3.0.module")
    assert jar.startswith(b"PK")
    assert json.loads(module)["component"]["version"] == "3.0"
    assert b"published-with-gradle-metadata" in fetch(f"{directory}/gradle-library-3.0.pom")
    for name, content in (("gradle-library-3.0.jar", jar), ("gradle-library-3.0.module", module)):
        assert fetch(f"{directory}/{name}.sha1").decode() == hashlib.sha1(content).hexdigest()
        assert fetch(f"{directory}/{name}.sha256").decode() == hashlib.sha256(content).hexdigest()
        assert fetch(f"{directory}/{name}.sha512").decode() == hashlib.sha512(content).hexdigest()
    listed = metadata.parse(fetch(f"releases/{GRADLE_LIBRARY}/maven-metadata.xml"))
    assert (listed.versions, listed.release) == (("3.0",), "3.0")

    builds = metadata.parse(fetch(f"snapshots/{GRADLE_LIBRARY}/3.1-SNAPSHOT/maven-metadata.xml"))
    newest = {entry.extension: entry.value for entry in builds.snapshot_versions}
    assert builds.snapshot_build == 2
    assert {"jar", "pom", "module"} <= set(newest)
    assert newest["jar"].endswith("-2")

    # A Gradle that has never seen either: everything comes from the server, the public
    # library through the proxy, and Gradle reads its own module file to find it.
    for version in ("3.0", "3.1-SNAPSHOT"):
        project = gradle_consumer(tmp_path / f"consumer-{version}", version)
        resolved = gradle(
            project, f"{GRADLE} --gradle-user-home /tmp/never-used --info compileJava"
        )
        assert resolved.returncode == 0, said(resolved)
        assert "BUILD SUCCESSFUL" in resolved.stdout
        assert f"{INSIDE}/maven-public/{GRADLE_LIBRARY}/{version}/" in resolved.stdout
        assert "commons-lang3-3.14.0.jar" in resolved.stdout


def said(result: subprocess.CompletedProcess[str]) -> str:
    """The end of what a client printed, for when it failed."""
    return (result.stdout + result.stderr)[-6000:]


def sbt_project(directory: Path, build: str, sources: dict[str, str]) -> Path:
    server = SBT_SERVER.format(server=INSIDE, username=USERNAME, password=PASSWORD)
    files = {
        "project/build.properties": "sbt.version=1.13.0\n",
        "build.sbt": server + build,
        **sources,
    }
    return write(directory, files)


def sbt_library(directory: Path, version: str) -> Path:
    build = SBT_LIBRARY_BUILD.format(version=version, server=INSIDE)
    source = {"src/main/java/io/megooarti/test/SbtLibrary.java": SBT_LIBRARY_SOURCE}
    return sbt_project(directory, build, source)


def sbt_consumer(directory: Path, version: str) -> Path:
    build = SBT_CONSUMER_BUILD.format(version=version)
    source = {"src/main/java/io/megooarti/test/consumer/Consumer.java": SBT_CONSUMER_SOURCE}
    return sbt_project(directory, build, source)


def test_sbt_publishes_a_release_and_a_snapshot_and_resolves_them_through_the_group(
    repositories, tmp_path
):
    release = sbt_library(tmp_path / "release", "4.0")
    snapshot = sbt_library(tmp_path / "snapshot", "4.1-SNAPSHOT")

    # The library needs one of Maven Central's, which Coursier fetches through the group.
    published = sbt(release, f"{SBT} publish")
    assert published.returncode == 0, said(published)
    again = sbt(release, f"{SBT} publish")
    assert again.returncode != 0, "a release was published twice"
    built = sbt(snapshot, f"{SBT} publish")
    assert built.returncode == 0, said(built)

    directory = f"releases/{SBT_LIBRARY}/4.0"
    jar = fetch(f"{directory}/sbt-library-4.0.jar")
    assert jar.startswith(b"PK")
    assert fetch(f"{directory}/sbt-library-4.0.jar.sha1").decode() == hashlib.sha1(jar).hexdigest()
    pom = fetch(f"{directory}/sbt-library-4.0.pom")
    assert b"<artifactId>sbt-library</artifactId>" in pom and b"commons-text" in pom
    # sbt also publishes the sources and the documentation, each as a jar of its own.
    for classifier in ("sources", "javadoc"):
        assert fetch(f"{directory}/sbt-library-4.0-{classifier}.jar").startswith(b"PK")
    listed = metadata.parse(fetch(f"releases/{SBT_LIBRARY}/maven-metadata.xml"))
    assert (listed.versions, listed.release) == (("4.0",), "4.0")

    for version in ("4.0", "4.1-SNAPSHOT"):
        project = sbt_consumer(tmp_path / f"consumer-{version}", version)
        resolved = sbt(project, f"{SBT} compile")
        assert resolved.returncode == 0, said(resolved)
        assert "[success]" in resolved.stdout

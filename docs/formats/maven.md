# Maven repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is Maven's own, for Maven itself, Gradle and sbt.

## The repositories

One for releases, one for snapshots, a proxy of Maven Central, and a group of the
three, which is the one address a build resolves from:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "releases", "format": "maven", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"},
  "format_config": {"version_policy": "release"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "snapshots", "format": "maven", "type": "hosted",
  "format_config": {"version_policy": "snapshot"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "central", "format": "maven", "type": "proxy",
  "proxy": {"remote_url": "https://repo1.maven.org/maven2"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "maven-public", "format": "maven", "type": "group",
  "group": {"members": ["releases", "snapshots", "central"]}
}' http://localhost:8000/api/v1/repositories
```

## Maven

Point a project at the hosted repositories in its `pom.xml`:

```xml
<distributionManagement>
  <repository>
    <id>megooarti</id>
    <url>https://repo.example.com/repository/releases/</url>
  </repository>
  <snapshotRepository>
    <id>megooarti</id>
    <url>https://repo.example.com/repository/snapshots/</url>
  </snapshotRepository>
</distributionManagement>
```

and give Maven the credentials in `~/.m2/settings.xml`, under the same `id`:

```xml
<servers>
  <server>
    <id>megooarti</id>
    <username>ci</username>
    <password>an API token</password>
  </server>
</servers>
```

## What a Maven repository does

- **Version policy** (`version_policy`): `release` (default), `snapshot` or `mixed`. It
  decides which versions a repository takes, and cannot be changed after creation.
- **Layout policy** (`layout_policy`): `strict` (default) takes only paths in the Maven
  layout; `permissive` also takes other paths, as plain files.
- **Checksums are computed, never stored.** A request for `app-1.0.jar.sha1` (or `.md5`,
  `.sha256`, `.sha512`) is answered from the hash recorded for the file. A checksum that
  a client uploads is compared with the file. A wrong one is refused with `400` and
  logged as `checksum_mismatch`; the file stays. Maven itself only warns when a checksum
  upload fails, so a corrupted deploy shows in the server log, not in the build result.
- **`maven-metadata.xml` is generated** on every request from the files stored, so it is
  right after a delete and after two deploys at the same moment. What clients upload is
  accepted and discarded, except plugin prefixes, which are kept for each group.
- `latest` and `release` are the highest versions in Maven's version order, not the
  most recently deployed ones.
- **A deploying account needs `add` and `read`**, for example
  `repository:maven:releases:add` and `repository:maven:releases:read`: Maven reads a
  repository's metadata before it uploads. It does not need `edit`.
- **Maven refuses plain HTTP** to any host but `localhost` (since Maven 3.8.1). Put
  MegooArti behind HTTPS for clients on other machines.
- **A proxy** caches what it fetches. It serves the remote's `maven-metadata.xml` as
  received, and answers checksum requests from the cached file: it never asks the
  remote for a checksum file. Metadata and old-style snapshot files are checked again
  after `metadata_max_age_minutes`; release files after `content_max_age_minutes`. A
  proxy with the `release` policy does not ask its remote for snapshots.
- **A group** serves a file from the first member that has it, and merges
  `maven-metadata.xml` from every member that can answer, so one URL lists your own
  versions and the remote's. A group has no policies of its own.

## Resolving everything through the group

To send everything Maven resolves through the group, mirror it in `~/.m2/settings.xml`:

```xml
<mirrors>
  <mirror>
    <id>megooarti</id>
    <mirrorOf>*</mirrorOf>
    <url>https://repo.example.com/repository/maven-public/</url>
  </mirror>
</mirrors>
```

Reading through a group needs `read` on the group only, for example
`repository:maven:maven-public:read`.

## Gradle

Name the group as the place everything is resolved from, and the hosted repositories
as where a build publishes to:

```groovy
plugins {
    id 'java-library'
    id 'maven-publish'
}

repositories {
    maven {
        url = uri('https://repo.example.com/repository/maven-public')
        credentials {
            username = 'ci'
            password = 'an API token'
        }
    }
}

publishing {
    publications {
        library(MavenPublication) {
            from components.java
        }
    }
    repositories {
        maven {
            url = uri('https://repo.example.com/repository/releases')
            credentials {
                username = 'ci'
                password = 'an API token'
            }
        }
    }
}
```

- For a snapshot version, publish to the snapshots repository.
- Gradle publishes a file of its own beside the POM (`.module`), and SHA-256 and
  SHA-512 checksums beside the SHA-1 and MD5 ones. They are taken as Maven's are: the
  module is stored, and the checksums are compared with the files.
- Gradle refuses a repository over plain HTTP unless the repository says
  `allowInsecureProtocol = true`.

## sbt

```scala
ThisBuild / credentials += Credentials("MegooArti", "repo.example.com", "ci", "an API token")
ThisBuild / externalResolvers := Seq(
  "megooarti" at "https://repo.example.com/repository/maven-public"
)

publishMavenStyle := true
publishTo := {
  val name = if (isSnapshot.value) "snapshots" else "releases"
  Some("megooarti-" + name at "https://repo.example.com/repository/" + name)
}
```

- **The realm is `MegooArti`**, written exactly so: sbt gives its credentials only to
  the realm they are for.
- sbt publishes a snapshot under one name (`library-1.0-SNAPSHOT.jar`), not under the
  dated names Maven gives each build. Publishing it again replaces a file, so an
  account that publishes snapshots with sbt needs `edit` as well as `add`.
- Over plain HTTP, a resolver must say `.withAllowInsecureProtocol(true)`.

## Clients

Deploying and resolving are tested with Maven, Gradle and sbt.

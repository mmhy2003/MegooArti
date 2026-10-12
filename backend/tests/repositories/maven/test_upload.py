"""A Maven upload form, turned into the files it asks to be stored."""

import xml.etree.ElementTree as ElementTree

import pytest

from megooarti.repositories.maven import upload
from megooarti.repositories.maven.upload import InvalidUpload

APP = {"group": "com.acme", "artifact": "app", "version": "1.0"}
POM = "{http://maven.apache.org/POM/4.0.0}"


def test_an_artifact_goes_where_its_coordinates_say_and_gets_a_pom():
    planned = upload.plan(APP, [("file", "whatever-it-was-called.jar")])

    assert planned.paths == ("com/acme/app/1.0/app-1.0.jar",)
    assert planned.pom_path == "com/acme/app/1.0/app-1.0.pom"
    project = ElementTree.fromstring(planned.pom)
    said = {child.tag.removeprefix(POM): child.text for child in project}
    assert said == {
        "modelVersion": "4.0.0",
        "groupId": "com.acme",
        "artifactId": "app",
        "version": "1.0",
        "packaging": "jar",
    }


def test_each_part_says_what_its_file_is():
    planned = upload.plan(
        APP,
        [
            ("file", "app.jar"),
            ("file.sources", "app-sources.jar"),
            ("file.javadoc", "docs.jar"),
            ("file.linux-x86_64", "app.tar.gz"),
            ("pom", "pom.xml"),
        ],
    )

    assert [path.rpartition("/")[2] for path in planned.paths] == [
        "app-1.0.jar",
        "app-1.0-sources.jar",
        "app-1.0-javadoc.jar",
        "app-1.0-linux-x86_64.tar.gz",
        "app-1.0.pom",
    ]
    assert planned.pom is None  # one was sent


@pytest.mark.parametrize(
    ("filename", "extension"),
    [
        ("app.jar", "jar"),
        ("app-1.0.war", "war"),
        ("app-1.0.tar.gz", "tar.gz"),
        ("APP.TAR.GZ", "TAR.GZ"),
        ("app.tar.bz2", "tar.bz2"),
        ("app.jar.asc", "jar.asc"),
        ("app.tar.gz.asc", "tar.gz.asc"),
        ("app.module", "module"),
        ("pom.xml", "xml"),
        ("jar", None),
        (".jar", None),
        ("app.", None),
        (".tar.gz", "gz"),
        (".asc", None),
    ],
)
def test_the_end_of_a_name_says_what_a_file_is(filename, extension):
    assert upload.extension_of(filename) == extension


def test_a_pom_is_not_written_when_one_is_sent_or_none_is_wanted():
    as_pom = upload.plan(APP, [("file", "app.jar"), ("pom", "pom.xml")])
    as_file = upload.plan(APP, [("file", "app-1.0.pom")])
    unwanted = upload.plan({**APP, "generate_pom": "False"}, [("file", "app.jar")])

    assert (as_pom.pom, as_file.pom, unwanted.pom) == (None, None, None)
    assert as_file.paths == (as_file.pom_path,)


def test_the_pom_says_the_packaging_that_was_given():
    planned = upload.plan({**APP, "packaging": "war"}, [("file", "app.war")])

    assert b"<packaging>war</packaging>" in planned.pom
    assert planned.paths == ("com/acme/app/1.0/app-1.0.war",)


def test_a_snapshot_is_for_a_build_to_deploy():
    with pytest.raises(InvalidUpload, match="deployed by a build") as refused:
        upload.plan({**APP, "version": "1.0-SNAPSHOT"}, [("file.sources", "s.jar")])

    assert refused.value.field == "version"


def test_what_is_given_is_trimmed():
    planned = upload.plan(
        {"group": " com.acme ", "artifact": "app\n", "version": " 1.0", "packaging": " "},
        [("file", "app.jar")],
    )

    assert planned.paths == ("com/acme/app/1.0/app-1.0.jar",)
    assert b"<packaging>jar</packaging>" in planned.pom


@pytest.mark.parametrize(
    ("changes", "files", "field"),
    [
        ({"group": ""}, [("file", "a.jar")], "group"),
        ({"group": None}, [("file", "a.jar")], "group"),
        ({"artifact": None}, [("file", "a.jar")], "artifact"),
        ({"version": None}, [("file", "a.jar")], "version"),
        ({"group": "com..acme"}, [("file", "a.jar")], "group"),
        ({"group": ".com"}, [("file", "a.jar")], "group"),
        ({"group": "com/acme"}, [("file", "a.jar")], "group"),
        ({"group": "com.acme."}, [("file", "a.jar")], "group"),
        ({"artifact": "app/1"}, [("file", "a.jar")], "artifact"),
        ({"artifact": "app name"}, [("file", "a.jar")], "artifact"),
        ({"artifact": "<app>"}, [("file", "a.jar")], "artifact"),
        ({"version": ".."}, [("file", "a.jar")], "version"),
        ({"version": "1/0"}, [("file", "a.jar")], "version"),
        ({"version": "-SNAPSHOT"}, [("file", "a.jar")], "version"),
        ({"version": "1" * 256}, [("file", "a.jar")], "file"),
        ({"packaging": "a b"}, [("file", "a.jar")], "packaging"),
        ({"generate_pom": "maybe"}, [("file", "a.jar")], "generate_pom"),
        ({"classifier": "sources"}, [("file", "a.jar")], "classifier"),
        ({}, [], "file"),
        ({}, [("file", "README")], "file"),
        ({}, [("file", "a.j@r")], "file"),
        ({}, [("file", "app-1.0.jar.sha1")], "file"),
        ({}, [("file", "app.md5")], "file"),
        ({}, [("file.sources", "s.jar.sha512")], "file.sources"),
        ({}, [("upload", "a.jar")], "upload"),
        ({}, [("file.", "a.jar")], "file."),
        ({}, [("file.a.b", "a.jar")], "file.a.b"),
        ({}, [("file.so/urces", "a.jar")], "file.so/urces"),
        ({}, [("pom.extra", "a.pom")], "pom.extra"),
        ({}, [("file", "a.jar"), ("file", "b.jar")], "file"),
        ({}, [("file", "a.pom"), ("pom", "pom.xml")], "pom"),
        ({}, [("pom", "a.xml"), ("pom", "b.xml")], "pom"),
        ({}, [("file.x", "a.jar"), ("file.x", "b.jar")], "file.x"),
    ],
)
def test_a_form_that_does_not_say_what_to_store_is_refused_at_the_field(changes, files, field):
    fields = {name: value for name, value in {**APP, **changes}.items() if value is not None}

    with pytest.raises(InvalidUpload) as refused:
        upload.plan(fields, files)

    assert refused.value.field == field


def test_two_kinds_of_one_artifact_can_come_together():
    planned = upload.plan(APP, [("file", "a.jar"), ("file", "a.zip"), ("file.x", "a.zip")])

    assert len(set(planned.paths)) == 3

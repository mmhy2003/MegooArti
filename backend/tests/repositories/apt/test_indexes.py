import gzip
import hashlib
import lzma
from datetime import UTC, datetime

from megooarti.repositories.apt import control, indexes
from megooarti.repositories.apt.indexes import Listed
from tests.repositories.apt.packages import DATA

MOMENT = datetime(2026, 10, 14, 9, 30, 5, tzinfo=UTC)


def scanned_listing() -> list[Listed]:
    """The packages dpkg-scanpackages listed, as the server would keep them."""
    text = (DATA / "Packages.scanned").read_text(encoding="utf-8")
    listed = []
    for part in filter(str.strip, text.split("\n\n")):
        paragraph = control.parse(part)
        value = {name.lower(): text for name, text in paragraph}
        kept = [
            (name, text)
            for name, text in paragraph
            if name.lower() not in ("filename", "size", "md5sum", "sha1", "sha256")
        ]
        listed.append(
            Listed(
                path=value["filename"],
                size=int(value["size"]),
                md5=value["md5sum"],
                sha1=value["sha1"],
                sha256=value["sha256"],
                control=kept,
                package=value["package"],
                version=value["version"],
                architecture=value["architecture"],
            )
        )
    return listed


def listed(package: str, version: str, architecture: str = "amd64") -> Listed:
    paragraph = [
        ("Package", package),
        ("Version", version),
        ("Architecture", architecture),
        ("Description", "x"),
    ]
    path = f"pool/main/{package[0]}/{package}/{package}_{version}_{architecture}.deb"
    return Listed(path, 1, "m", "s1", "s256", paragraph, package, version, architecture)


def test_packages_is_written_as_dpkg_scanpackages_writes_it_byte_for_byte():
    expected = (DATA / "Packages.scanned").read_bytes()

    assert indexes.packages(reversed(scanned_listing())) == expected


def test_packages_are_listed_by_name_then_by_version_as_dpkg_orders_them_then_architecture():
    given = [
        listed("b", "1.0"),
        listed("a", "1.0-1"),
        listed("a", "1.0~rc1"),
        listed("a", "1:0.1", "arm64"),
        listed("a", "1:0.1", "amd64"),
    ]

    text = indexes.packages(given).decode()

    order = [
        line.removeprefix("Filename: ") for line in text.splitlines() if line.startswith("Filename")
    ]
    assert [path.rpartition("/")[2] for path in order] == [
        "a_1.0~rc1_amd64.deb",
        "a_1.0-1_amd64.deb",
        "a_1:0.1_amd64.deb",
        "a_1:0.1_arm64.deb",
        "b_1.0_amd64.deb",
    ]


def test_a_package_for_all_architectures_is_in_every_architectures_index():
    files = indexes.packages_files([listed("a", "1.0", "all"), listed("b", "1.0", "arm64")])

    assert sorted(path for path in files if path.endswith("/Packages")) == [
        "main/binary-amd64/Packages",
        "main/binary-arm64/Packages",
    ]
    assert b"Package: a\n" in files["main/binary-arm64/Packages"]
    assert b"Package: a\n" in files["main/binary-amd64/Packages"]
    assert b"Package: b\n" not in files["main/binary-amd64/Packages"]


def test_a_repository_with_no_package_of_one_architecture_lists_the_two_most_common():
    for given in ([], [listed("a", "1.0", "all")]):
        files = indexes.packages_files(given)

        assert sorted(path for path in files if path.endswith("/Packages")) == [
            "main/binary-amd64/Packages",
            "main/binary-arm64/Packages",
        ]


def test_the_compressed_indexes_hold_the_same_text_and_are_the_same_every_time():
    files = indexes.packages_files(scanned_listing())
    again = indexes.packages_files(scanned_listing())

    text = files["main/binary-amd64/Packages"]
    assert gzip.decompress(files["main/binary-amd64/Packages.gz"]) == text
    assert lzma.decompress(files["main/binary-amd64/Packages.xz"]) == text
    assert files == again


def test_release_names_each_index_with_its_size_and_checksums():
    files = indexes.packages_files([listed("a", "1.0", "amd64")])

    text = indexes.release(
        label="apt-hosted",
        suite="stable",
        moment=MOMENT,
        architectures=["amd64"],
        files=files,
    ).decode()

    assert text.startswith(
        "Origin: MegooArti\nLabel: apt-hosted\nSuite: stable\nCodename: stable\n"
        "Date: Wed, 14 Oct 2026 09:30:05 UTC\nArchitectures: amd64\nComponents: main\n"
        "Acquire-By-Hash: no\nMD5Sum:\n"
    )
    packages = files["main/binary-amd64/Packages"]
    line = f" {hashlib.sha256(packages).hexdigest()} {len(packages):>16} main/binary-amd64/Packages"
    assert line in text.splitlines()
    assert text.count("main/binary-amd64/Packages") == 6  # three files, two checksums each


def test_a_date_is_written_in_english_and_in_utc_whatever_the_zone_it_is_given_in():
    from datetime import timedelta, timezone

    later = MOMENT.astimezone(timezone(timedelta(hours=3)))

    assert indexes.date(later) == "Wed, 14 Oct 2026 09:30:05 UTC"


def test_the_architectures_listed_are_the_two_most_common_and_those_of_the_packages():
    assert indexes.architectures(scanned_listing()) == ["amd64", "arm64"]
    assert indexes.architectures([listed("a", "1.0", "riscv64")]) == [
        "amd64",
        "arm64",
        "riscv64",
    ]

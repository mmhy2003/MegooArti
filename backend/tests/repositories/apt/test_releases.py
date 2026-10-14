from datetime import UTC, datetime

import pysequoia
import pytest

from megooarti.repositories.apt import releases
from megooarti.repositories.apt.releases import Entry
from tests.repositories.apt.packages import DATA

MOMENT = datetime(2026, 10, 14, 9, 30, 5, tzinfo=UTC)


def debians() -> bytes:
    """The text of Debian 13's `Release`, as its signature vouches for it."""
    keys = pysequoia.Cert.split_bytes((DATA / "debian-archive-keyring.asc").read_bytes())
    signed = (DATA / "debian-trixie-InRelease").read_bytes()
    return pysequoia.verify(bytes=signed, store=lambda _: keys).bytes


def test_debians_release_says_its_components_architectures_date_and_files():
    release = releases.parse(debians())

    assert release.components == ["main", "contrib", "non-free-firmware", "non-free"]
    assert "amd64" in release.architectures and "all" in release.architectures
    assert release.moment == datetime(2026, 9, 12, 7, 55, 41, tzinfo=UTC)
    entry = release.entries["main/binary-amd64/Packages.xz"]
    assert entry.size > 1_000_000 and len(entry.sha256) == 64
    assert release.text.endswith(b"\n")


def test_a_release_the_group_writes_is_read_back_as_it_was_written():
    entries = [
        ("main/binary-amd64/Packages", Entry(10, "a" * 64)),
        ("main/binary-amd64/Packages.gz", Entry(7, "b" * 64)),
    ]

    text = releases.compose(
        label="apt-public",
        suite="trixie",
        moment=MOMENT,
        components=["main", "contrib"],
        architectures=["amd64", "arm64"],
        entries=entries,
    )
    release = releases.parse(text)

    assert text.startswith(
        b"Origin: MegooArti\nLabel: apt-public\nSuite: trixie\nCodename: trixie\n"
        b"Date: Wed, 14 Oct 2026 09:30:05 UTC\nArchitectures: amd64 arm64\n"
        b"Components: main contrib\nAcquire-By-Hash: no\nSHA256:\n"
    )
    assert release.entries == dict(entries)
    assert (release.components, release.moment) == (["main", "contrib"], MOMENT)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (b"Origin: X\nSuite: a\n", "no SHA256 list"),
        (b"Suite: a\nSHA256:\n not a line\n", "cannot be read"),
        (b"\xff\xfe", "not a Release file"),
        (b"Suite: a\n\nSuite: b\n", "not a Release file"),
    ],
)
def test_a_release_that_cannot_be_read_is_refused(text, said):
    with pytest.raises(releases.InvalidRelease, match=said):
        releases.parse(text)


def test_a_date_that_cannot_be_read_is_no_date():
    release = releases.parse(b"Date: tomorrow\nSHA256:\n")

    assert release.moment is None

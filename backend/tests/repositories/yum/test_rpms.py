"""Reading an RPM's headers, as it arrives, and refusing what is not one dnf installs."""

import struct

import pytest

from megooarti.repositories.yum import rpms
from megooarti.repositories.yum.rpms import Changelog, Entry
from tests.repositories.yum.packages import (
    DATA,
    HELLO,
    INT32,
    REAL,
    SOURCE,
    STRING,
    STRING_ARRAY,
    TOOL,
    header,
    lead,
    make_rpm,
    pieces,
)


async def read(data: bytes) -> rpms.Rpm:
    return await rpms.read(pieces(data))


async def test_a_package_rpmbuild_wrote_says_what_its_spec_said():
    rpm = await read((DATA / HELLO).read_bytes())

    assert (rpm.name, rpm.epoch, rpm.version, rpm.release, rpm.arch) == (
        "megooarti-hello",
        "0",
        "1.0",
        "1",
        "noarch",
    )
    assert rpm.summary == "Says hello"
    assert rpm.description.endswith("It prints one line: “hello”.")
    assert (rpm.license, rpm.url, rpm.group) == (
        "MIT",
        "https://example.com/megooarti-hello",
        "Unspecified",
    )
    assert rpm.sourcerpm == "megooarti-hello-1.0-1.src.rpm"
    assert (rpm.installed_size, rpm.archive_size) == (67, 596)
    assert (rpm.header_start, rpm.header_end) == (4504, 7421)
    assert rpm.files == [
        ("/etc/megooarti", "dir"),
        ("/etc/megooarti/hello.conf", ""),
        ("/usr/bin/megooarti-hello", ""),
        ("/var/log/megooarti-hello.log", "ghost"),
    ]
    assert rpm.evr == "1.0-1"


async def test_what_a_package_requires_is_listed_as_createrepo_c_lists_it():
    """Not rpm's own features, nor what it provides itself; `pre` for what comes first."""
    rpm = await read((DATA / HELLO).read_bytes())

    assert rpm.dependencies["requires"] == [
        Entry("/usr/bin/sh"),
        Entry("bash"),
        Entry("coreutils", pre=True),  # Requires(pre)
        Entry("findutils", pre=True),  # Requires(posttrans)
        Entry("gawk"),  # Requires(postun)
        Entry("grep", pre=True),  # Requires(post)
        Entry("sed"),  # Requires(preun)
    ]
    assert rpm.dependencies["provides"] == [
        Entry("config(megooarti-hello)", "EQ", "0", "1.0", "1"),
        Entry("hello-tool", "EQ", "0", "1.0"),
        Entry("megooarti-hello", "EQ", "0", "1.0", "1"),
    ]


async def test_every_kind_of_dependency_is_read_with_its_epoch():
    rpm = await read((DATA / TOOL).read_bytes())

    assert (rpm.epoch, rpm.evr) == ("2", "2:0.3-2")
    assert list(rpm.dependencies) == [
        "provides",
        "requires",
        "conflicts",
        "obsoletes",
        "suggests",
        "enhances",
        "recommends",
        "supplements",
    ]
    assert rpm.dependencies["requires"] == [Entry("megooarti-hello", "GE", "0", "1.0")]
    assert rpm.dependencies["conflicts"] == [Entry("megooarti-old", "LT", "0", "1")]
    assert rpm.dependencies["obsoletes"] == [Entry("megooarti-older", "LE", "0", "0.9")]
    assert rpm.dependencies["recommends"] == [Entry("less")]


async def test_the_ten_newest_changelog_entries_are_kept_oldest_first():
    """Of two at the same moment, the newer is moved a second on, as createrepo_c does."""
    rpm = await read((DATA / TOOL).read_bytes())

    assert [entry.author for entry in rpm.changelogs] == [
        f"Tool Maker <maker@example.com> - 2:0.3-{n}" for n in range(3, 13)
    ]
    assert [entry.date for entry in rpm.changelogs][-2:] == [1791806400, 1791806401]
    assert rpm.changelogs[0].text == "- Change 3 & more <here>."


async def test_a_run_of_entries_at_one_moment_is_spread_over_as_many_seconds():
    rpm = await read(
        make_rpm(changelog=[(500, "C - 3", "c"), (500, "B - 2", "b"), (500, "A - 1", "a")])
    )

    assert rpm.changelogs == [
        Changelog("A - 1", 500, "a"),
        Changelog("B - 2", 501, "b"),
        Changelog("C - 3", 502, "c"),
    ]


async def test_of_libc_only_the_highest_version_is_required_and_last():
    rpm = await read(
        make_rpm(
            requires=[
                ("libc.so.6()(64bit)", 16384, ""),
                ("libc.so.6(GLIBC_2.38)(64bit)", 16384, ""),
                ("bash", 0, ""),
                ("libc.so.6(GLIBC_2.4)(64bit)", 16384, ""),
                ("bash", 0, ""),  # twice: once is enough
                ("rpmlib(PayloadIsZstd)", 16777224, "5.4.18-1"),
                ("/usr/bin/megooarti-hello", 0, ""),  # its own file, which primary.xml lists
                ("/usr/share/other", 0, ""),
            ]
        )
    )

    assert [entry.name for entry in rpm.dependencies["requires"]] == [
        "bash",
        "/usr/share/other",
        "libc.so.6(GLIBC_2.38)(64bit)",
    ]


@pytest.mark.parametrize("name", sorted(REAL))
async def test_fedoras_own_packages_are_read_from_their_headers_alone(name):
    rpm = await read((DATA / f"{name}.header").read_bytes())

    assert f"{rpm.name}-{rpm.version}-{rpm.release}.{rpm.arch}.rpm" == name
    assert rpm.changelogs and len(rpm.changelogs) <= 10


async def test_what_is_kept_of_a_package_reads_back_as_it_was():
    rpm = await read((DATA / TOOL).read_bytes())

    assert rpms.Rpm.from_json(rpm.as_json()) == rpm


async def test_text_that_is_not_utf_8_is_read_as_latin_1():
    rpm = await read(make_rpm(extra={1015: (STRING, "Jos\xe9".encode("latin-1"))}))

    assert rpm.packager == "José"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"PK\x03\x04 a zip file" + b"\0" * 100, "not an RPM"),
        ((DATA / SOURCE).read_bytes(), "source RPM"),
        (make_rpm(source=True), "source RPM"),
        (lead("x") + b"\0" * 32, "no RPM header"),
        (make_rpm()[:200], "ends early"),
        (make_rpm(name="-rf"), "name"),
        (make_rpm(arch=""), "no name, version, release or architecture"),
    ],
)
async def test_what_is_not_an_rpm_dnf_installs_is_refused(data, reason):
    with pytest.raises(rpms.InvalidPackage, match=reason):
        await read(data)


async def test_headers_larger_than_the_bound_are_refused_before_they_are_read():
    said = struct.pack(">II", 1, rpms.HEADER_MOST)  # one tag, and 64 MiB of values
    data = lead("x") + b"\x8e\xad\xe8\x01\0\0\0\0" + said
    taken = []

    async def counted():
        async for piece in pieces(data + b"\0" * 1_000_000):
            taken.append(len(piece))
            yield piece

    with pytest.raises(rpms.InvalidPackage, match="larger than 64 MiB"):
        await rpms.read(counted())
    assert sum(taken) < 2000


async def test_a_header_that_points_outside_itself_is_refused():
    broken = header({1000: (STRING, "x")})
    broken = broken[:24] + struct.pack(">I", 1 << 20) + broken[28:]  # the name's offset
    signature = header({1007: (INT32, [1])})
    signature += b"\0" * (-len(signature) % 8)

    with pytest.raises(rpms.InvalidPackage, match="outside"):
        await read(lead("x") + signature + broken)


async def test_a_list_of_files_that_does_not_hold_together_is_refused():
    data = make_rpm(extra={1116: (INT32, [0, 0])})  # two indexes for one file

    with pytest.raises(rpms.InvalidPackage, match="list of files"):
        await read(data)


async def test_only_the_headers_are_read():
    data = make_rpm(payload=b"\0" * 100_000)
    taken = []

    async def counted():
        async for piece in pieces(data):
            taken.append(len(piece))
            yield piece

    await rpms.read(counted())

    assert sum(taken) < 2000


async def test_dependencies_may_have_no_versions_at_all():
    data = make_rpm(requires=[], extra={1049: (STRING_ARRAY, ["a", "b"])})

    rpm = await read(data)

    assert rpm.dependencies["requires"] == [Entry("a"), Entry("b")]


def pointed(data: bytes, tag: int, at: int) -> bytes:
    """A header in which one tag's values are said to be where another's are."""
    count = struct.unpack(">I", data[8:12])[0]
    entries = {}
    for number in range(count):
        place = 16 + 16 * number
        entries[struct.unpack(">I", data[place : place + 4])[0]] = place
    offset = data[entries[at] + 8 : entries[at] + 12]
    place = entries[tag] + 8
    return data[:place] + offset + data[place + 4 :]


async def test_a_header_whose_values_overlap_is_refused_before_they_are_read():
    """Seven lists of names over the same bytes would be seven times as many entries."""
    main = header(
        {
            1000: (STRING, "x"),
            1001: (STRING, "1"),
            1002: (STRING, "1"),
            1022: (STRING, "noarch"),
            1047: (STRING_ARRAY, ["a", "b", "c"]),
            1054: (STRING_ARRAY, ["d", "e", "f"]),
        }
    )
    signature = header({1007: (INT32, [1])})
    signature += b"\0" * (-len(signature) % 8)

    with pytest.raises(rpms.InvalidPackage, match="overlap"):
        await read(lead("x") + signature + pointed(main, 1054, 1047))


async def test_a_package_with_more_files_and_dependencies_than_the_bound_is_refused(monkeypatch):
    monkeypatch.setattr(rpms, "ENTRIES_MOST", 3)

    with pytest.raises(rpms.InvalidPackage, match="more than 3 files and dependencies"):
        await read(make_rpm(files=["/a", "/b"], requires=[("c", 0, ""), ("d", 0, "")]))
    await read(make_rpm(files=["/a"], requires=[("c", 0, "")]))  # one provide, three in all

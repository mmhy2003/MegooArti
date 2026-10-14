"""A `repodata/`, written byte for byte as createrepo_c writes it of the same packages."""

import gzip
import hashlib
from xml.etree import ElementTree

import pytest

from megooarti.repositories.yum import repodata, rpms
from tests.repositories.yum.packages import DATA, HELLO, REAL, STORED_AT, TOOL, pieces

KINDS = {"primary": repodata.primary, "filelists": repodata.filelists, "other": repodata.other}
REPO = "{http://linux.duke.edu/metadata/repo}"


async def listed_from(name: str, data: bytes, size: int, sha256: str, time: int):
    return repodata.Listed(name, size, sha256, time, await rpms.read(pieces(data)))


async def ours() -> list[repodata.Listed]:
    """The two packages rpmbuild wrote, as the server lists them."""
    listed = []
    for name in (HELLO, TOOL):
        data = (DATA / name).read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        listed.append(await listed_from(name, data, len(data), sha256, STORED_AT))
    return listed


async def fedoras() -> list[repodata.Listed]:
    """Two of Fedora's, from their headers, with what the whole files are."""
    return [
        await listed_from(name, (DATA / f"{name}.header").read_bytes(), size, sha256, time)
        for name, (size, sha256, time) in REAL.items()
    ]


@pytest.mark.parametrize("kind", sorted(KINDS))
async def test_the_metadata_of_our_packages_is_what_createrepo_c_wrote(kind):
    expected = (DATA / f"createrepo-{kind}.xml").read_bytes()

    assert KINDS[kind](await ours()) == expected


@pytest.mark.parametrize("kind", sorted(KINDS))
async def test_the_metadata_of_fedoras_packages_is_what_createrepo_c_wrote(kind):
    expected = (DATA / f"real-createrepo-{kind}.xml").read_bytes()

    assert KINDS[kind](await fedoras()) == expected


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_metadata_of_nothing_is_what_createrepo_c_wrote(kind):
    assert KINDS[kind]([]) == (DATA / f"empty-createrepo-{kind}.xml").read_bytes()


async def test_repomd_names_each_file_by_its_hash_as_createrepo_c_does():
    written = repodata.repodata(await ours(), 1792005637)

    mine = ElementTree.fromstring(written["repomd.xml"])
    theirs = ElementTree.fromstring((DATA / "createrepo-repomd.xml").read_bytes())
    assert [child.tag for child in mine] == [child.tag for child in theirs]
    assert mine.findtext(f"{REPO}revision") == "1792005637"
    named = {"repomd.xml"}
    for data in mine.iter(f"{REPO}data"):
        kind = data.get("type")
        location = data.find(f"{REPO}location").get("href")
        named.add(location.removeprefix("repodata/"))
        packed = written[location.removeprefix("repodata/")]
        opened = gzip.decompress(packed)
        checksum = data.findtext(f"{REPO}checksum")
        assert location == f"repodata/{checksum}-{kind}.xml.gz"
        assert checksum == hashlib.sha256(packed).hexdigest()
        assert data.findtext(f"{REPO}open-checksum") == hashlib.sha256(opened).hexdigest()
        assert (data.findtext(f"{REPO}size"), data.findtext(f"{REPO}open-size")) == (
            str(len(packed)),
            str(len(opened)),
        )
        assert data.findtext(f"{REPO}timestamp") == "1792005637"
        assert opened == (DATA / f"createrepo-{kind}.xml").read_bytes()
    assert set(written) == named


async def test_the_same_packages_make_the_same_bytes():
    assert repodata.repodata(await ours(), 1) == repodata.repodata(await ours(), 1)


@pytest.mark.parametrize(
    ("value", "text", "attribute"),
    [
        ("a & b < c > d", "a &amp; b &lt; c &gt; d", "a &amp; b &lt; c &gt; d"),
        ('say "hi"', 'say "hi"', "say &quot;hi&quot;"),
        ("one\ntwo\tthree\rfour", "one\ntwo\tthree&#13;four", "one&#10;two&#9;three&#13;four"),
        ("Jędrzejewski “x”", "Jędrzejewski “x”", "J&#x119;drzejewski &#x201C;x&#x201D;"),
        ("bell\x07 and nul\x00", "bell and nul", "bell and nul"),
    ],
)
def test_text_is_escaped_as_libxml2_escapes_it(value, text, attribute):
    assert repodata.text(value) == text
    assert repodata.attribute(value) == attribute

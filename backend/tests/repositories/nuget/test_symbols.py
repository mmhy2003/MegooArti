"""What a symbol server keeps of a portable PDB: its key, as dotnet-symbol asks for it,
and its checksum, as it names it."""

import hashlib
import uuid

import pytest

from megooarti.repositories.nuget import symbols
from megooarti.repositories.nuget.packages import InvalidPackage
from tests.repositories.nuget.packages import GUID, portable_pdb

KEPT_PATH = "symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.pdb"


def test_a_portable_pdb_is_kept_at_its_key_with_its_checksum():
    data = portable_pdb(stamp=7)

    pdb = symbols.read("lib/net8.0/Hello.pdb", data)

    # As dotnet-symbol asks for Serilog's: the GUID as 32 hex digits, then FFFFFFFF.
    assert pdb.path == "symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.pdb"
    at = data.index(GUID.bytes_le)
    zeroed = data[:at] + b"\0" * 20 + data[at + 20 :]
    assert pdb.checksum == hashlib.sha256(zeroed).hexdigest()
    # The stamp is part of what is zeroed, not of the key.
    assert symbols.read("Hello.pdb", portable_pdb(stamp=8)).path == pdb.path


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0", "is a Windows PDB"),
        (b"MZ\x90\0", "is not a portable PDB"),
        (b"BSJB\x01\0", "metadata that cannot be read"),
        (portable_pdb().replace(b"#Pdb", b"#Str"), "has no PDB id"),
    ],
    ids=["windows", "other", "cut-short", "no-id"],
)
def test_what_is_not_a_portable_pdb_is_refused_by_name(data, said):
    with pytest.raises(InvalidPackage, match=said):
        symbols.read("Hello.pdb", data)


@pytest.mark.parametrize(
    ("path", "served"),
    [
        ("symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.pdb", True),
        # Matched without regard to case, as symbol servers match keys.
        ("symbols/Hello.pdb/201D67AFC77A4CD5A6668A65B7B7382DFFFFFFFF/Hello.pdb", True),
        ("symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382d00000001/hello.pdb", False),
        ("symbols/hello.pdb/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/other.pdb", False),
        ("symbols/hello.dll/201d67afc77a4cd5a6668a65b7b7382dFFFFFFFF/hello.dll", False),
    ],
    ids=["key", "capitals", "windows-key", "names", "not-a-pdb"],
)
def test_a_symbol_path_is_a_portable_pdbs_key(path, served):
    assert symbols.is_path(path) is served


def test_the_checksums_a_debugger_names_are_read():
    checksum = "AF671D20" + "0" * 56

    assert symbols.asked(None) is None
    assert symbols.asked(f"SHA256:{checksum}") == {checksum.lower()}
    assert symbols.asked(f"SHA1:{'0' * 40};SHA256:{checksum}") == {checksum.lower()}
    assert symbols.asked("nonsense") == set()


def test_another_guid_is_another_key():
    other = uuid.UUID("00000000-0000-0000-0000-000000000001")

    assert (
        "00000000000000000000000000000001FFFFFFFF"
        in symbols.read("Hello.pdb", portable_pdb(guid=other)).path
    )


def test_a_key_in_another_case_is_the_key():
    upper = KEPT_PATH.replace("hello.pdb", "Hello.pdb").replace("201d67af", "201D67AF")

    assert symbols.normalized(upper) == KEPT_PATH
    assert symbols.normalized(KEPT_PATH.replace("FFFFFFFF", "ffffffff")) == KEPT_PATH
    assert symbols.normalized("symbols/a.pdb/xyz/a.pdb") is None

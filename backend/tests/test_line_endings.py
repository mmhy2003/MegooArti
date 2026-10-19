"""Files a container reads as text keep LF line endings on every checkout: a CR at a
line's end would be part of every value (an LDIF's passwords among them)."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", ["backend/tests/openldap/corp.ldif"])
def test_a_file_a_container_reads_is_checked_out_with_lf(path):
    said = subprocess.run(
        ["git", "check-attr", "eol", "--", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert said.strip().endswith(": eol: lf"), said

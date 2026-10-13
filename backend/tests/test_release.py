"""What a release says of itself: its licence and its version, the same everywhere."""

import json
import re
import tomllib
from pathlib import Path

import pytest

from megooarti import __version__
from megooarti.api_docs import ASSETS

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]
PACKAGE = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))


def test_the_licence_is_mit_and_both_packages_say_so():
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert licence.startswith("MIT License\n")
    assert "Permission is hereby granted, free of charge" in licence
    assert re.search(r"^Copyright \(c\) \d{4} .+$", licence, flags=re.MULTILINE)
    assert PROJECT["license"] == "MIT"
    assert PACKAGE["license"] == "MIT"


@pytest.mark.parametrize("image", ["backend", "frontend"])
def test_each_image_is_labelled_with_what_it_is(image):
    dockerfile = (ROOT / image / "Dockerfile").read_text(encoding="utf-8")
    labels = dict(re.findall(r'org\.opencontainers\.image\.(\w+)="([^"]*)"', dockerfile))

    assert labels["licenses"] == "MIT"
    assert labels["title"] == f"MegooArti {image}"
    # Whatever tag the image is built under: Compose says which (test_compose.py).
    assert labels["version"] == "${VERSION}"
    assert labels["source"].startswith("https://")
    # After everything else, so that a new version builds no other layer again.
    assert dockerfile.rstrip().endswith(f'source="{labels["source"]}"')


def test_what_is_not_ours_keeps_its_own_licence():
    assert "Apache License" in (ASSETS / "LICENSE").read_text(encoding="utf-8")


def test_one_version_is_said_everywhere():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert PROJECT["version"] == PACKAGE["version"] == __version__
    assert f"#MEGOOARTI_VERSION={__version__}\n" in example

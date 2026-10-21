"""A cleanup policy's criteria (spec 4.2): what each selects, all of them together (E2),
and what cannot be a policy, said at its field."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from megooarti.cleanup.criteria import Criteria, Held, problems
from megooarti.repositories.formats import format_names, get_format

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def held(
    version: str = "1.0.0",
    *,
    modified_days: int = 0,
    downloaded_days: int = 0,
    paths: tuple[str, ...] = ("pkg/a-1.0.0.tgz",),
) -> Held:
    return Held(
        uuid.uuid4(),
        "",
        "a",
        version,
        NOW - timedelta(days=modified_days),
        NOW - timedelta(days=downloaded_days),
        paths,
    )


@pytest.mark.parametrize(
    ("criteria", "component", "selected"),
    [
        (Criteria(updated_days=30), held(modified_days=31), True),
        (Criteria(updated_days=30), held(modified_days=30), False),  # exactly 30 days: kept
        (Criteria(downloaded_days=7), held(downloaded_days=8), True),
        (Criteria(downloaded_days=7), held(downloaded_days=6), False),
        (Criteria(release_type="prerelease"), held("1.0.0-beta.1"), True),
        (Criteria(release_type="prerelease"), held("1.0.0"), False),
        (Criteria(release_type="release"), held("1.0.0"), True),
        (Criteria(release_type="release"), held("1.0.0-beta.1"), False),
        (Criteria(asset_pattern=r"/pkg/.*\.tgz"), held(), True),
        (Criteria(asset_pattern=r"pkg/.*\.tgz"), held(), False),  # the path has its `/`
        (Criteria(asset_pattern=r"/pkg/a"), held(), False),  # the whole path
        (
            Criteria(updated_days=30, release_type="prerelease"),
            held("1.0.0", modified_days=90),
            False,
        ),
    ],
)
def test_a_component_is_selected_when_every_criterion_is_met(criteria, component, selected):
    assert criteria.selects(component, NOW, get_format("npm")) is selected


def test_one_file_matching_the_pattern_is_enough():
    component = held(paths=("pkg/a-1.0.0.tgz", "pkg/a-1.0.0.tgz.sig"))

    assert Criteria(asset_pattern=r".*\.sig").selects(component, NOW, get_format("npm"))


def test_the_newest_file_decides():
    assert Criteria(updated_days=30, downloaded_days=7).cutoffs(NOW) == (
        NOW - timedelta(days=30),
        NOW - timedelta(days=7),
    )
    assert Criteria(asset_pattern=".*").cutoffs(NOW) == (None, None)


@pytest.mark.parametrize(
    ("format", "version", "pre"),
    [
        ("maven", "1.0-SNAPSHOT", True),
        ("maven", "1.0", False),
        ("npm", "2.0.0-rc.1", True),
        ("pypi", "1.0rc1", True),
        ("nuget", "1.0.0-preview", True),
        ("apk", "1.0_rc1-r0", True),
    ],
)
def test_release_type_is_each_formats_own(format, version, pre):
    criteria = Criteria(release_type="prerelease")

    assert criteria.selects(held(version), NOW, get_format(format)) is pre


@pytest.mark.parametrize(
    ("format", "criteria", "field"),
    [
        ("npm", Criteria(), "criteria"),  # none at all
        ("npm", Criteria(updated_days=0), "updated_days"),
        ("npm", Criteria(downloaded_days=36501), "downloaded_days"),
        ("raw", Criteria(release_type="prerelease"), "release_type"),
        ("docker", Criteria(release_type="release"), "release_type"),
        ("*", Criteria(release_type="release"), "release_type"),
        ("npm", Criteria(asset_pattern="("), "asset_pattern"),
        ("npm", Criteria(asset_pattern="(a+)+"), "asset_pattern"),
        ("npm", Criteria(asset_pattern="a" * 1001), "asset_pattern"),
        ("nothing", Criteria(updated_days=1), "format"),
    ],
)
def test_what_cannot_be_a_policy_is_said_at_its_field(format, criteria, field):
    assert [problem["field"] for problem in problems(format, criteria)] == [field]


def test_a_good_policy_has_no_problem():
    assert problems("maven", Criteria(updated_days=14, release_type="prerelease")) == []
    assert problems("*", Criteria(downloaded_days=90, asset_pattern=r"/.*\.tmp")) == []


def test_formats_say_whether_they_have_prereleases():
    having = {name for name in format_names() if get_format(name).has_prereleases}

    assert having == {"maven", "npm", "pypi", "nuget", "apt", "yum", "apk"}

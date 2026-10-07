import pytest

from megooarti.security.permissions import (
    FULL_ACCESS,
    any_grants,
    grants,
    is_valid_pattern,
    is_valid_permission,
)


@pytest.mark.parametrize(
    ("pattern", "permission", "expected"),
    [
        ("*", "admin:users:write", True),
        ("admin:users:*", "admin:users:write", True),
        ("admin:users:read", "admin:users:write", False),
        ("admin:users:write", "admin:users:write", True),
        ("repository:*:*:read", "repository:maven:releases:read", True),
        ("repository:*:*:read", "repository:maven:releases:delete", False),
        ("repository:maven", "repository:maven:releases:delete", True),
        ("repository:maven", "repository:npm:internal:read", False),
        ("admin", "admin:settings:write", True),
        ("repository:maven:releases:read:extra", "repository:maven:releases:read", False),
        ("admin:Users:read", "admin:users:read", False),
        ("*:users:read", "admin:users:read", True),
    ],
)
def test_grants(pattern, permission, expected):
    assert grants(pattern, permission) is expected


def test_any_grants_is_true_when_one_pattern_matches():
    assert any_grants(["admin:roles:read", "admin:users:*"], "admin:users:write")


def test_any_grants_is_false_for_no_patterns():
    assert not any_grants([], "admin:users:read")


def test_full_access_is_the_single_wildcard():
    assert FULL_ACCESS == "*"
    assert grants(FULL_ACCESS, "anything:at:all")


@pytest.mark.parametrize("pattern", ["*", "admin:users:*", "repository:maven:my.repo-1_x:read"])
def test_valid_patterns(pattern):
    assert is_valid_pattern(pattern)


@pytest.mark.parametrize(
    "pattern", ["", "admin::read", "admin:us ers", "admin:users:", "a:b*", "é"]
)
def test_invalid_patterns(pattern):
    assert not is_valid_pattern(pattern)


def test_a_permission_may_not_contain_a_wildcard():
    assert is_valid_permission("admin:users:read")
    assert not is_valid_permission("admin:*:read")

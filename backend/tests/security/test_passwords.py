import pytest
from argon2 import PasswordHasher

from megooarti.security import passwords
from megooarti.security.passwords import (
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)


def test_a_hash_verifies_its_own_password_only():
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "correct horse batterx")


def test_two_hashes_of_one_password_differ():
    assert hash_password("same password") != hash_password("same password")


def test_a_missing_hash_never_verifies():
    assert not verify_password(None, "anything")


def test_a_corrupt_hash_never_verifies():
    assert not verify_password("not-a-hash", "anything")


def test_non_ascii_passwords_work():
    hashed = hash_password("pässwörd-ünïcode-✓")
    assert verify_password(hashed, "pässwörd-ünïcode-✓")


def test_a_hash_made_with_other_parameters_needs_a_rehash(monkeypatch):
    old = hash_password("correct horse battery")
    assert not needs_rehash(old)

    stronger = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    monkeypatch.setattr(passwords, "_hasher", stronger)

    assert needs_rehash(old)
    assert verify_password(old, "correct horse battery")


@pytest.mark.parametrize(
    ("password", "username", "fragment"),
    [
        ("short", "dana", "at least 8"),
        ("x" * 257, "dana", "at most 256"),
        ("DanaSmith", "danasmith", "username"),
    ],
)
def test_password_rules(password, username, fragment):
    assert fragment in password_problem(password, username)


def test_an_acceptable_password_has_no_problem():
    assert password_problem("correct horse battery", "dana") is None

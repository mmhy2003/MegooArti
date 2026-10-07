import re

from megooarti.security.keys import TOKEN_PREFIX, hash_secret, new_api_token, new_secret


def test_secrets_are_long_random_and_url_safe():
    first, second = new_secret(), new_secret()
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)


def test_api_tokens_carry_the_prefix():
    token = new_api_token()
    assert token.startswith(TOKEN_PREFIX)
    assert len(token) == 47


def test_hash_is_stable_hex_and_differs_by_input():
    assert hash_secret("abc") == hash_secret("abc")
    assert hash_secret("abc") != hash_secret("abd")
    assert re.fullmatch(r"[0-9a-f]{64}", hash_secret("abc"))

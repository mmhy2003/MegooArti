import pytest

from megooarti.repositories.maven.checksums import read_uploaded

SHA1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
MD5 = "d41d8cd98f00b204e9800998ecf8427e"


@pytest.mark.parametrize(
    "body",
    [
        SHA1.encode(),
        SHA1.encode() + b"\n",
        SHA1.upper().encode(),
        f"{SHA1}  app-1.0.jar\n".encode(),
        f"{SHA1} *app-1.0.jar\r\n".encode(),
        f"SHA1(app-1.0.jar)= {SHA1}\n".encode(),
        f"SHA1 (my app.jar) = {SHA1}".encode(),
        f"\n\n  {SHA1}\r\n".encode(),
        b"\xef\xbb\xbf" + SHA1.encode(),
    ],
)
def test_the_ways_tools_write_a_checksum_are_all_read(body):
    assert read_uploaded(body, "sha1") == SHA1


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"   \n",
        b"not a checksum",
        SHA1[:-1].encode(),
        (SHA1 + "0").encode(),
        ("z" * 40).encode(),
        ("٣" * 40).encode(),
        b"\xff\xfe\x00",
    ],
)
def test_anything_else_is_not_a_checksum(body):
    assert read_uploaded(body, "sha1") is None


def test_the_length_must_fit_the_algorithm():
    assert read_uploaded(MD5.encode(), "md5") == MD5
    assert read_uploaded(MD5.encode(), "sha1") is None
    assert read_uploaded(b"a" * 64, "sha256") == "a" * 64
    assert read_uploaded(b"a" * 128, "sha512") == "a" * 128
    assert read_uploaded(b"a" * 64, "sha512") is None

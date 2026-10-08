import hashlib

import pytest

from megooarti.repositories.pypi import upload
from megooarti.repositories.pypi.upload import Declared, Form, InvalidUpload
from tests.repositories.pypi.conftest import BOUNDARY, CONTENT_TYPE, WHEEL, form_body

DATA = b"PK\x03\x04 not really a wheel " + bytes(range(256)) * 4
FIELDS = {
    ":action": "file_upload",
    "protocol_version": "1",
    "name": "Megooarti_Greeter",
    "version": "1.0.0",
    "filetype": "bdist_wheel",
    "summary": "Says hello",
    "requires_python": ">=3.9",
    "sha256_digest": hashlib.sha256(DATA).hexdigest(),
    "md5_digest": hashlib.md5(DATA).hexdigest(),
    "blake2_256_digest": "0" * 64,
    "description": "# A long README\n" * 200,
}
KEPT = {key: FIELDS[key] for key in FIELDS if key not in ("protocol_version", "filetype")}
KEPT = {
    key: value for key, value in KEPT.items() if key not in ("blake2_256_digest", "description")
}


def read(body: bytes, cuts: list[int] | None = None, content_type: str = CONTENT_TYPE):
    """Feed a body in pieces. Returns the form and the file's bytes."""
    form = Form(content_type)
    edges = [0, *sorted(cuts or []), len(body)]
    pieces = []
    for start, end in zip(edges, edges[1:], strict=False):
        pieces.extend(form.feed(body[start:end]))
    form.finish()
    return form, b"".join(pieces)


def test_a_form_gives_its_file_and_the_fields_that_are_used():
    form, data = read(form_body(FIELDS, (WHEEL, DATA)))

    assert data == DATA
    assert form.fields == KEPT
    assert (form.filename, form.files) == (WHEEL, 1)


def test_the_result_is_the_same_wherever_the_form_is_cut():
    body = form_body(FIELDS, (WHEEL, DATA))
    whole, data = read(body)

    for cut in range(len(body) + 1):
        form, pieces = read(body, [cut])
        assert (pieces, form.fields, form.filename) == (data, whole.fields, WHEEL), cut


def test_the_result_is_the_same_one_byte_at_a_time():
    body = form_body({**FIELDS, "description": "short"}, (WHEEL, DATA[:300]))

    form, data = read(body, list(range(1, len(body))))

    assert (data, form.fields) == (DATA[:300], KEPT)


def test_the_file_may_come_before_the_fields():
    body = form_body(FIELDS, (WHEEL, DATA), file_first=True)

    form, data = read(body)

    assert (data, form.fields, form.filename) == (DATA, KEPT, WHEEL)


def test_a_file_that_contains_the_boundary_text_is_not_cut_there():
    tricky = b"line one\r\n--" + BOUNDARY.encode()[:-1] + b"X\r\nline two\r\n"

    _, data = read(form_body(FIELDS, (WHEEL, tricky)))

    assert data == tricky


def test_a_field_that_is_not_used_can_be_any_length():
    huge = {**FIELDS, "description": "x" * (2 * 1024 * 1024)}

    form, data = read(form_body(huge, (WHEEL, DATA)))

    assert (data, form.fields) == (DATA, KEPT)


@pytest.mark.parametrize("name", ["name", "version", "summary", "requires_python", "sha256_digest"])
def test_a_field_that_is_used_has_a_limit(name):
    body = form_body({**FIELDS, name: "x" * (upload.FIELD_LIMIT + 1)}, (WHEEL, DATA))

    with pytest.raises(InvalidUpload, match=name):
        read(body)


def test_a_field_that_is_used_may_be_given_once():
    body = form_body(FIELDS, (WHEEL, DATA), extra=[("name", "another")])

    with pytest.raises(InvalidUpload, match="twice"):
        read(body)


def test_a_second_file_is_counted_and_not_read():
    body = form_body(FIELDS, (WHEEL, DATA), extra=[("content", ("other.whl", b"second"))])

    form, data = read(body)

    assert (data, form.files, form.filename) == (DATA, 2, WHEEL)


@pytest.mark.parametrize(
    "content_type",
    [
        "",
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "multipart/form-data; boundary=",
        "multipart/mixed; boundary=abc",
        "multipart/form-data; boundary=" + "b" * 500,
    ],
)
def test_what_is_not_a_multipart_form_is_refused_at_once(content_type):
    with pytest.raises(InvalidUpload):
        Form(content_type)


def test_a_form_cut_short_is_refused():
    body = form_body(FIELDS, (WHEEL, DATA))

    for length in (0, 10, len(body) // 2, len(body) - 3):
        with pytest.raises(InvalidUpload):
            read(body[:length])
    # The line break after the last boundary is not part of the form.
    assert read(body[:-2])[1] == DATA


@pytest.mark.parametrize("body", [b"not a form at all", b"\x00" * 100, b"--wrong-boundary\r\n\r\n"])
def test_a_body_that_is_not_the_form_it_says_is_refused(body):
    with pytest.raises(InvalidUpload):
        read(body)


def test_too_many_parts_are_refused(monkeypatch):
    monkeypatch.setattr(upload, "MAX_PARTS", 5)
    body = form_body(FIELDS, (WHEEL, DATA))

    with pytest.raises(InvalidUpload, match="parts"):
        read(body)


def test_a_field_that_is_not_text_is_refused():
    body = form_body({**FIELDS, "summary": b"\xff\xfe"}, (WHEEL, DATA))

    with pytest.raises(InvalidUpload, match="summary"):
        read(body)


def test_what_a_good_upload_declares():
    form, _ = read(form_body(FIELDS, (WHEEL, DATA)))

    assert upload.declared(form.fields, form.filename, form.files) == Declared(
        project="megooarti-greeter",
        name="Megooarti_Greeter",
        version="1.0.0",
        filename=WHEEL,
        file_version="1.0.0",
        summary="Says hello",
        requires_python=">=3.9",
        digests={"sha256": hashlib.sha256(DATA).hexdigest(), "md5": hashlib.md5(DATA).hexdigest()},
    )


def test_the_version_in_the_file_name_is_reported_beside_the_declared_one():
    fields = {":action": "file_upload", "name": "pkg", "version": "9"}

    sent = upload.declared(fields, "pkg-1.0.tar.gz", 1)

    assert (sent.version, sent.file_version) == ("9", "1.0")


def test_what_is_not_declared_is_left_out():
    fields = {":action": "file_upload", "name": "pkg", "version": "1.0", "summary": "  "}

    sent = upload.declared(fields, "pkg-1.0.tar.gz", 1)

    assert (sent.summary, sent.requires_python, sent.digests) == (None, None, {})


def test_digests_are_compared_in_lower_case():
    fields = {":action": "file_upload", "name": "pkg", "version": "1.0"}
    fields["sha256_digest"] = "ABCDEF" + "0" * 58

    assert upload.declared(fields, "pkg-1.0.zip", 1).digests == {"sha256": "abcdef" + "0" * 58}


GOOD = {":action": "file_upload", "name": "pkg", "version": "1.0"}


@pytest.mark.parametrize(
    ("fields", "filename", "files", "reason"),
    [
        ({**GOOD, ":action": "submit"}, "pkg-1.0.tar.gz", 1, "action"),
        ({"name": "pkg", "version": "1.0"}, "pkg-1.0.tar.gz", 1, "action"),
        (GOOD, None, 0, "one file"),
        (GOOD, "pkg-1.0.tar.gz", 2, "one file"),
        (GOOD, "", 1, "one file"),
        ({**GOOD, "name": "-pkg"}, "pkg-1.0.tar.gz", 1, "project name"),
        ({**GOOD, "name": ""}, "pkg-1.0.tar.gz", 1, "project name"),
        ({**GOOD, "version": "1.0/../.."}, "pkg-1.0.tar.gz", 1, "version"),
        ({**GOOD, "version": ".."}, "pkg-1.0.tar.gz", 1, "version"),
        ({**GOOD, "version": ""}, "pkg-1.0.tar.gz", 1, "version"),
        (GOOD, "pkg-1.0.exe", 1, "wheel or a source"),
        (GOOD, "pkg-1.0.tar.bz2", 1, "wheel or a source"),
        (GOOD, "../pkg-1.0.tar.gz", 1, "wheel or a source"),
        (GOOD, "pkg 1.0.tar.gz", 1, "wheel or a source"),
        (GOOD, "other-1.0.tar.gz", 1, "does not fit"),
        (GOOD, "pkg-1.0-py3-none.whl", 1, "does not fit"),
        ({**GOOD, "sha256_digest": "abc"}, "pkg-1.0.tar.gz", 1, "sha256_digest"),
        ({**GOOD, "md5_digest": "z" * 32}, "pkg-1.0.tar.gz", 1, "md5_digest"),
        ({**GOOD, "requires_python": ">=3.9\n<4"}, "pkg-1.0.tar.gz", 1, "requires_python"),
        ({**GOOD, "summary": "a\x00b"}, "pkg-1.0.tar.gz", 1, "summary"),
    ],
)
def test_what_a_bad_upload_is_refused_for(fields, filename, files, reason):
    with pytest.raises(InvalidUpload, match=reason):
        upload.declared(fields, filename, files)

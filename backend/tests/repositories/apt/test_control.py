import pytest

from megooarti.repositories.apt import control

TEXT = """Package: megooarti-hello
Version: 1.0-1
Depends: libc6 (>= 2.17)
Description: Says hello
 A package made for the tests.
 .
 It prints one line.
"""


def test_a_paragraph_is_read_field_by_field_and_written_back_as_it_was():
    paragraph = control.parse(TEXT)

    assert [name for name, _ in paragraph] == ["Package", "Version", "Depends", "Description"]
    assert control.get(paragraph, "description") == (
        "Says hello\n A package made for the tests.\n .\n It prints one line."
    )
    assert control.format_paragraph(paragraph) == TEXT


def test_a_value_that_begins_on_the_next_line_is_written_so():
    paragraph = control.parse("Package: a\nConffiles:\n /etc/a abc\n")

    assert control.get(paragraph, "Conffiles") == "\n /etc/a abc"
    assert control.format_paragraph(paragraph) == "Package: a\nConffiles:\n /etc/a abc\n"


def test_comments_blank_lines_around_and_trailing_spaces_go():
    paragraph = control.parse("# made by hand\n\nPackage:  a  \nVersion: 1\t\n\n\n")

    assert paragraph == [("Package", "a"), ("Version", "1")]


def test_a_field_is_found_whatever_the_case_of_its_name():
    assert control.get(control.parse("package: a\n"), "Package") == "a"
    assert control.get(control.parse("Package: a\n"), "Version") is None


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("", "it has no fields"),
        ("Package: a\n\nPackage: b\n", "more than one paragraph"),
        (" continued\nPackage: a\n", "begins with a continuation line"),
        ("Package: a\nPackage: b\n", "given twice"),
        ("Package: a\npackage: b\n", "given twice"),
        ("Package: a\r\n", "carriage return"),
        ("Package a\n", "is not a field"),
        ("-----BEGIN PGP SIGNED MESSAGE-----\n", "is not a field"),
        ("Pack age: a\n", "is not a field"),
    ],
)
def test_text_that_is_not_one_paragraph_is_refused(text, said):
    with pytest.raises(control.InvalidControl, match=said):
        control.parse(text)


def test_a_continuation_line_cannot_begin_a_field_of_its_own():
    paragraph = control.parse("Package: a\nDescription: x\n Filename: ../../etc/passwd\n")

    assert control.get(paragraph, "Filename") is None
    assert control.format_paragraph(paragraph).count("\nFilename") == 0

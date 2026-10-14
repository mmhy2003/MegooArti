import pytest

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.formats import ComponentKey, Format, format_names, get_format, register
from megooarti.repositories.raw import RawFormat


def test_raw_is_registered():
    assert isinstance(get_format("raw"), RawFormat)
    assert "raw" in format_names()
    assert get_format("no-such-format") is None


def test_raw_supports_every_repository_type():
    assert get_format("raw").types == {"hosted", "proxy", "group"}


def test_a_format_without_settings_accepts_only_an_empty_object():
    raw = get_format("raw")

    assert raw.validate_config("hosted", {}) == {}
    with pytest.raises(ApiError) as caught:
        raw.validate_config("hosted", {"anything": 1})
    assert caught.value.code == "validation_error"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/guide/intro.txt", ComponentKey("docs/guide", "intro.txt")),
        ("top.txt", ComponentKey("", "top.txt")),
    ],
)
def test_the_generic_component_is_the_file_in_its_directory(path, expected):
    assert get_format("raw").describe_component(path) == expected


def test_a_format_must_have_a_name_to_be_registered():
    with pytest.raises(ValueError):
        register(Format())


@pytest.mark.parametrize(
    ("base", "path", "expected"),
    [
        ("https://remote.example/files", "a/b.bin", "https://remote.example/files/a/b.bin"),
        ("https://remote.example/files/", "a.bin", "https://remote.example/files/a.bin"),
        (
            "https://remote.example",
            "with space/ünï?.bin",
            "https://remote.example/with%20space/%C3%BCn%C3%AF%3F.bin",
        ),
    ],
)
def test_the_generic_remote_url_is_the_base_plus_the_encoded_path(base, path, expected):
    assert get_format("raw").remote_url(base, path) == expected


def test_the_generic_format_has_no_metadata_paths():
    assert get_format("raw").is_metadata("anything/at/all.xml") is False


def test_the_generic_content_type_is_whatever_the_client_declared():
    raw = get_format("raw")

    assert raw.content_type("a/b.bin", "application/x-thing") == "application/x-thing"
    assert raw.content_type("a/b.bin", None) is None


def test_settings_validation_is_given_the_stored_settings():
    assert get_format("raw").validate_config("hosted", {}, {}) == {}


class Choosy(RawFormat):
    """Raw, as a format whose groups take no proxy."""

    def validate_member(self, member):
        if member.type == "proxy":
            raise ApiError(
                422,
                "validation_error",
                "The request is not valid.",
                [{"field": "group.members", "message": f"{member.name} is a proxy."}],
            )


async def test_a_format_may_refuse_a_repository_as_a_member_of_its_groups(db, monkeypatch):
    for name, type, settings in (
        ("files", "hosted", {}),
        ("mirror", "proxy", {"proxy": {"remote_url": "http://remote.test/files"}}),
    ):
        await service.create_repository(
            db, name=name, format="raw", type=type, online=True, blob_store=None, **settings
        )
    monkeypatch.setattr(service, "get_format", lambda name: Choosy())

    taken = await service.create_repository(
        db,
        name="ours",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    with pytest.raises(ApiError) as refused:
        await service.create_repository(
            db,
            name="everything",
            format="raw",
            type="group",
            online=True,
            blob_store=None,
            group={"members": ["files", "mirror"]},
        )

    assert taken.name == "ours"
    assert refused.value.details == [{"field": "group.members", "message": "mirror is a proxy."}]


def test_the_generic_format_takes_any_member():
    from megooarti.repositories.models import Repository

    assert get_format("raw").validate_member(Repository(name="mirror", type="proxy")) is None

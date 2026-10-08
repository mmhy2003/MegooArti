import base64
import hashlib
from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest

from megooarti import __version__
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import remote
from megooarti.secrets_box import SecretUnreadable, seal
from megooarti.storage.backends import FileBlobBackend, StagedBlob
from tests.repositories.fake_remote import MODIFIED, FakeRemote, etag_of

URL = "http://remote.test/files/a/b.bin"
CONTENT = b"content held by the remote"


@pytest.fixture
def fake() -> FakeRemote:
    remote_ = FakeRemote()
    remote_.files["files/a/b.bin"] = CONTENT
    return remote_


@pytest.fixture
def backend(tmp_path) -> FileBlobBackend:
    return FileBlobBackend(tmp_path / "store")


@pytest.fixture
def stage(backend):
    async def stage_checked(chunks: AsyncIterator[bytes], size: int | None) -> StagedBlob:
        staged = await backend.stage(chunks)
        if size is not None and staged.size != size:
            await backend.discard(staged)
            raise ApiError(400, "checksum_mismatch", "The size does not match.")
        return staged

    return stage_checked


def temporary_files(tmp_path) -> list:
    directory = tmp_path / "store" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


async def fetch(fake, stage, **options):
    async with fake.client() as client:
        options.setdefault("authorization", None)
        return await remote.download(client, URL, stage=stage, **options)


async def test_download_stages_the_content_and_reports_what_the_remote_said(fake, stage):
    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Fetched)
    assert outcome.staged.sha256 == hashlib.sha256(CONTENT).hexdigest()
    assert (outcome.content_type, outcome.etag, outcome.last_modified) == (
        "application/x-remote",
        etag_of(CONTENT),
        MODIFIED,
    )


async def test_requests_identify_megooarti_and_ask_for_the_bytes_as_stored(fake, stage):
    await fetch(fake, stage)

    (seen,) = fake.requests
    assert seen["headers"]["user-agent"] == f"MegooArti/{__version__}"
    assert seen["headers"]["accept-encoding"] == "identity"
    assert "authorization" not in seen["headers"]


async def test_an_unchanged_file_is_not_downloaded_again(fake, stage, tmp_path):
    outcome = await fetch(fake, stage, etag=etag_of(CONTENT), last_modified=MODIFIED)

    assert outcome == remote.NotModified()
    assert fake.requests[0]["headers"]["if-modified-since"] == MODIFIED
    assert temporary_files(tmp_path) == []


async def test_a_file_the_remote_lacks_is_missing(fake, stage):
    fake.files.clear()
    assert await fetch(fake, stage) == remote.Missing()

    fake.status = 410
    assert await fetch(fake, stage) == remote.Missing()


@pytest.mark.parametrize(
    ("status", "blockable"),
    [
        (502, True),
        (503, True),
        (504, True),
        (429, True),
        (500, False),
        (401, False),
        (403, False),
        (400, False),
    ],
)
async def test_other_answers_are_failures_and_only_some_count_towards_blocking(
    fake, stage, tmp_path, status, blockable
):
    fake.status = status

    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is blockable
    assert str(status) in outcome.reason
    assert temporary_files(tmp_path) == []


async def test_an_unreachable_remote_is_a_blockable_failure(fake, stage):
    fake.down = True

    outcome = await fetch(fake, stage)

    assert outcome == remote.Failed("ConnectError", blockable=True)


async def test_a_file_shorter_than_declared_is_a_failure_and_leaves_nothing(fake, stage, tmp_path):
    fake.declared_extra = 5

    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is True
    assert temporary_files(tmp_path) == []


async def test_the_credential_is_sent_to_the_remote(fake, stage):
    await fetch(fake, stage, authorization="Bearer the-remote-token")

    assert fake.requests[0]["headers"]["authorization"] == "Bearer the-remote-token"


async def test_the_credential_does_not_follow_a_redirect_to_another_host(fake, stage):
    fake.redirect_to = "http://elsewhere.test"

    outcome = await fetch(fake, stage, authorization="Bearer the-remote-token")

    first, second = fake.requests
    assert isinstance(outcome, remote.Fetched)
    assert (first["host"], second["host"]) == ("remote.test", "elsewhere.test")
    assert "authorization" in first["headers"]
    assert "authorization" not in second["headers"]


async def test_head_reports_existence_without_fetching_the_body(fake):
    async with fake.client() as client:
        exists = await remote.head(client, URL, authorization=None)
        fake.files.clear()
        missing = await remote.head(client, URL, authorization=None)
        fake.status = 500
        failed = await remote.head(client, URL, authorization=None)

    assert isinstance(exists, remote.Exists)
    assert exists.headers["Content-Length"] == str(len(CONTENT))
    assert exists.headers["Content-Type"] == "application/x-remote"
    assert missing == remote.Missing()
    assert isinstance(failed, remote.Failed)
    assert [seen["method"] for seen in fake.requests] == ["HEAD", "HEAD", "HEAD"]


def test_authorization_headers_for_each_kind_of_credential(tmp_path):
    settings = Settings(_env_file=None, database_url="postgresql://u:p@db/m", data_dir=tmp_path)
    sealed = seal(settings, "s3cret")
    expected_basic = "Basic " + base64.b64encode(b"robot:s3cret").decode()

    assert remote.authorization(settings, {"type": "none"}) is None
    assert remote.authorization(settings, {"type": "bearer", "secret": sealed}) == "Bearer s3cret"
    basic = {"type": "basic", "username": "robot", "secret": sealed}
    assert remote.authorization(settings, basic) == expected_basic


def test_a_credential_sealed_with_another_key_is_unreadable(tmp_path):
    here = Settings(_env_file=None, database_url="postgresql://u:p@db/m", data_dir=tmp_path)
    sealed = seal(here.model_copy(update={"secret_key": "another key"}), "s3cret")

    with pytest.raises(SecretUnreadable):
        remote.authorization(here, {"type": "bearer", "secret": sealed})


async def test_the_outbound_client_is_built_once_when_first_needed():
    application = SimpleNamespace(state=SimpleNamespace(http=None))

    first = remote.client_of(application)
    try:
        assert isinstance(first, httpx.AsyncClient)
        assert remote.client_of(application) is first
        assert application.state.http is first
    finally:
        await first.aclose()


def test_an_application_that_never_proxies_builds_no_outbound_client(app):
    assert app.state.http is None


async def test_cookies_from_the_remote_are_never_kept(fake, stage):
    fake.set_cookie = "JSESSIONID=signed-in-as-robot; Path=/"

    async with fake.client() as client:
        await remote.download(client, URL, authorization="Bearer t", stage=stage)
        await remote.download(client, URL, authorization=None, stage=stage)

    assert "cookie" not in fake.requests[1]["headers"]


async def test_a_body_the_remote_compressed_anyway_is_not_stored(fake, stage, tmp_path):
    fake.content_encoding = "gzip"

    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is False
    assert temporary_files(tmp_path) == []


@pytest.mark.parametrize("url", ["http://remote.test:abc/files/a/b.bin", "http://[::1/x"])
async def test_a_url_that_cannot_be_requested_is_a_failure_not_a_crash(fake, stage, url):
    async with fake.client() as client:
        downloaded = await remote.download(client, url, authorization=None, stage=stage)
        asked = await remote.head(client, url, authorization=None)

    assert isinstance(downloaded, remote.Failed)
    assert isinstance(asked, remote.Failed)
    assert (downloaded.blockable, asked.blockable) == (False, False)


async def test_a_credential_that_cannot_be_a_header_is_a_failure_not_a_crash(fake, stage):
    outcome = await fetch(fake, stage, authorization="Bearer tökën")

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is False


@pytest.mark.parametrize(
    "target", ["http://169.254.169.254", "http://127.0.0.1:9000", "http://10.1.2.3"]
)
async def test_a_redirect_from_a_public_remote_to_an_internal_address_is_refused(
    fake, stage, target
):
    fake.redirect_to = target

    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is False
    assert "internal" in outcome.reason
    assert len(fake.requests) == 1  # the internal address was never contacted


async def test_a_remote_that_is_itself_internal_may_redirect_internally(fake, stage):
    fake.files["files/a/b.bin"] = CONTENT
    fake.redirect_to = "http://10.1.2.3"

    async with fake.client() as client:
        outcome = await remote.download(
            client, "http://127.0.0.1/files/a/b.bin", authorization=None, stage=stage
        )

    assert isinstance(outcome, remote.Fetched)

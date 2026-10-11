"""A remote that wants a token before it serves anything, as container registries do."""

from collections.abc import AsyncIterator

import pytest

from megooarti.repositories import remote
from megooarti.repositories.remote import Document, Exists, Failed, Fetched, Missing, SignIn
from megooarti.storage.backends import FileBlobBackend
from tests.repositories.fake_registry import REGISTRY, FakeRegistry, basic, digest_of

MANIFEST = f"{REGISTRY}/v2/team/app/manifests/1.0"
SIGN_IN = SignIn(REGISTRY, "team/app")
LAYER = b"a layer" * 1000


@pytest.fixture
def registry() -> FakeRegistry:
    registry = FakeRegistry()
    registry.add_image("team/app", "1.0", LAYER)
    registry.add_image("team/other", "1.0", b"another layer")
    return registry


@pytest.fixture
async def client(registry) -> AsyncIterator:
    async with registry.client() as client:
        yield client


async def get(client, url: str = MANIFEST, sign_in: SignIn | None = SIGN_IN, **options):
    options.setdefault("authorization", None)
    return await remote.fetch(client, url, limit=1024 * 1024, sign_in=sign_in, **options)


def tokens_asked(registry: FakeRegistry) -> list[dict]:
    return [seen for seen in registry.requests if seen["path"] == "/token"]


async def test_a_remote_that_wants_a_token_is_given_one(registry, client):
    answer = await get(client)

    assert isinstance(answer, Document)
    assert digest_of(answer.body) == answer.headers["Docker-Content-Digest"]
    (asked,) = tokens_asked(registry)
    assert asked["host"] == "auth.registry.test"
    assert asked["query"] == {"service": "registry.test", "scope": "repository:team/app:pull"}
    assert "authorization" not in asked["headers"]  # there is no credential to present
    sent = [seen["headers"].get("authorization") for seen in registry.requests]
    assert sent == [None, None, "Bearer token-1"]  # refused, signed in, served


async def test_a_token_is_used_until_it_runs_out(registry, client, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(remote, "_now", lambda: clock[0])
    await get(client)
    registry.requests.clear()

    await get(client)
    at_once = [seen["headers"].get("authorization") for seen in registry.requests]
    clock[0] += 300 - 10  # its five minutes, less the margin
    registry.requests.clear()
    await get(client)

    assert at_once == ["Bearer token-1"]  # no refusal first, and no sign-in
    assert len(tokens_asked(registry)) == 1
    assert registry.requests[-1]["headers"]["authorization"] == "Bearer token-2"


@pytest.mark.parametrize(("seconds", "kept"), [(None, True), (5, False), (10**9, True)])
async def test_how_long_a_token_is_kept(registry, client, monkeypatch, seconds, kept):
    clock = [1000.0]
    monkeypatch.setattr(remote, "_now", lambda: clock[0])
    registry.token_seconds = seconds
    await get(client)

    clock[0] += 45  # under the minute a token is good for if nothing says otherwise
    await get(client)
    clock[0] += 3600  # nobody's word keeps one longer than an hour
    await get(client)

    assert len(tokens_asked(registry)) == (2 if kept else 3)


async def test_a_token_is_for_one_thing_and_one_credential(registry, client):
    registry.accounts["ci"] = "secret"
    await get(client)

    other = await get(
        client, f"{REGISTRY}/v2/team/other/manifests/1.0", SignIn(REGISTRY, "team/other")
    )
    as_ci = await get(client, authorization=basic("ci", "secret"))

    assert isinstance(other, Document) and isinstance(as_ci, Document)
    scopes = [asked["query"]["scope"] for asked in tokens_asked(registry)]
    assert scopes == ["repository:team/app:pull", "repository:team/other:pull", scopes[0]]
    assert [account for account, _ in registry.issued.values()] == [None, None, "ci"]


async def test_a_token_the_remote_no_longer_takes_is_replaced(registry, client):
    await get(client)
    registry.issued.clear()  # revoked, or the registry restarted

    answer = await get(client)

    assert isinstance(answer, Document)
    assert len(tokens_asked(registry)) == 2


async def test_the_credential_goes_to_the_sign_in_address_and_the_token_to_the_remote(
    registry, client
):
    registry.accounts["ci"] = "secret"
    registry.private.add("team/app")
    registry.blobs_at = "https://cdn.registry.test"
    credential = basic("ci", "secret")
    blob = f"{REGISTRY}/v2/team/app/blobs/{digest_of(LAYER)}"

    async def stage(chunks, size):
        return b"".join([chunk async for chunk in chunks])

    fetched = await remote.download(
        client, blob, authorization=credential, stage=stage, sign_in=SIGN_IN
    )

    assert isinstance(fetched, Fetched) and fetched.staged == LAYER
    by_host = {seen["host"]: seen["headers"].get("authorization") for seen in registry.requests}
    assert by_host == {
        "registry.test": "Bearer token-1",  # after the first attempt, which sent the credential
        "auth.registry.test": credential,
        "cdn.registry.test": None,  # where the blob is kept learns nothing
    }
    assert registry.requests[0]["headers"]["authorization"] == credential


async def test_a_wrong_credential_is_a_failure_that_does_not_block(registry, client):
    registry.accounts["ci"] = "secret"

    answer = await get(client, authorization=basic("ci", "wrong"))

    # No status: it is not the remote's answer about what was asked for, and must not
    # be taken for "you may not see this image".
    assert answer == Failed("its sign-in address refused the credential", blockable=False)


async def test_an_image_the_token_does_not_open_is_refused_by_the_remote(registry, client):
    registry.private.add("team/app")

    answer = await get(client)

    assert answer == Failed("the remote answered 401", blockable=False, status=401)
    assert len(tokens_asked(registry)) == 1  # asked once, not in a loop


async def test_a_token_that_is_not_a_basic_credential_is_not_shown_to_the_sign_in_address(
    registry, client
):
    await get(client, authorization="Bearer a-static-token")

    assert "authorization" not in tokens_asked(registry)[0]["headers"]


@pytest.mark.parametrize(
    ("realm", "reason"),
    [
        ("http://auth.registry.test/token", "it asks for sign-in over plain HTTP"),
        ("https://127.0.0.1/token", "it points at an internal address"),
        ("https://169.254.169.254/latest/meta-data", "it points at an internal address"),
        ("https://localhost:8443/token", "it points at an internal address"),
    ],
)
async def test_where_a_remote_may_send_us_to_sign_in(registry, client, realm, reason):
    registry.accounts["ci"] = "secret"
    registry.realm = realm

    answer = await get(client, authorization=basic("ci", "secret"))

    assert isinstance(answer, Failed) and answer.reason.endswith(reason)
    assert answer.blockable is False
    assert tokens_asked(registry) == []  # nothing was sent there, the credential least of all


async def test_a_remote_on_an_internal_address_may_name_its_own(registry, client):
    registry.realm = "http://10.0.0.5:5001/token"
    here = "http://10.0.0.5:5000"

    answer = await get(client, f"{here}/v2/team/app/manifests/1.0", SignIn(here, "team/app"))

    assert isinstance(answer, Document)


@pytest.mark.parametrize("challenge", ['Bearer realm="registry"', 'Basic realm="registry"', ""])
async def test_a_refusal_that_names_no_address_is_only_a_refusal(registry, client, challenge):
    registry.challenge = challenge

    answer = await get(client)

    assert answer == Failed("the remote answered 401", blockable=False, status=401)
    assert tokens_asked(registry) == []


@pytest.mark.parametrize(
    "answer",
    [b"not json", b"[]", b"{}", b'{"token": 7}', b'{"token": "line\\nbreak"}', b" " * 70_000],
    ids=["text", "a list", "empty", "a number", "a line break", "too long"],
)
async def test_a_sign_in_answer_that_cannot_be_used(registry, client, answer):
    registry.token_answer = answer

    result = await get(client)

    assert result == Failed("its sign-in address gave no usable token", blockable=False)


async def test_a_sign_in_address_that_answers_something_else_is_a_failure(registry, client):
    registry.realm = "https://auth.registry.test/missing"

    answer = await get(client)

    assert answer == Failed("its sign-in address answered 404", blockable=False, status=404)


async def test_without_being_told_to_sign_in_a_refusal_stays_one(registry, client):
    answer = await get(client, sign_in=None)
    asked = await remote.head(client, MANIFEST, authorization=None)

    assert answer == asked == Failed("the remote answered 401", blockable=False, status=401)
    assert tokens_asked(registry) == []


async def test_asking_about_a_file_signs_in_too_and_gives_every_header(registry, client):
    answer = await remote.head(client, MANIFEST, authorization=None, sign_in=SIGN_IN)
    missing = await remote.head(
        client, f"{REGISTRY}/v2/team/app/manifests/2.0", authorization=None, sign_in=SIGN_IN
    )

    assert isinstance(answer, Exists)
    assert answer.every["docker-content-digest"].startswith("sha256:")
    assert "Docker-Content-Digest" not in answer.headers  # not what a client is passed
    assert missing == Missing()
    assert registry.asked("HEAD") == ["/v2/team/app/manifests/1.0"] * 2 + [
        "/v2/team/app/manifests/2.0"
    ]


async def test_what_is_accepted_is_said(registry, client):
    await get(client, accept="application/vnd.oci.image.index.v1+json, */*")

    assert registry.requests[-1]["headers"]["accept"] == (
        "application/vnd.oci.image.index.v1+json, */*"
    )
    assert registry.requests[-1]["headers"]["accept-encoding"] == "identity"


async def test_a_document_has_a_limit(registry, client):
    registry.wants_token = False

    whole = await remote.fetch(client, MANIFEST, authorization=None, limit=100_000)
    cut = await remote.fetch(client, MANIFEST, authorization=None, limit=100)
    missing = await remote.fetch(client, MANIFEST + "0", authorization=None, limit=100)

    assert isinstance(whole, Document)
    assert cut == Failed("the remote sent more than a document may hold", blockable=False)
    assert missing == Missing()


async def test_a_remote_that_is_down_is_a_failure_that_blocks(registry, client):
    registry.down = True

    answer = await get(client)

    assert answer == Failed("ConnectError", blockable=True)


async def test_what_one_client_learned_another_does_not_know(registry, client):
    await get(client)
    registry.requests.clear()

    async with registry.client() as other:
        await get(other)

    assert len(tokens_asked(registry)) == 1


async def test_a_whole_file_is_staged_through_a_sign_in(registry, client, tmp_path):
    backend = FileBlobBackend(tmp_path)

    async def stage(chunks, size):
        return await backend.stage(chunks)

    blob = f"{REGISTRY}/v2/team/app/blobs/{digest_of(LAYER)}"
    fetched = await remote.download(client, blob, authorization=None, stage=stage, sign_in=SIGN_IN)

    assert isinstance(fetched, Fetched)
    assert "sha256:" + fetched.staged.sha256 == digest_of(LAYER)


async def test_the_sign_in_address_is_asked_for_an_answer_that_is_not_compressed(registry, client):
    await get(client)
    registry.token_answer = b"\x1f\x8b\x08 a compressed answer"
    registry.token_headers = {"Content-Encoding": "gzip"}

    other = await get(
        client, f"{REGISTRY}/v2/team/other/manifests/1.0", SignIn(REGISTRY, "team/other")
    )

    assert tokens_asked(registry)[0]["headers"]["accept-encoding"] == "identity"
    assert other == Failed("its sign-in address sent an encoded answer", blockable=False)


async def test_a_token_is_for_the_remote_it_was_fetched_for(registry, client):
    # Two remotes may name the same sign-in address, service and scope. The second must
    # sign in for itself: the rules about that address are applied when it does.
    registry.realm = "http://10.0.0.5:5001/token"
    inside = "http://10.0.0.5:5000"
    await get(client, f"{inside}/v2/team/app/manifests/1.0", SignIn(inside, "team/app"))

    outside = await get(client)

    assert isinstance(outside, Failed)
    assert outside.reason.endswith("it points at an internal address")
    assert len(tokens_asked(registry)) == 1

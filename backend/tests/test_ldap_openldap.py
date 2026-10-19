"""Sign-in with a real directory's password (spec 7, 12): OpenLDAP in a container beside
the built stack, its people and groups loaded at start (tests/openldap), StartTLS with a
certificate of an authority made in the test, which the stack trusts once it is added
(15c). A person's directory password then works for curl, as for any package client.

Run with `pytest -m docker`.
"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from tests.accounts import basic
from tests.containers import BACKEND_DIR, HTTP_PORT, PROJECT, call
from tests.tls import authority, ffdhe2048, server_certificate

pytestmark = pytest.mark.docker

IMAGE = "osixia/openldap:1.5.0"
CONTAINER = f"{PROJECT}-openldap"
ADMIN_DN = "cn=admin,dc=corp,dc=example"
ADMIN_PASSWORD = "the directory's admin password"
LDIF = BACKEND_DIR / "tests" / "openldap" / "corp.ldif"
ADDRESS = f"http://127.0.0.1:{HTTP_PORT}"
CA = authority("Corp Directory CA")


def docker(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, encoding="utf-8", check=False
    )


@pytest.fixture(scope="module")
def openldap(stack):
    """OpenLDAP on the stack's network as `openldap`, with StartTLS and the corp entries."""
    served = server_certificate(CA, "openldap")
    with tempfile.TemporaryDirectory() as folder:
        certs, ldif = Path(folder) / "certs", Path(folder) / "ldif"
        certs.mkdir()
        ldif.mkdir()
        (certs / "ldap.crt").write_text(served.pem)
        (certs / "ca.crt").write_text(CA.pem)
        # Without them, slapd spends minutes making some before it serves TLS.
        (certs / "dhparam.pem").write_bytes(ffdhe2048())
        (certs / "ldap.key").write_bytes(
            served.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        shutil.copy(LDIF, ldif / "50-corp.ldif")
        docker("rm", "--force", CONTAINER)
        started = docker(
            "run", "--detach", "--name", CONTAINER, "--hostname", "openldap",
            "--network", f"{PROJECT}_default", "--network-alias", "openldap",
            "--env", "LDAP_ORGANISATION=Corp", "--env", "LDAP_DOMAIN=corp.example",
            "--env", f"LDAP_ADMIN_PASSWORD={ADMIN_PASSWORD}",
            "--env", "LDAP_TLS_CRT_FILENAME=ldap.crt", "--env", "LDAP_TLS_KEY_FILENAME=ldap.key",
            "--env", "LDAP_TLS_CA_CRT_FILENAME=ca.crt", "--env", "LDAP_TLS_VERIFY_CLIENT=never",
            "--env", "LDAP_TLS_DH_PARAM_FILENAME=dhparam.pem",
            "--volume", f"{certs}:/container/service/slapd/assets/certs",
            "--volume", f"{ldif}:/container/service/slapd/assets/config/bootstrap/ldif/custom",
            IMAGE, "--copy-service",
        )  # fmt: skip
        assert started.returncode == 0, started.stderr
        deadline = time.monotonic() + 120
        while True:
            found = docker(
                "exec", CONTAINER, "ldapsearch", "-x", "-H", "ldap://localhost",
                "-b", "ou=people,dc=corp,dc=example", "-D", ADMIN_DN, "-w", ADMIN_PASSWORD,
                "(uid=kim)",
            )  # fmt: skip
            if found.returncode == 0 and "uid=kim" in found.stdout:
                break
            assert time.monotonic() < deadline, docker("logs", "--tail", "60", CONTAINER).stdout
            time.sleep(2)
        yield
    docker("rm", "--force", CONTAINER)


@pytest.fixture(scope="module")
def corp(administrator, openldap) -> str:
    """A repository, the role the group gives, and the source: its id."""
    status, _, said = call(
        "POST", "/repositories", {"name": "files", "format": "raw", "type": "hosted"}, administrator
    )
    assert status == 201, said
    role = {
        "name": "deployers",
        "description": "",
        "permissions": ["repository:raw:files"],
        "roles": [],
    }
    status, _, said = call("POST", "/roles", role, administrator)
    assert status == 201, said
    source = {
        "kind": "ldap",
        "name": "Corp LDAP",
        "enabled": True,
        "settings": {
            "url": "ldap://openldap",
            "starttls": True,
            "bind_dn": ADMIN_DN,
            "bind_password": ADMIN_PASSWORD,
            "user_base": "ou=people,dc=corp,dc=example",
            "groups": "search",
            "group_base": "ou=groups,dc=corp,dc=example",
        },
        "group_mapping": [{"group": "developers", "roles": ["deployers"]}],
    }
    status, _, said = call("POST", "/auth-sources", source, administrator)
    assert status == 201, said
    return said["id"]


def test_starttls_is_trusted_once_the_directorys_authority_is_added(administrator, corp):
    status, _, before = call("POST", f"/auth-sources/{corp}/test", {}, administrator)
    status, _, added = call("POST", "/certificates", {"pem": CA.pem}, administrator)
    assert status == 201, added
    status, _, after = call(
        "POST", f"/auth-sources/{corp}/test", {"username": "kim"}, administrator
    )

    assert before["ok"] is False and "CERTIFICATE_VERIFY_FAILED" in before["message"], before
    assert after["ok"] is True, after
    assert after["user"]["groups"] == ["cn=developers,ou=groups,dc=corp,dc=example", "developers"]
    assert after["user"]["roles"] == ["deployers"]


def test_a_person_puts_and_gets_a_file_with_curl_and_their_directory_password(corp):
    curl = shutil.which("curl")
    assert curl, "curl is not installed"
    account = ["--user", "kim:kims-directory-password", "--silent", "--show-error"]
    with tempfile.TemporaryDirectory() as folder:
        sent = Path(folder) / "hello.txt"
        sent.write_text("hello from the directory")
        address = f"{ADDRESS}/repository/files/hello.txt"
        put = subprocess.run(
            [curl, *account, "--fail", "--upload-file", str(sent), address],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        got = subprocess.run(
            [curl, *account, "--fail", address],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        wrong = subprocess.run(
            [curl, "--user", "kim:not-it", "--silent", "--output", str(Path(folder) / "refused"),
             "--write-out", "%{http_code}", address],
            capture_output=True, text=True, check=False,
        )  # fmt: skip

    assert put.returncode == 0, put.stderr
    assert got.stdout == "hello from the directory", got.stderr
    assert wrong.stdout == "401"
    status, _, session = call(
        "GET", "/auth/session", headers=basic("kim", "kims-directory-password")
    )
    assert (status, session["user"]["display_name"], session["user"]["email"]) == (
        200,
        "Kim Lee",
        "kim@corp.example",
    )

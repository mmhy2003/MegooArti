"""An LDAP server on 127.0.0.1 that speaks just enough of the protocol for what the mock
strategy cannot show: a referral, a result code of failure, a connection dropped. Binds
succeed, and are recorded; every search is answered as the test says."""

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


def _tlv(tag: int, body: bytes) -> bytes:
    size = len(body)
    if size < 0x80:
        length = bytes([size])
    else:
        octets = size.to_bytes((size.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(octets)]) + octets
    return bytes([tag]) + length + body


def _read(data: bytes, at: int) -> tuple[int, bytes, int]:
    tag, size = data[at], data[at + 1]
    at += 2
    if size & 0x80:
        count = size & 0x7F
        size = int.from_bytes(data[at : at + count], "big")
        at += count
    return tag, data[at : at + size], at + size


def _result(operation: int, code: int, referral: str | None = None) -> bytes:
    body = _tlv(0x0A, bytes([code])) + _tlv(0x04, b"") + _tlv(0x04, b"")
    if referral is not None:
        body += _tlv(0xA3, _tlv(0x04, referral.encode()))
    return _tlv(operation, body)


@dataclass
class WireDirectory:
    """How each search is answered: a result code, with a referral to another address,
    or the connection dropped."""

    search_code: int = 0
    referral: str | None = None
    drop_on_search: bool = False
    binds: list[tuple[str, str]] = field(default_factory=list)

    def _serve(self, listener: socket.socket) -> None:
        while True:
            try:
                peer, _ = listener.accept()
            except OSError:
                return  # closed: the test is over
            with peer:
                self._converse(peer)

    def _converse(self, peer: socket.socket) -> None:
        while True:
            data = peer.recv(65536)
            if not data:
                return
            _, message, _ = _read(data, 0)
            _, message_id, after = _read(message, 0)
            tag, operation, _ = _read(message, after)
            identifier = _tlv(0x02, message_id)
            if tag == 0x60:  # bind
                _, _, at = _read(operation, 0)
                _, name, at = _read(operation, at)
                _, password, _ = _read(operation, at)
                self.binds.append((name.decode(), password.decode()))
                peer.sendall(_tlv(0x30, identifier + _result(0x61, 0)))
            elif tag == 0x63:  # search
                if self.drop_on_search:
                    return
                answer = _result(0x65, self.search_code, self.referral)
                peer.sendall(_tlv(0x30, identifier + answer))
            elif tag == 0x42:  # unbind
                return

    @contextmanager
    def serving(self) -> Iterator[int]:
        """Listen on 127.0.0.1 while the block runs: its port."""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        threading.Thread(target=self._serve, args=(listener,), daemon=True).start()
        try:
            yield listener.getsockname()[1]
        finally:
            listener.close()


def settings_for(port: int, **more) -> dict:
    """An LDAP source's settings, as the kind keeps them, for a server at this port."""
    return {
        "url": f"ldap://127.0.0.1:{port}",
        "starttls": False,
        "bind_dn": "cn=reader,dc=corp,dc=example",
        "bind_password": "the reader's password",
        "user_base": "ou=people,dc=corp,dc=example",
        "user_filter": "(uid={username})",
        "groups": "none",
        "username_attribute": "uid",
        "name_attribute": "cn",
        "email_attribute": "mail",
        **more,
    }

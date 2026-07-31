"""Minimal MTGNP client for Phase 2 testing.

Provides simple helpers to connect and exchange PDUs.
"""
from __future__ import annotations

import socket
from typing import Tuple

from .common import framing
from .common import pdu as PDUs
from .common.verbose import set_verbose


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False):
        set_verbose(verbose)
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port))

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def hello(self) -> dict:
        if not self.sock:
            raise RuntimeError("not connected")
        framing.send_pdu(self.sock, {"type": PDUs.HELLO, "name": "test-client"})
        return framing.recv_pdu(self.sock)

    def ping(self) -> dict:
        if not self.sock:
            raise RuntimeError("not connected")
        framing.send_pdu(self.sock, {"type": PDUs.PING})
        return framing.recv_pdu(self.sock)


def quick_ping(host: str, port: int) -> Tuple[str, dict]:
    c = Client(host=host, port=port)
    c.connect()
    resp = c.ping()
    c.close()
    return (resp.get("type"), resp)

"""Minimal MTGNP client for Phase 2 testing.

Provides simple helpers to connect and exchange PDUs and an
interactive lobby input loop for users.
"""
from __future__ import annotations

import socket
import threading
import queue
import time
from typing import Tuple, Optional

from .common import framing
from .common import pdu as PDUs
from .common.verbose import set_verbose
from .client_pdu_handler import ClientPDUHandler
from .states.lobbyState import LobbyState
from .states.mulliganState import MulliganState


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False, log_filename: str = ""):
        set_verbose(verbose, filename=log_filename)
        self.host = host
        self.port = port
        self.seq_num = 0 # latest seq_num received from server
        self.sock: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_q: "queue.Queue[dict]" = queue.Queue()
        self._recv_stop = threading.Event()
        self.player_id: Optional[str] = None
        self._ready = False
        self._start_game = False
        self._last_error: Optional[dict] = None
        self.players_count = 0
        self.players_ready: int = 0
        self.waiting_for: list[str] = []
        self.pdu_handler = ClientPDUHandler(self)
        self.mulligan_count = 0
        self.ready_seq_num = 0          # only for PLAYER_READY

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port))
        # start receiver thread
        self._recv_stop.clear()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def close(self) -> None:
        self._recv_stop.set()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        if self._recv_thread:
            self._recv_thread.join(timeout=0.2)

    def _recv_loop(self) -> None:
        while not self._recv_stop.is_set():
            if not self.sock:
                break
            try:
                pkt = framing.recv_pdu(self.sock)
            except (ConnectionError, OSError):
                break
            except Exception:
                # ignore malformed or protocol errors here
                continue
            try:
                # dispatch via client-side handler (also enqueues by default)
                self.pdu_handler.handle_pdu(pkt)
            except Exception:
                try:
                    self._recv_q.put_nowait(PDUs.make_error(500, "recv handler error"))
                except Exception:
                    pass

    def send_pdu(self, obj: dict) -> None:
        if not self.sock:
            raise RuntimeError("not connected")

        if obj["type"] == PDUs.PLAYER_READY:
            self.ready_seq_num += 1
            obj["seq_num"] = self.ready_seq_num
        else:
            obj["seq_num"] = self.seq_num

        framing.send_pdu(self.sock, obj)

    def hello(self, name: str = "test-client", timeout: float = 2.0) -> dict:
        if not self.sock:
            raise RuntimeError("not connected")
        self.send_pdu({"type": PDUs.HELLO, "name": name})
        # wait for welcome
        try:
            pkt = self._recv_q.get(timeout=timeout)
            return pkt
        except queue.Empty:
            raise TimeoutError("no welcome from server")

    def ping(self) -> dict:
        if not self.sock:
            raise RuntimeError("not connected")
        self.send_pdu({"type": PDUs.PING})
        try:
            return self._recv_q.get(timeout=1.0)
        except queue.Empty:
            raise TimeoutError("no pong")

    @staticmethod
    def load_deck(filename: str) -> list[str]:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]

    def interactive_lobby(self, name: str = "player") -> None:
        """Delegate the lobby UI to the `LobbyState` object."""
        lobby = LobbyState(self)
        lobby.run(name)


def quick_ping(host: str, port: int) -> Tuple[str, dict]:
    c = Client(host=host, port=port)
    c.connect()
    resp = c.ping()
    c.close()
    return (resp.get("type"), resp)


if __name__ == "__main__":
    name = input("Enter your name: ").strip()

    client = Client()
    client.interactive_lobby(name)

    print("LOBBY FINISHED")

    

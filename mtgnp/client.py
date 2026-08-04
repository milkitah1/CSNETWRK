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


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False, log_filename: str = ""):
        set_verbose(verbose, filename=log_filename)
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_q: "queue.Queue[dict]" = queue.Queue()
        self._recv_stop = threading.Event()

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
                self._recv_q.put_nowait(pkt)
            except Exception:
                pass

    def send_pdu(self, obj: dict) -> None:
        
        if not self.sock:
            raise RuntimeError("not connected")
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

    def interactive_lobby(self, name: str = "player") -> None:
        """Simple terminal UI that shows lobby status and lets the user mark ready.
        """
        self.connect()
        try:
            welcome = self.hello(name)
            print("Connected to MTGNP Server")
            ready = False
            start_game = False
            players_count = 1

            # small loop: display status, accept input, handle incoming PDUs
            while True:
                # process any incoming PDUs
                while True:
                    try:
                        pkt = self._recv_q.get_nowait()
                    except queue.Empty:
                        break
                    t = pkt.get("type")
                    if t == PDUs.START_GAME:
                        print("\n==> START_GAME received — game starting")
                        start_game = True
                    elif t == PDUs.PLAYER_READY:
                        # server-side may broadcast player readiness (optional)
                        players_count = pkt.get("players", players_count)
                    elif t == "PLAYER_READY_ACK":
                        ready = True
                    elif t == PDUs.ERROR:
                        print(f"ERROR from server: {pkt.get('message')}")

                if start_game:
                    break

                # render lobby UI
                print("\n========== LOBBY ==========\n")
                print(f"Players: {players_count} / 2\n")
                print(f"You are {'ready' if ready else 'not ready'}.\n")
                if not ready:
                    print("1. Ready")
                print("q. Quit")

                choice = input("Select: ").strip().lower()
                if choice == "1" and not ready:
                    # send PLAYER_READY
                    try:
                       
                        self.send_pdu({"type": PDUs.PLAYER_READY})
                    except Exception as e:
                        print(f"failed to send PLAYER_READY: {e}")
                elif choice == "q":
                    break
                else:
                    # small sleep to avoid busy loop
                    time.sleep(0.1)

            if start_game:
                print("Entering game loop (not implemented)")
        finally:
            self.close()


def quick_ping(host: str, port: int) -> Tuple[str, dict]:
    c = Client(host=host, port=port)
    c.connect()
    resp = c.ping()
    c.close()
    return (resp.get("type"), resp)

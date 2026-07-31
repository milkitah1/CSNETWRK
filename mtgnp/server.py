"""Simple MTGNP server skeleton for Phase 2.

Features:
- Accepts TCP connections, thread-per-client
- Handles `PING` -> `PONG` and `HELLO` -> `WELCOME`
"""
from __future__ import annotations

import socket
import threading
from typing import Optional

from .common import framing
from .common import pdu as PDUs
from .common.verbose import set_verbose


class ClientHandler(threading.Thread):
    def __init__(self, conn: socket.socket, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.running = True

    def run(self) -> None:
        try:
            while self.running:
                pkt = framing.recv_pdu(self.conn)
                t = pkt.get("type")
                if t == PDUs.PING:
                    framing.send_pdu(self.conn, {"type": PDUs.PONG})
                elif t == PDUs.HELLO:
                    # simple accept and send WELCOME
                    framing.send_pdu(self.conn, {"type": PDUs.WELCOME, "message": "Welcome to MTGNP"})
                else:
                    framing.send_pdu(self.conn, PDUs.make_error(400, f"unhandled pdu type: {t}"))
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False):
        set_verbose(verbose)
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: list[ClientHandler] = []
        self._stop = threading.Event()

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(5)
        # if port was 0, update self.port
        self.port = self._sock.getsockname()[1]

        def accept_loop():
            while not self._stop.is_set():
                try:
                    conn, addr = self._sock.accept()
                except OSError:
                    break
                handler = ClientHandler(conn, addr)
                self._clients.append(handler)
                handler.start()

        self._accept_thread = threading.Thread(target=accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        # join client threads
        for c in self._clients:
            c.running = False
            try:
                c.join(timeout=0.2)
            except Exception:
                pass


if __name__ == "__main__":
    srv = Server()
    print(f"Starting server on {srv.host}:{srv.port}")
    srv.start()
    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        print("Shutting down")
        srv.stop()

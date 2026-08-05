"""Simple MTGNP server skeleton for Phase 2.

Features:
- Accepts TCP connections, thread-per-client

"""
from __future__ import annotations

import socket
import threading
from typing import Optional
import uuid

from .common import framing
from .common import pdu as PDUs
from .common.verbose import set_verbose
from .common.managers.lobby_manager import Lobby
from .common.lifecycle import GameLifecycleEngine
from . import pdu_handlers


class ClientHandler(threading.Thread):
    def __init__(self, conn: socket.socket, addr, server: "Server"):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.server = server
        self.running = True
        self.player_id: str | None = None
        # per-client PDU dispatcher
        self.pdu_handler = pdu_handlers.PDUHandler(self)

    def _send(self, obj):
        try:
            obj["seq_num"] = (obj.get("seq_num", 0)) + 1
            framing.send_pdu(self.conn, obj)
        except Exception as e:
            print("SEND ERROR:", e)
            raise

    def run(self) -> None:
        try:
            while self.running:
                pkt = framing.recv_pdu(self.conn)
                self.pdu_handler.handle_pdu(pkt)
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            if self.player_id:
                try:
                    self.server.gameEngine.unregister_player(self.player_id)
                except Exception:
                    pass


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False, log: bool = False):
        set_verbose(verbose, log=log)
        self.host = host
        self.port = port
        self.lobby = Lobby(max_players=2)
        self.gameEngine = GameLifecycleEngine()
        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: list[ClientHandler] = []
        self._stop = threading.Event()

        self._game_starter_thread: Optional[threading.Thread] = None

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
                handler = ClientHandler(conn, addr, self)
                self._clients.append(handler)
                handler.start()

        def game_starter():
            # wait for both players to be present and ready
            ready = self.lobby.wait_for_all_ready()
            if not ready:
                return

            # only start setup if both players are already registered in lifecycle
            if len(self.gameEngine.registered_players) < 2:
                return
            
            # initialize the game state for setup + mulligan
            self.gameEngine.run_game_setup()

            # tell clients the game has started and is in mulligan state
            for c in list(self._clients):
                try:
                    framing.send_pdu(c.conn, {
                        "type": PDUs.START_GAME,
                        "macro_state": self.gameEngine.macro_state.value,
                        "phase": self.gameEngine.phase,
                        "turn": self.gameEngine.game_state.turn_number
                    })
                except Exception:
                    pass

        # start the accept loop and game start threads
        self._accept_thread = threading.Thread(target=accept_loop, daemon=True)
        self._accept_thread.start()
        self._game_starter_thread = threading.Thread(target=game_starter, daemon=True)
        self._game_starter_thread.start()

    # stop the server and all client threads
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

    # broadcast a message to all connected clients
    def broadcast(self, msg: dict):
        for c in list(self._clients):
            try:
                framing.send_pdu(c.conn, msg)
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

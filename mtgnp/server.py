"""Simple MTGNP server skeleton for Phase 2.

Features:
- Accepts TCP connections, thread-per-client

"""
from __future__ import annotations
import json
import socket
import threading
import time
from typing import Optional
import uuid

from .common import framing
from .common import pdu as PDUs
from .common.verbose import set_verbose
from .common.lifecycle import GameLifecycleEngine
from .pdu_handlers import PDUHandler


class ClientHandler(threading.Thread):
    def __init__(self, conn: socket.socket, addr, server: "Server"):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.server = server
        self.running = True
        self.player_id: str | None = None
        # Section 6.2: the client-chosen player_id claimed via PLAYER_READY
        self.claimed_player_id: str | None = None
        # PDUHandler is created after server is set so it can access server.gameEngine
        self.pdu_handler = PDUHandler(self)
        self.seq_num = 0
        self.ping_seq_num = 0
        
    
    def _send(self, obj):
        try:
            if obj["type"] != PDUs.PONG:
                self.seq_num += 1
                obj["seq_num"] = self.seq_num
            else:
                self.ping_seq_num = obj.get("seq_num", self.ping_seq_num)
                obj["seq_num"] = self.ping_seq_num
            
            framing.send_pdu(self.conn, obj)
        except Exception as e:
            print("SEND ERROR:", e)
            raise

    def run(self) -> None:
        try:
            while self.running:
                pkt = framing.recv_pdu(self.conn)
                try:
                    self.pdu_handler.handle_pdu(pkt)
                except Exception as e:
                    try:
                        self._send(PDUs.make_error(500, str(e)))
                    except Exception:
                        pass
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            if self.player_id:
                engine = self.server.gameEngine
                try:
                    from .common.lifecycle import MacroState
                    if engine.macro_state == MacroState.IN_GAME and engine.game_state is not None:
                        loser = self.player_id
                        winner = engine.get_opponent(loser)
                        if winner:
                            # Route through lifecycle — idempotent, broadcasts GAME_OVER
                            self.pdu_handler._finish_game(winner, loser, "DISCONNECT")
                except Exception:
                    pass
                try:
                    engine.unregister_player(self.player_id)
                except Exception:
                    pass


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False, log: bool = False):
        set_verbose(verbose, log=log)
        self.host = host
        self.port = port
        
        self.gameEngine = GameLifecycleEngine(max_players=2)
        # Wire the lifecycle broadcast callback so trigger_game_over() auto-broadcasts
        self.gameEngine.lifecycle.on_game_over = self._on_game_over
        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: list[ClientHandler] = []
        self._stop = threading.Event()

        self._game_starter_thread: Optional[threading.Thread] = None
        with open("./jsons/cards_list/card_instances.json", "r") as f:
            cards = json.load(f)
            self.LEGAL_CARDS = {
                card["card_id (protocol reference)"]
                for card in cards
            }

    # Called by LifecycleManager.on_game_over — broadcasts GAME_OVER to all clients
    def _on_game_over(self, winner_id: str, loser_id: str, reason: str) -> None:
        self.broadcast({
            "type": PDUs.GAME_OVER,
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason,
        })
        # Section 6.6: after broadcasting GAME_OVER the server returns to the
        # LOBBY state on the same TCP connections, awaiting fresh PLAYER_READY.
        self.gameEngine.reset_to_lobby()

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
            from .common.lifecycle import MacroState
            engine = self.gameEngine
            # Loop so that after every GAME_OVER the server re-enters the lobby
            # and can start a new game on the same connections (Section 6.6).
            while not self._stop.is_set():
                # Block until both players have joined and are ready.
                if not engine.wait_for_all_ready():
                    continue
                # Only start a fresh game while back in the LOBBY state.
                if engine.macro_state != MacroState.LOBBY or len(engine.registered_players) < engine.max_players:
                    time.sleep(0.05)
                    continue

                # initialize the game state for setup + mulligan
                engine.run_game_setup()

                # send each player their initial game state (including hand, deck, etc.)
                self.broadcast({
                    "type": PDUs.START_GAME,

                })
                self.send_game_state_to_all()

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
                c._send(msg)
            except Exception as e:
                print("Broadcast failed:", e)

    def send_game_state_to_all(self):
        for c in list(self._clients):
            try:
                state = self.gameEngine.get_visible_state(c.player_id)

                c._send({
                    "type": PDUs.GAME_STATE_UPDATE,
                    "state": state
                })

            except Exception as e:
                print("Failed sending game state:", e)


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

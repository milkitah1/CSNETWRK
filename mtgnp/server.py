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
from .engine.rules_engine import RulesEngine


class ClientHandler(threading.Thread):
    def __init__(self, conn: socket.socket, addr, server: "Server"):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.server = server
        self.running = True
        self.player_id: str | None = None
        # The client-chosen player_id claimed via PLAYER_READY
        self.claimed_player_id: str | None = None
        # PDUHandler is created after server is set so it can access server.gameEngine
        self.pdu_handler = PDUHandler(self)
        self.seq_num = 0
        self.ping_seq_num = 0
        # A connection is written to by its client thread, the game-starter
        # thread, and sometimes another player's handler.  Keep each framed
        # PDU atomic so a header from one message can never be followed by the
        # JSON body of another.
        self._send_lock = threading.Lock()
        
    
    def _send(self, obj):
        try:
            with self._send_lock:
                msg = dict(obj)
                if "seq_num" not in msg:
                    if msg.get("type") != PDUs.PONG:
                        self.seq_num += 1
                        msg["seq_num"] = self.seq_num
                    else:
                        self.ping_seq_num = msg.get("seq_num", self.ping_seq_num)
                        msg["seq_num"] = self.ping_seq_num
                framing.send_pdu(self.conn, msg)
        except Exception as e:
            print("SEND ERROR:", e)
            raise

    def run(self) -> None:
        try:
            while self.running:
                pkt = framing.recv_pdu(self.conn)
                try:
                    # The game state is shared by both client threads.  An
                    # action must be checked and applied as one transaction;
                    # otherwise simultaneous mulligan/priority PDUs can race.
                    with self.server._state_lock:
                        self.pdu_handler.handle_pdu(pkt)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    try:
                        self._send(PDUs.make_error("INTERNAL_ERROR", str(e)))
                    except Exception:
                        pass
                    # Broadcast GAME_OVER reset so both clients gracefully unblock instead of deadlocking
                    try:
                        with self.server._state_lock:
                            if self.server.gameEngine.macro_state == MacroState.IN_GAME:
                                self.server._on_game_over("NONE", "NONE", f"Server Error: {e}")
                    except Exception:
                        pass
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            # A disconnected client cannot receive GAME_OVER.  Removing it
            # before the disconnect handler broadcasts prevents writes to a
            # closed socket and leaves the notification for the opponent.
            with self.server._state_lock:
                try:
                    self.server._clients.remove(self)
                except ValueError:
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
        # Rules state (priority passes, stack, combat and triggers) belongs to
        # the match, not to an individual TCP connection.
        self.rules_engine = RulesEngine(lifecycle=self.gameEngine)
        # Wire the lifecycle broadcast callback so trigger_game_over() auto-broadcasts
        self.gameEngine.lifecycle.on_game_over = self._on_game_over
        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: list[ClientHandler] = []
        self._stop = threading.Event()
        # Serializes lifecycle and rules-engine mutations across client
        # handlers and the game-starter thread.
        self._state_lock = threading.RLock()

        self._game_starter_thread: Optional[threading.Thread] = None
        with open("./jsons/cards_list/card_instances.json", "r") as f:
            cards = json.load(f)
            self.LEGAL_CARDS = {
                card["card_id (protocol reference)"]
                for card in cards
            }

    # Called by LifecycleManager.on_game_over — broadcasts GAME_OVER to all clients
    def _on_game_over(self, winner_id: str, loser_id: str, reason: str) -> None:
        if getattr(self, "is_game_over", False):
            return
        self.is_game_over = True
        seq = 1
        if hasattr(self.gameEngine, "game_state") and self.gameEngine.game_state:
            self.gameEngine.game_state.seq_num += 1
            seq = self.gameEngine.game_state.seq_num

        self.broadcast({
            "type": PDUs.GAME_OVER,
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason,
            "seq_num": seq,
        })
        # After broadcasting GAME_OVER the server returns to the
        # LOBBY state on the same TCP connections, awaiting fresh PLAYER_READY.
        self.gameEngine.reset_to_lobby()
        self.is_game_over = False

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(2)
        # if port was 0, update self.port
        self.port = self._sock.getsockname()[1]

        def accept_loop():
            while not self._stop.is_set():
                try:
                    conn, addr = self._sock.accept()
                except OSError:
                    break

                if len(self.gameEngine.joined_players) >= self.gameEngine.max_players:
                    try:
                        framing.send_pdu(conn, PDUs.make_error("LOBBY_FULL", "LOBBY_FULL"))
                    except Exception:
                        pass
                   
                    continue

                handler = ClientHandler(conn, addr, self)
                self._clients.append(handler)
                handler.start()

        def game_starter():
            from .common.lifecycle import MacroState
            engine = self.gameEngine
            # Loop so that after every GAME_OVER the server re-enters the lobby
            # and can start a new game on the same connections.
            while not self._stop.is_set():
                # Block until both players have joined and are ready.
                if not engine.wait_for_all_ready():
                    continue
                # Only start a fresh game while back in the LOBBY state.
                if engine.macro_state != MacroState.LOBBY or len(engine.registered_players) < engine.max_players:
                    time.sleep(0.05)
                    continue

                with self._state_lock:
                    # Readiness may have changed while this thread was waiting.
                    if engine.macro_state != MacroState.LOBBY or not engine.all_ready():
                        continue

                    # initialize the game state for setup + mulligan
                    engine.run_game_setup()
                    # A fresh game must not inherit priority/pass state from a
                    # previous match on these same connections.
                    self.rules_engine = RulesEngine(lifecycle=engine)

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
                    "seq_num": self.gameEngine.game_state.seq_num if self.gameEngine.game_state else 0,
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

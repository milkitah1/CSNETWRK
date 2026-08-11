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
                    if engine.macro_state in (MacroState.IN_GAME, MacroState.MULLIGAN,
                                              MacroState.GAME_SETUP) and engine.game_state is not None:
                        # A hard socket close mid-match starts the reconnect
                        # grace window instead of ending the game immediately.
                        self.server.begin_reconnect_grace(self)
                        return
                except Exception:
                    pass
                try:
                    engine.unregister_player(self.player_id)
                except Exception:
                    pass


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False, log: bool = False,
                 reconnect_timeout: float = 10.0):
        set_verbose(verbose, log=log)
        self.host = host
        self.port = port
        # Implementation-defined window during which a disconnected player's
        # seat is held so they can re-attach via RECONNECT before the server
        # ends the match with GAME_OVER (reason DISCONNECT).
        self.reconnect_timeout = float(reconnect_timeout)
        # player_id -> ClientHandler whose socket closed mid-match.
        self._reconnecting: dict[str, "ClientHandler"] = {}
        
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
        with self._state_lock:
            if getattr(self, "is_game_over", False):
                return
            self.is_game_over = True
            # Compute seq_num while still holding the lock so both threads
            # cannot advance it independently.
            seq = 1
            if hasattr(self.gameEngine, "game_state") and self.gameEngine.game_state:
                self.gameEngine.game_state.seq_num += 1
                seq = self.gameEngine.game_state.seq_num
            pdu = {
                "type": PDUs.GAME_OVER,
                "winner_id": winner_id,
                "loser_id": loser_id,
                "reason": reason,
                "seq_num": seq,
            }

        # Broadcast outside the lock to avoid holding _state_lock during I/O.
        # is_game_over stays True, so any concurrent _on_game_over entry will
        # hit the early-return above.
        self.broadcast(pdu)

        # After broadcasting GAME_OVER the server returns to the
        # LOBBY state on the same TCP connections, awaiting fresh PLAYER_READY.
        self.gameEngine.reset_to_lobby()
        with self._state_lock:
            self.is_game_over = False

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

                # While a disconnected player's seat is still reserved for
                # reconnection, accept new sockets so that a RECONNECT can
                # complete on a fresh TCP connection.
                with self._state_lock:
                    reconnect_pending = bool(self._reconnecting)
                if len(self.gameEngine.joined_players) >= self.gameEngine.max_players and not reconnect_pending:
                    try:
                        framing.send_pdu(conn, PDUs.make_error("LOBBY_FULL", "LOBBY_FULL"))
                    except Exception:
                        pass
                    try:
                        conn.close()
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
        dead = []
        for c in list(self._clients):
            try:
                c._send(msg)
            except Exception:
                # Socket may have been closed between the list copy and the
                # send (e.g. a concurrent handler finally-block).  Remove it
                # silently; the handler's own finally-block will also try.
                dead.append(c)
        for c in dead:
            try:
                self._clients.remove(c)
            except ValueError:
                pass

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

    # -----------------------------------------------------------------------
    # Disconnect / Reconnect handling (implementation-defined timeout)
    # -----------------------------------------------------------------------
    def begin_reconnect_grace(self, handler: "ClientHandler") -> None:
        """Hold a disconnected player's seat for `reconnect_timeout` seconds.

        A hard socket close mid-match (IN_GAME / MULLIGAN / SETUP) does not
        end the game immediately: the seat is reserved and, if the same player
        calls RECONNECT within the window, the match resumes on a fresh TCP
        connection.  When the window elapses, the match ends with
        GAME_OVER(DISCONNECT) and the seat is freed.
        """
        from .common.lifecycle import MacroState
        engine = self.gameEngine
        player_id = handler.player_id

        if engine.macro_state not in (MacroState.IN_GAME, MacroState.MULLIGAN,
                                      MacroState.GAME_SETUP) or engine.game_state is None:
            # Not mid-match: nothing to preserve, just free the seat.
            if player_id:
                try:
                    engine.unregister_player(player_id)
                except Exception:
                    pass
            return

        if self.reconnect_timeout <= 0:
            # Timeout disabled -> fall back to immediate DISCONNECT.
            self._finalize_disconnect(handler)
            return

        with self._state_lock:
            self._reconnecting[player_id] = handler

        def watchdog() -> None:
            # Let the reconnect window elapse, then end the match if the seat
            # was never reclaimed (handle_reconnect cancels this via pop).
            time.sleep(self.reconnect_timeout)
            with self._state_lock:
                if self._reconnecting.get(player_id) is handler:
                    del self._reconnecting[player_id]
                    self._finalize_disconnect(handler)

        threading.Thread(target=watchdog, daemon=True).start()

    def _finalize_disconnect(self, handler: "ClientHandler") -> None:
        """End the match with DISCONNECT and free the player's seat."""
        from .common.lifecycle import MacroState
        engine = self.gameEngine
        player_id = handler.player_id
        try:
            if engine.macro_state in (MacroState.IN_GAME, MacroState.MULLIGAN,
                                      MacroState.GAME_SETUP) and engine.game_state is not None:
                winner = engine.get_opponent(player_id)
                if winner:
                    # Idempotent via LifecycleManager: broadcasts GAME_OVER once.
                    handler.pdu_handler._finish_game(winner, player_id, "DISCONNECT")
        except Exception:
            pass
        if player_id:
            try:
                engine.unregister_player(player_id)
            except Exception:
                pass

    def is_reconnect_pending(self, player_id: str) -> bool:
        return player_id in self._reconnecting


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

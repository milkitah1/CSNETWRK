"""Minimal MTGNP client for Phase 2 testing.

Provides simple helpers to connect and exchange PDUs and an
interactive lobby input loop for users.
"""
from __future__ import annotations

import socket
import threading
import queue
import time
import curses
from typing import Tuple, Optional

from .common import framing
from .common import pdu as PDUs
from .common.verbose import set_verbose
from .client_pdu_handler import ClientPDUHandler
from .client_ui.ui_mulligan import MulliganState

from .client_ui.ui_lobby import LobbyCardSelectionState # change this to * if needed


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 4444, verbose: bool = False, log_filename: str = "", ping_interval: float = 30.0, ping_timeout: float = 10.0):
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
        self._reconnected = False
        self.players_count = 0
        self.players_ready: int = 0
        self.waiting_for: list[str] = []
        self.pdu_handler = ClientPDUHandler(self)
        self.mulligan_count = 0
        self.ready_seq_num = 0          # only for PLAYER_READY
        self.ping_seq_num = 0           # separate counter for PING PDUs
        # ping/pong heartbeat
        self.ping_interval = float(ping_interval)
        self.ping_timeout = float(ping_timeout)
        self._ping_thread: Optional[threading.Thread] = None
        self._ping_stop = threading.Event()
        self._pong_event = threading.Event()
        self._last_pong: Optional[float] = None
        # Set to True when GAME_OVER is received; blocks further sends
        self._game_over: bool = False
        self.visible_state: Optional[dict] = None
        self.phase_seq_num: int = 0
        self.cleanup_seq_num: int = 0
        self.priority_grant_seq_num: int = 0
        self.pending_prompt: Optional[dict] = None
        # The UI and heartbeat threads can send at the same time.  A lock keeps
        # the length prefix and JSON body of each PDU together on the wire.
        self._send_lock = threading.Lock()

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port))
        # start receiver thread
        self._recv_stop.clear()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        # start ping thread
        self._start_ping()

    def close(self) -> None:
        # stop ping thread first
        self._stop_ping()
        self._recv_stop.set()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        if self._recv_thread:
            self._recv_thread.join(timeout=0.2)
        # clear pong event
        try:
            self._pong_event.clear()
        except Exception:
            pass

    # --- ping thread management ---
    def _start_ping(self) -> None:
        if self._ping_thread and self._ping_thread.is_alive():
            return
        self._ping_stop.clear()
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()

    def _stop_ping(self) -> None:
        self._ping_stop.set()
        if self._ping_thread and threading.current_thread() is not self._ping_thread:
            try:
                self._ping_thread.join(timeout=0.5)
            except Exception:
                pass

    def _ping_loop(self) -> None:
        # Periodically send PING and wait for PONG within timeout
        while not self._ping_stop.is_set():
            try:
                # clear previous pong
                self._pong_event.clear()
                # send ping
                try:
                    self.send_pdu({"type": PDUs.PING})
                except Exception:
                    # can't send; assume disconnected
                    try:
                        self.close()
                    except Exception:
                        pass
                    break

                # wait for pong
                got = self._pong_event.wait(self.ping_timeout)
                if not got:
                    # no pong within timeout -> disconnect
                    try:
                        print("No PONG received; disconnecting")
                        self.close()
                    except Exception:
                        pass
                    try:
                        self.close()
                    except Exception:
                        pass
                    break

                # sleep until next ping interval (respect stop)
                slept = 0.0
                while slept < self.ping_interval and not self._ping_stop.is_set():
                    time.sleep(0.5)
                    slept += 0.5
            except Exception:
                # on unexpected error, attempt clean shutdown
                try:
                    self.close()
                except Exception:
                    pass
                break

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
        # Do not mutate a UI-owned action dict.  In particular, callers pass
        # the exact priority token received in PRIORITY_GRANT.
        msg = dict(obj)
        # Block all non-heartbeat sends once the game is over, except the few
        # PDUs needed to start a rematch on the same connection (fresh
        # PLAYER_READY / HELLO) or to re-attach after a mid-game disconnect
        # (RECONNECT).  Anything else silently dropped, as a finished match no
        # longer accepts game actions.
        if self._game_over and msg.get("type") not in (
            PDUs.PING, PDUs.DISCONNECT, PDUs.PLAYER_READY, PDUs.HELLO, PDUs.RECONNECT,
        ):
            return

        ptype = msg.get("type")
        if ptype == PDUs.PLAYER_READY:
            self.ready_seq_num += 1
            msg["seq_num"] = self.ready_seq_num
        elif ptype == PDUs.PING:
            # use a dedicated ping counter so heartbeats don't affect other seq counters
            self.ping_seq_num += 1
            msg["seq_num"] = self.ping_seq_num
        elif "seq_num" not in msg:
            # Non-priority messages do not use the priority token, but retain
            # the current value for backwards-compatible server diagnostics.
            msg["seq_num"] = self.seq_num

        with self._send_lock:
            framing.send_pdu(self.sock, msg)

    def hello(self, name: str = "test-client", timeout: float = 2.0) -> dict:
        if not self.sock:
            raise RuntimeError("not connected")
        self.send_pdu({"type": PDUs.HELLO, "name": name})

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no welcome from server")
            try:
                pkt = self._recv_q.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("no welcome from server")

            ptype = pkt.get("type")
            if ptype in {PDUs.HELLO, PDUs.ERROR, PDUs.WELCOME}:
                return pkt

    def ping(self) -> dict:
        if not self.sock:
            raise RuntimeError("not connected")
        self.send_pdu({"type": PDUs.PING})
        try:
            return self._recv_q.get(timeout=1.0)
        except queue.Empty:
            raise TimeoutError("no pong")

    def reconnect(self, player_id: str, timeout: float = 5.0) -> dict:
        """Open a fresh TCP connection and re-attach to a pending session.

        The server holds the player's seat for `reconnect_timeout` seconds
        after a mid-game disconnect; this sends RECONNECT and returns the
        RECONNECT_ACK (or an ERROR if the window has already expired).
        """
        if self.sock:
            self.close()
        self.connect()
        self._reconnected = False
        self.send_pdu({"type": PDUs.RECONNECT, "player_id": player_id})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                pkt = self._recv_q.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                continue
            t = pkt.get("type")
            if t == PDUs.RECONNECT_ACK:
                self.player_id = player_id
                return pkt
            if t == PDUs.ERROR:
                return pkt
        raise TimeoutError("no RECONNECT_ACK from server")

    @staticmethod
    def load_deck(filename: str) -> list[str]:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]

    def interactive_lobby(self, stdscr, name: str = "player") -> None:
        """Delegate the lobby UI to the `LobbyState` object."""
        # lobby = LobbyState(self)
        # lobby.run(name)
        lobby = LobbyCardSelectionState(stdscr)
        return lobby.get_cards()

    def run_lobby(self, stdscr, name):
        """Run the curses lobby until the game starts or the client quits.

        PLAYER_READY is sent after the player finishes deck selection.
        ClientPDUHandler callbacks notify this function when the server
        accepts the submission, rejects it with ERROR, or starts the game.
        """
        lobby = {
            "ready": False,
            "start_game": False,
            "error": None,
        }

        def on_error(pkt):
            lobby["error"] = pkt
            lobby["ready"] = False

        def on_game_state_update(pkt):
            state = pkt.get("state") or {}

            if state.get("phase") == "LOBBY":
                self.game_state = state

                players_ready = state.get("players_ready")
                if players_ready is not None:
                    try:
                        self.players_ready = int(players_ready)
                    except (TypeError, ValueError):
                        pass

                waiting_for = state.get("waiting_for")
                if isinstance(waiting_for, list):
                    self.waiting_for = list(waiting_for)

                # If our PLAYER_READY was accepted, the server's lobby
                # state should show us as ready.
                if name not in self.waiting_for:
                    lobby["ready"] = True

            elif state.get("phase") != "LOBBY":
                lobby["start_game"] = True

        def on_start_game(pkt):
            lobby["start_game"] = True
            self._start_game = True

        # Register callbacks for the duration of the lobby.
        self.pdu_handler.register_callback(PDUs.ERROR, on_error)
        self.pdu_handler.register_callback(PDUs.GAME_STATE_UPDATE, on_game_state_update)
        self.pdu_handler.register_callback(PDUs.START_GAME, on_start_game)

        # Only send HELLO on the initial lobby connection.
        # Rematches reuse the existing TCP connection and go directly
        # to PLAYER_READY as required by the protocol.
        if not self.player_id:
            self.hello(name)

        while not lobby["start_game"]:
            lobby["ready"] = False
            lobby["error"] = None
            self._last_error = None

            # Let the player build/select a deck. If the server rejects it,
            # this loop returns here and allows another PLAYER_READY.
            decklist = LobbyCardSelectionState(stdscr).get_cards()

            if not decklist:
                # ESC with no cards: leave the lobby.
                return False

            try:

                # Starting a rematch: clear the previous GAME_OVER state.
                self._game_over = False
                self._last_error = None
                self._start_game = False
                
                message = {
                    "type": PDUs.PLAYER_READY,
                    "player_id": name,
                    "deck_list": decklist,
                }
                self.send_pdu(message)

            except Exception as exc:
                stdscr.clear()
                stdscr.addstr(2, 2, f"Failed to send PLAYER_READY: {exc}")
                stdscr.addstr(4, 2, "Press any key to return to deck selection.")
                stdscr.refresh()
                stdscr.getch()

                continue


            # Wait for either an ERROR or a GAME_STATE_UPDATE.
            while not lobby["ready"] and not lobby["error"] and not lobby["start_game"]:
                curses.napms(50)

            if lobby["error"]:
                error = lobby["error"]
                code = error.get("code", "UNKNOWN_ERROR")
                message = error.get("message", "The server rejected the deck.")

                print("ERROR PACKET:", error)

                stdscr.clear()
                stdscr.addstr(2, 2, "PLAYER_READY was rejected")
                stdscr.addstr(4, 2, f"Code: {code}")
                stdscr.addstr(5, 2, f"Message: {message}")
                stdscr.addstr(7, 2, "Press any key to choose a deck again.")
                stdscr.refresh()
                stdscr.getch()
                stdscr.clear()
                stdscr.refresh()
                continue

            # Accepted, but the other player may not be ready yet.
            if lobby["ready"] and not lobby["start_game"]:
                stdscr.clear()
                stdscr.addstr(2, 2, "Deck accepted!")
                stdscr.addstr(4, 2, f"Players ready: {self.players_ready}/2")

                if self.waiting_for:
                    stdscr.addstr(5, 2, "Waiting for: " + ", ".join(self.waiting_for))

                stdscr.addstr(7, 2, "Waiting for the game to start...")
                stdscr.refresh()

                while not lobby["start_game"]:
                    curses.napms(50)
        return decklist

    def run_mulligan(self, stdscr):
        mulligan = MulliganState(self)
    
        keeps = False
        while not keeps:
            keeps = mulligan.keep_or_mulligan()
            self.send_pdu({
                "type": "MULLIGAN_CHOICE", "keep": keeps, "cards_to_bottom": mulligan.bottomed_cards
            })
    
        if mulligan.mulligan_count > 0:
            mulligan.bottom_cards()
            self.send_pdu({
                "type": "MULLIGAN_CHOICE", "keep": keeps, "cards_to_bottom": mulligan.bottomed_cards
            })

    def run_main_game(self, stdscr) -> None:
        from .client_ui.ui_main_game import GameUI
        game_ui = GameUI(stdscr, self.player_id or "Player")
        # Decode terminal arrow-key escape sequences into curses.KEY_UP/DOWN
        # so selectors, including the Actions menu, can move their cursor.
        stdscr.keypad(True)
        stdscr.timeout(50)

        while not self._game_over:
            state = self.visible_state or {}
            game_ui.render(state)

            key = stdscr.getch()
            if key != -1:
                action = game_ui.handle_key(key, state)
                if action == "QUIT":
                    break
                elif action == "PASS":
                    # Only send PRIORITY_PASS when this player actually holds priority.
                    # Suppress silently if we're in an automatic phase or opponent's priority window.
                    priority_holder = state.get("priority_holder")
                    if priority_holder and priority_holder == self.player_id:
                        self.send_pdu({"type": PDUs.PRIORITY_PASS, "seq_num": self.priority_grant_seq_num})
                elif isinstance(action, dict):
                    p_type = action.get("type")
                    if "seq_num" not in action:
                        if p_type in (PDUs.TRIGGER_ORDER_RESPONSE, PDUs.TRIGGER_CHOICE_RESPONSE):
                            if self.pending_prompt and "seq_num" in self.pending_prompt:
                                action["seq_num"] = self.pending_prompt["seq_num"]
                            else:
                                action["seq_num"] = self.priority_grant_seq_num
                            self.pending_prompt = None
                        elif p_type == PDUs.DISCARD:
                            action["seq_num"] = self.cleanup_seq_num if self.cleanup_seq_num is not None else self.priority_grant_seq_num
                        elif p_type in (PDUs.DECLARE_ATTACKERS, PDUs.DECLARE_BLOCKERS, PDUs.ASSIGN_DAMAGE_ORDER):
                            # PHASE_TRANSITION carries a transport sequence
                            # number.  Combat actions must instead use the
                            # authoritative token from PRIORITY_GRANT.
                            action["seq_num"] = self.priority_grant_seq_num
                        elif p_type in (PDUs.CAST_SPELL, PDUs.PLAY_LAND, PDUs.ACTIVATE_ABILITY):
                            action["seq_num"] = self.priority_grant_seq_num
                    self.send_pdu(action)

        if self._game_over:
            stdscr.clear()
            stdscr.addstr(5, 5, "=== GAME OVER ===")
            stdscr.addstr(7, 5, "Press any key to exit.")
            stdscr.refresh()
            stdscr.timeout(-1)
            try:
                stdscr.getch()
            except Exception:
                pass



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

    

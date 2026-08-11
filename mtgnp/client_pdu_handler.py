"""Client-side PDU packet handler and event dispatcher for MTGNP.

Handles incoming server protocol packets, updates local client game state tracking,
manages sequence numbers, and triggers UI updates/callbacks.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .common import pdu as PDUs

#function when client receives pdu
class ClientPDUHandler:
    """Client-side PDU dispatcher.

    Responsibilities:
    - Map incoming PDUs to handler methods
    - Update `client` state (player_id, ready, start_game) where appropriate
    - Forward PDUs to the client's receive queue by default
    - Allow registering simple callbacks for specific PDU types
    """

    def __init__(self, client) -> None:
        self.client = client
        self._callbacks: Dict[str, Callable[[dict], None]] = {}
        self.handlers = {
            PDUs.PONG: self._handle_pong,
            PDUs.WELCOME: self._handle_welcome,
            PDUs.HELLO: self._handle_hello,
            PDUs.START_GAME: self._handle_start_game,
            PDUs.PLAYER_READY: self._handle_player_ready,
            "PLAYER_READY_ACK": self._handle_player_ready_ack,
            PDUs.ERROR: self._handle_error,
            PDUs.GAME_STATE_UPDATE: self._handle_game_state_update,
            PDUs.GAME_OVER: self._handle_game_over,
            PDUs.PRIORITY_GRANT: self._handle_priority_grant,
            PDUs.PHASE_TRANSITION: self._handle_phase_transition,
            PDUs.TRIGGER_ORDER: self._handle_trigger_prompt,
            PDUs.TRIGGER_CHOICE: self._handle_trigger_prompt,
            PDUs.RECONNECT_ACK: self._handle_reconnect_ack,
        }

    def register_callback(self, pdu_type: str, cb: Callable[[dict], None]) -> None:
        self._callbacks[pdu_type] = cb

    def handle_pdu(self, pkt: dict) -> None:
        """Dispatch an incoming PDU to the appropriate handler.

        Handlers should be fast and non-blocking. By default the PDU is also
        queued onto `client._recv_q` so existing client code continues to work.
        """
        if not isinstance(pkt, dict):
            return
        type = pkt.get("type")
        if "seq_num" in pkt:
            self.client.seq_num = pkt["seq_num"]
        handler = self.handlers.get(type)
        try:
            if handler:
                handler(pkt)
            # deliver to client receive queue by default
            try:
                self.client._recv_q.put_nowait(pkt)
            except Exception:
                pass
            # invoke any registered callback
            cb = self._callbacks.get(type)
            if cb:
                try:
                    cb(pkt)
                except Exception:
                    pass
        except Exception:
            # swallow handler exceptions to avoid killing recv loop
            try:
                self.client._recv_q.put_nowait(PDUs.make_error(500, "client handler error"))
            except Exception:
                pass

    # ---- handlers ----
    def _handle_pong(self, pkt: dict) -> None:
        # record last pong timestamp and notify ping loop
        try:
            import time as _t
            self.client._last_pong = _t.time()
        except Exception:
            pass
        try:
            self.client._pong_event.set()
        except Exception:
            pass
        return

    def _handle_welcome(self, pkt: dict) -> None:
        # server welcome may include metadata
        return

    def _handle_hello(self, pkt: dict) -> None:
        # server-assigned player id
        pid = pkt.get("player_id")
        if pid:
            self.client.player_id = pid

    def _handle_start_game(self, pkt: dict) -> None:
        # mark that game is starting and expose payload
        self.client._start_game = True
        # A fresh match begins (e.g. rematch after GAME_OVER on the same
        # connection): clear the game-over flag and old priority tokens so
        # in-game actions are accepted again and stale tokens can't be reused.
        self.client._game_over = False
        self.client._last_error = None
        self.client.priority_grant_seq_num = 0
        self.client.cleanup_seq_num = 0
        self.client.phase_seq_num = 0
        # Drain any PDUs left over from the previous match so the next state
        # machine starts from a clean queue.
        try:
            while True:
                self.client._recv_q.get_nowait()
        except Exception:
            pass
        # store basic metadata if present
        self.client._server_macro_state = pkt.get("macro_state")
        self.client._server_phase = pkt.get("phase")
        self.client._server_turn = pkt.get("turn")

    def _handle_reconnect_ack(self, pkt: dict) -> None:
        # successful RECONNECT: client is re-attached to the pending session
        self.client._reconnected = True

    def _handle_player_ready(self, pkt: dict) -> None:
        # server may broadcast lobby changes; keep a simple counter field
        players = pkt.get("players")
        if players is not None:
            try:
                self.client.players_count = int(players)
            except Exception:
                pass

    def _handle_player_ready_ack(self, pkt: dict) -> None:
        # client has successfully marked ready
        self.client._ready = True

    def _handle_error(self, pkt: dict) -> None:
        # store last error for quick inspection
        if pkt.get("message") == "LOBBY_FULL":
            
         print(f"Received ERROR PDU: {pkt}")
        
        self.client._last_error = pkt
        # A rejected action often means this client missed a phase/state
        # update.  Request an authoritative snapshot without blocking the
        # receiver thread; send_pdu serializes this with UI/heartbeat traffic.
        if pkt.get("code") in {"STALE_ACTION", "NOT_YOUR_PRIORITY"}:
            try:
                self.client.send_pdu({"type": PDUs.STATE_REQUEST})
            except Exception:
                pass

    def _handle_game_over(self, pkt: dict) -> None:
        """Set client into GAME_OVER state and display result."""
        self.client._game_over = True
        winner = pkt.get("winner_id", "?")
        loser = pkt.get("loser_id", "?")
        reason = pkt.get("reason", "?")
        try:
            print(f"\n=== GAME OVER === winner={winner}  loser={loser}  reason={reason}")
        except Exception:
            pass

    def _handle_priority_grant(self, pkt: dict) -> None:
        if "seq_num" in pkt:
            self.client.priority_grant_seq_num = pkt["seq_num"]

    def _handle_phase_transition(self, pkt: dict) -> None:
        # PHASE_TRANSITION is stamped by the per-connection transport stream,
        # so its seq_num cannot validate a game action.  PRIORITY_GRANT is the
        # sole source of an action token, including during combat.
        return

    def _handle_trigger_prompt(self, pkt: dict) -> None:
        self.client.pending_prompt = pkt

    def _handle_game_state_update(self, pkt: dict) -> None:
        # Parse lobby-phase updates and update client-friendly fields
        self.client.visible_state = pkt.get("state")

        state = pkt.get("state") or {}
        phase = state.get("phase")

        if phase == "CLEANUP" or pkt.get("request_discard"):
            if "seq_num" in pkt:
                self.client.cleanup_seq_num = pkt["seq_num"]

        if phase == "LOBBY":
            # players_ready: number of ready players
            players_ready = state.get("players_ready")
            if players_ready is not None:
                try:
                    self.client.players_ready = int(players_ready)
                except Exception:
                    pass

            # waiting_for: list of player ids still to be ready
            waiting = state.get("waiting_for")
            if isinstance(waiting, list):
                self.client.waiting_for = list(waiting)

            # optional players count
            players = state.get("players_ready")
            if players is not None:
                try:
                    self.client.players_count = int(players)
                except Exception:
                    pass
        return



__all__ = ["ClientPDUHandler"]

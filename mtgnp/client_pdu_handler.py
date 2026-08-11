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
        # store basic metadata if present
        self.client._server_macro_state = pkt.get("macro_state")
        self.client._server_phase = pkt.get("phase")
        self.client._server_turn = pkt.get("turn")

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

    def _handle_game_state_update(self, pkt: dict) -> None:
        # Parse lobby-phase updates and update client-friendly fields
        self.client.visible_state = pkt.get("state")

        state = pkt.get("state") or {}
        phase = state.get("phase")
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
        # otherwise leave full game-state updates to the recv queue
        return



__all__ = ["ClientPDUHandler"]

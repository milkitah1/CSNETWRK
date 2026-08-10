from __future__ import annotations
import traceback
from typing import Any
import uuid
from .common import pdu as PDUs
from .engine.rules_engine import RulesEngine
from .common.lifecycle import MacroState

#handler for the clienhandler class from the server
class PDUHandler:
    """Class-based PDU dispatcher for a single client handler instance.

    Dispatches PDUs via a mapping of PDU type -> bound method, matching the
    pattern requested by the user.
    """

    # In-game PDU types forwarded directly to RulesEngine
    _RULES_ENGINE_TYPES = {
        PDUs.PRIORITY_PASS, PDUs.CAST_SPELL, PDUs.ACTIVATE_ABILITY,
        PDUs.PLAY_LAND, PDUs.DECLARE_ATTACKERS, PDUs.DECLARE_BLOCKERS,
        PDUs.ASSIGN_DAMAGE_ORDER,
    }

    def __init__(self, client: Any) -> None:
        self.client = client
        # Pass lifecycle engine reference so RulesEngine can call trigger_game_over()
        self.rules_engine = RulesEngine(lifecycle=client.server.gameEngine if hasattr(client, 'server') else None)
        self.handlers = {
            PDUs.PING: self.handle_ping,
            PDUs.HELLO: self.handle_hello,
            PDUs.PLAYER_READY: self.handle_player_ready,
            PDUs.MULLIGAN_CHOICE: self.handle_mulligan_choice,
            PDUs.CONCEDE: self.handle_concede,
            PDUs.DISCONNECT: self.handle_disconnect,
        }

    def handle_pdu(self, pkt: dict) -> None:
        t = pkt.get("type")
        handler = self.handlers.get(t)
        if handler:
            handler(pkt)
        elif t in self._RULES_ENGINE_TYPES:
            self.handle_rules_engine_pdu(pkt)
        else:
            self.client._send(PDUs.make_error(400, f"unhandled pdu type: {t}"))

    # -------------------------------------------------------------------------
    # Shared helper: broadcast GAME_OVER — only broadcasts, does NOT decide logic
    # -------------------------------------------------------------------------
    def _finish_game(self, winner_id: str, loser_id: str, reason: str) -> None:
        """Route game-over through lifecycle (idempotent) which fires the
        server's on_game_over broadcast callback exactly once."""
        engine = self.client.server.gameEngine
        # trigger_game_over sets macro_state and fires on_game_over -> broadcast
        engine.trigger_game_over(winner_id, loser_id, reason)

    # -------------------------------------------------------------------------
    # In-game PDU handler: delegates to RulesEngine, then flushes results
    # -------------------------------------------------------------------------
    def handle_rules_engine_pdu(self, pkt: dict) -> None:
        engine = self.client.server.gameEngine
        if engine.macro_state != MacroState.IN_GAME or engine.game_state is None:
            self.client._send(PDUs.make_error(400, "NOT_IN_GAME"))
            return

        # Inject lifecycle reference so RulesEngine can call trigger_game_over()
        self.rules_engine.lifecycle = engine

        result = self.rules_engine.process_action(
            engine.game_state, self.client.player_id, pkt
        )

        if result.error_pdu:
            self.client._send(result.error_pdu)
            return

        for b_pdu in result.broadcast_pdus:
            self.client.server.broadcast(b_pdu)

        self.client.server.send_game_state_to_all()

        if result.engine_signal == "ADVANCE_STEP":
            engine.advance_phase()
            self.client.server.send_game_state_to_all()

        # game_over_pending is already routed through lifecycle inside RulesEngine;
        # here we only need to broadcast the GAME_OVER PDU if it fired.
        if result.game_over_pending:
            self._finish_game(
                result.game_over_pending["winner_id"],
                result.game_over_pending["loser_id"],
                result.game_over_pending["reason"],
            )

    # -------------------------------------------------------------------------
    # CONCEDE handler — routes through lifecycle.trigger_game_over()
    # -------------------------------------------------------------------------
    def handle_concede(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error(400, "NOT_REGISTERED"))
            return
        engine = self.client.server.gameEngine
        if engine.macro_state != MacroState.IN_GAME or engine.game_state is None:
            self.client._send(PDUs.make_error(400, "NOT_IN_GAME"))
            return
        loser = self.client.player_id
        winner = engine.get_opponent(loser)
        if winner:
            # lifecycle.trigger_game_over() is idempotent; _finish_game broadcasts
            self._finish_game(winner, loser, "CONCEDE")

    # -------------------------------------------------------------------------
    # DISCONNECT handler — routes through lifecycle.trigger_game_over()
    # -------------------------------------------------------------------------
    def handle_disconnect(self, pkt: dict) -> None:
        if not self.client.player_id:
            return
        engine = self.client.server.gameEngine
        if engine.macro_state == MacroState.IN_GAME and engine.game_state is not None:
            loser = self.client.player_id
            winner = engine.get_opponent(loser)
            if winner:
                self._finish_game(winner, loser, "DISCONNECT")
        self.client.running = False

    def handle_ping(self, pkt: dict) -> None:
        self.client._send({"type": PDUs.PONG, "seq_num": pkt.get("seq_num")})

    def handle_hello(self, pkt: dict) -> None:
        name = pkt.get("name") or f"{self.client.addr}"
        # Generate unique player ID
        self.client.player_id = name
        # Register player in the lifecycle-managed lobby
        try:
            self.client.server.gameEngine.add_player(self.client.player_id)
        except RuntimeError:
            self.client._send(PDUs.make_error(400, "LOBBY_FULL"))
            self.client.running = False
            return
        self.client.server.broadcast({
            "type": PDUs.GAME_STATE_UPDATE,
            "state": self.client.server.gameEngine.get_lobby_state()
        })

        # Acknowledge registration
        try:
            self.client._send({"type": PDUs.HELLO, "player_id": self.client.player_id})
        except Exception:
            try:
                self.client.server.gameEngine.remove_player(self.client.player_id)
            except Exception:
                pass
            self.client.running = False
            return
        self.client._send({"type": PDUs.WELCOME, "message": "Welcome to MTGNP"})

    def handle_player_ready(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error(400, "NOT_REGISTERED"))
            return
        name = pkt.get("name") or f"{self.client.addr}"
        deckList = pkt.get("deck_list") or None

        # validate deck
        if not deckList or not isinstance(deckList, list):
            self.client._send(PDUs.make_error(400, "INVALID_DECK"))
            return
        for card in deckList:
            if card not in self.client.server.LEGAL_CARDS:
                self.client._send(PDUs.make_error(400, "ILLEGAL_DECK"))
                return

        # register player as ready in lifecycle and register deck
        try:
            try:
                self.client.server.gameEngine.set_ready(self.client.player_id)
            except KeyError:
                self.client._send(PDUs.make_error(400, "NOT_IN_LOBBY"))
                return

            ok, err = self.client.server.gameEngine.register_player_ready(self.client.player_id, deckList)
            if not ok:
                # if registration failed, un-ready the player
                try:
                    self.client.server.gameEngine.set_ready(self.client.player_id, False)
                except Exception:
                    pass
                self.client._send(PDUs.make_error(400, err))
                return
            self.client.server.broadcast({
                "type": PDUs.GAME_STATE_UPDATE,
                "state": self.client.server.gameEngine.get_lobby_state()
            })
        except Exception as e:
            traceback.print_exc()
            self.client._send(PDUs.make_error(400, str(e)))
            return
        
        # acknowledge
        self.client._send({"type": "PLAYER_READY_ACK"})

    def handle_mulligan_choice(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error(400, "NOT_REGISTERED"))
            return
        keep = pkt.get("keep")
        cards_to_bottom = pkt.get("cards_to_bottom", [])
        if not isinstance(keep, bool) or not isinstance(cards_to_bottom, list):
            self.client._send(PDUs.make_error(400, "INVALID_MULLIGAN_CHOICE"))
            return
        try:
            success, msg, started = self.client.server.gameEngine.process_mulligan(
                self.client.player_id,
                keep,
                cards_to_bottom
            )
        except Exception as e:
            traceback.print_exc()
            self.client._send(PDUs.make_error(400, str("ILLEGAL_ACTION")))
            return
        # acknowledge
       
        self.client._send({
        "type": PDUs.GAME_STATE_UPDATE,
        "state": self.client.server.gameEngine.get_visible_state(self.client.player_id)
        })

        if started:
            self.client.server.broadcast({
                "type": PDUs.PHASE_TRANSITION,
                "from_phase": "MULLIGAN",
                "to_phase": "UNTAP",
                "active_player": self.client.server.gameEngine.game_state.players[
                    self.client.server.gameEngine.game_state.active_player_index
                ].name,
                "turn": self.client.server.gameEngine.game_state.turn_number
            })
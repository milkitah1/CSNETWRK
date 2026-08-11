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
        # Rules state is shared by both ClientHandlers through Server.  Keeping
        # it per connection causes each player to count priority passes in a
        # separate state machine, so two passes never advance the phase.
        self.rules_engine = client.server.rules_engine
        self.handlers = {
            PDUs.PING: self.handle_ping,
            PDUs.HELLO: self.handle_hello,
            PDUs.PLAYER_READY: self.handle_player_ready,
            PDUs.MULLIGAN_CHOICE: self.handle_mulligan_choice,
            PDUs.DISCARD: self.handle_discard,
            PDUs.STATE_REQUEST: self.handle_state_request,
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
            self.client._send(PDUs.make_error("BAD_REQUEST", f"unhandled pdu type: {t}"))

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
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_IN_GAME"))
            return

        # Resolve the server's current shared engine here.  The server replaces
        # it when it starts a fresh game on the same client connections.
        rules_engine = self.client.server.rules_engine
        rules_engine.lifecycle = engine

        result = rules_engine.process_action(
            engine.game_state, self.client.player_id, pkt
        )

        if result.error_pdu:
            self.client._send(result.error_pdu)
            return

        # A PRIORITY_GRANT is a game token, not a transport sequence.  Send it
        # only after the matching state snapshot so every client renders the
        # same priority holder before it can submit an action.
        pending_grants = [
            pdu for pdu in result.broadcast_pdus
            if pdu.get("type") == PDUs.PRIORITY_GRANT
        ]
        for b_pdu in result.broadcast_pdus:
            if b_pdu.get("type") != PDUs.PRIORITY_GRANT:
                self.client.server.broadcast(b_pdu)

        if result.engine_signal == "ADVANCE_STEP":
            # The grant produced while the two passes were being counted is
            # for the completed step.  Replace it with the new phase's token.
            next_phase, game_over, grant_pdu = engine.advance_phase()

            to_phase = next_phase.value if hasattr(next_phase, "value") else str(next_phase)
            ap_name = engine.game_state.players[engine.game_state.active_player_index].name if engine.game_state else None

            # Resolve combat damage when transitioning into damage steps
            if to_phase in ("FIRST_STRIKE_DAMAGE", "COMBAT_DAMAGE"):
                is_fs = (to_phase == "FIRST_STRIKE_DAMAGE")
                res_pdu, sba_events, dmg_game_over = rules_engine.combat_mgr.resolve_combat_damage(
                    engine.game_state, is_first_strike_step=is_fs
                )
                if res_pdu:
                    self.client.server.broadcast(res_pdu)
                for sba in sba_events:
                    self.client.server.broadcast(sba)
                if dmg_game_over:
                    game_over = dmg_game_over

            # Clean up combat state when entering postcombat main or end of combat
            if to_phase in ("POSTCOMBAT_MAIN", "END_OF_COMBAT"):
                rules_engine.combat_mgr.cleanup_combat(engine.game_state)

            self.client.server.broadcast({
                "type": PDUs.PHASE_TRANSITION,
                "to_phase": to_phase,
                "active_player": ap_name,
                "turn": engine.game_state.turn_number if engine.game_state else 0,
            })

            self.client.server.send_game_state_to_all()
            # The current state's token unlocks only the named priority holder.
            if grant_pdu:
                self.client.server.broadcast(grant_pdu)
            # DECK_EMPTY detected during DRAW step advance
            if game_over:
                self._finish_game(game_over["winner_id"], game_over["loser_id"], game_over["reason"])
        else:
            self.client.server.send_game_state_to_all()
            for grant_pdu in pending_grants:
                self.client.server.broadcast(grant_pdu)

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
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_REGISTERED"))
            return
        engine = self.client.server.gameEngine
        if engine.macro_state != MacroState.IN_GAME or engine.game_state is None:
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_IN_GAME"))
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
        if engine.macro_state in (MacroState.IN_GAME, MacroState.MULLIGAN, MacroState.GAME_SETUP):
            loser = self.client.player_id
            winner = engine.get_opponent(loser)
            if winner:
                self._finish_game(winner, loser, "DISCONNECT")
            else:
                engine.reset_to_lobby()
        else:
            engine.reset_to_lobby()
        self.client.running = False

    def handle_ping(self, pkt: dict) -> None:
        self.client._send({"type": PDUs.PONG, "seq_num": pkt.get("seq_num")})

    def handle_state_request(self, pkt: dict) -> None:
        """Return an authoritative snapshot after a rejected client action."""
        engine = self.client.server.gameEngine
        if not self.client.player_id or engine.game_state is None:
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_IN_GAME"))
            return

        self.client._send({
            "type": PDUs.GAME_STATE_UPDATE,
            "seq_num": engine.game_state.seq_num if engine.game_state else 0,
            "state": engine.get_visible_state(self.client.player_id),
        })
        priority_idx = engine.game_state.priority_player_index
        if engine.macro_state == MacroState.IN_GAME and priority_idx is not None:
            self.client._send({
                "type": PDUs.PRIORITY_GRANT,
                "player_id": engine.game_state.players[priority_idx].name,
                "seq_num": engine.game_state.seq_num,
                "time_limit_ms": 30000,
            })

    def handle_hello(self, pkt: dict) -> None:
        name = pkt.get("name") or f"{self.client.addr}"

        # Don't allow more than 2 players
        if len(self.client.server.gameEngine.joined_players) >= 2:
            self.client._send(PDUs.make_error("LOBBY_FULL", "Lobby is full"))
            self.client.running = False
            return

        # Generate unique player ID
        self.client.player_id = name

        # Register player in the lifecycle-managed lobby
        try:
            self.client.server.gameEngine.add_player(self.client.player_id)
        except RuntimeError:
            self.client._send(PDUs.make_error("LOBBY_FULL", "Lobby is full"))
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
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_REGISTERED"))
            return

        # Section 6.2: the player_id is client-chosen and MUST be a non-empty string.
        claimed_id = pkt.get("player_id")
        if not isinstance(claimed_id, str) or not claimed_id.strip():
            self.client._send(PDUs.make_error("ILLEGAL_PLAYER_ID", "player_id must be a non-empty string"))
            return
        claimed_id = claimed_id.strip()

        # Section 6.2: reject a player_id already claimed by the other connected player.
        for other in list(self.client.server._clients):
            if other is self.client:
                continue
            if getattr(other, "claimed_player_id", None) == claimed_id:
                self.client._send(PDUs.make_error("DUPLICATE_ID", f"player_id '{claimed_id}' is already claimed"))
                return
        self.client.claimed_player_id = claimed_id

        # Accept either "deck_list" (RFC) or legacy "decklist" key.
        deckList = pkt.get("deck_list")
        if deckList is None:
            deckList = pkt.get("decklist")

        # validate deck
        if not deckList or not isinstance(deckList, list):
            self.client._send(PDUs.make_error("ILLEGAL_DECK", "Deck list must be a non-empty array of cards."))
            return
        for card in deckList:
            if card not in self.client.server.LEGAL_CARDS:
                self.client._send(PDUs.make_error("ILLEGAL_DECK", f"Card '{card}' is not legal."))
                return

        # register player as ready in lifecycle and register deck
        try:
            try:
                self.client.server.gameEngine.set_ready(self.client.player_id)
            except KeyError:
                self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_IN_LOBBY"))
                return

            ok, err = self.client.server.gameEngine.register_player_ready(self.client.player_id, deckList)
            if not ok:
                # if registration failed, un-ready the player
                try:
                    self.client.server.gameEngine.set_ready(self.client.player_id, False)
                except Exception:
                    pass
                self.client._send(PDUs.make_error("ILLEGAL_DECK", err))
                return
            self.client.server.broadcast({
                "type": PDUs.GAME_STATE_UPDATE,
                "state": self.client.server.gameEngine.get_lobby_state()
            })
        except Exception as e:
            traceback.print_exc()
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", str(e)))
            return
        
        # acknowledge
        self.client._send({"type": "PLAYER_READY_ACK"})

    def handle_mulligan_choice(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_REGISTERED"))
            return
        keep = pkt.get("keep")
        cards_to_bottom = pkt.get("cards_to_bottom", [])
        if not isinstance(keep, bool) or not isinstance(cards_to_bottom, list):
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "Invalid mulligan choice"))
            return
        try:
            success, msg, started = self.client.server.gameEngine.process_mulligan(
                self.client.player_id,
                keep,
                cards_to_bottom
            )
        except Exception as e:
            traceback.print_exc()
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", str(e)))
            return

        # Section 6.4: a rejected mulligan choice MUST produce ERROR ILLEGAL_ACTION
        if not success:
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", msg or "Invalid mulligan choice"))
            return

        if started:
            # start_in_game() already ran _untap_permanents() and advance_phase(),
            # so the engine is already at UPKEEP with priority granted.
            engine = self.client.server.gameEngine
            gs = engine.game_state
            ap_name = gs.players[gs.active_player_index].name if gs else None
            turn_num = gs.turn_number if gs else 0

            # Broadcast PHASE_TRANSITION to the actual first priority phase (UPKEEP, not UNTAP)
            self.client.server.broadcast({
                "type": PDUs.PHASE_TRANSITION,
                "from_phase": "MULLIGAN",
                "to_phase": gs.phase if gs else "UPKEEP",
                "active_player": ap_name,
                "turn": turn_num,
            })

            # Broadcast the current snapshot first, then the game token that
            # unlocks priority on the active player's client.
            self.client.server.send_game_state_to_all()
            priority_player_idx = gs.priority_player_index
            if priority_player_idx is not None:
                from mtgnp.engine.priority import PriorityManager
                _pm = PriorityManager()
                grant_pdu = _pm.grant_priority(gs, priority_player_idx)
                self.client.server.broadcast(grant_pdu)
        else:
            engine = self.client.server.gameEngine
            self.client._send({
                "type": PDUs.GAME_STATE_UPDATE,
                "seq_num": engine.game_state.seq_num if engine.game_state else 0,
                "state": engine.get_visible_state(self.client.player_id),
            })

    # -------------------------------------------------------------------------
    # DISCARD handler (Section 7.8 — Cleanup step)
    # -------------------------------------------------------------------------
    def handle_discard(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "NOT_REGISTERED"))
            return
        card_ids = pkt.get("card_ids")
        if not isinstance(card_ids, list):
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", "Invalid discard choice"))
            return

        engine = self.client.server.gameEngine
        ok, msg, trans = engine.process_discard(self.client.player_id, card_ids)

        # Section 7.8: a DISCARD with invalid cards MUST be rejected with
        # ERROR code ILLEGAL_ACTION.
        if not ok:
            self.client._send(PDUs.make_error("ILLEGAL_ACTION", msg or "Invalid discard"))
            return

        if trans:
            self.client.server.broadcast({
                "type": PDUs.PHASE_TRANSITION,
                "to_phase": trans["to_phase"],
                "active_player": trans["active_player"],
                "turn": trans["turn"],
            })
        self.client.server.send_game_state_to_all()
        if trans and trans.get("priority_grant"):
            self.client.server.broadcast(trans["priority_grant"])

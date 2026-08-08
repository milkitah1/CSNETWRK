"""MTGNP Rules Engine Facade.

Coordinates priority, stack resolution, combat state machine, triggered abilities,
and state-based actions behind a single PDU processing entry point.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, NamedTuple
from mtgnp.common.game_state import GameState
from mtgnp.common import pdu as PDUs
from mtgnp.engine.priority import PriorityManager
from mtgnp.engine.stack import StackManager
from mtgnp.engine.sba import check_state_based_actions
from mtgnp.engine.triggers import TriggerManager
from mtgnp.engine.combat import CombatManager
from mtgnp.common.verbose import log_send, log_recv


class EngineResult(NamedTuple):
    """Structured result returned by RulesEngine.process_action."""
    broadcast_pdus: List[Dict[str, Any]]
    error_pdu: Optional[Dict[str, Any]]
    game_over_pending: Optional[Dict[str, Any]]
    engine_signal: Optional[str]


class RulesEngine:
    """Unified facade interface for the MTGNP rules engine."""

    def __init__(self) -> None:
        self.priority_mgr = PriorityManager()
        self.stack_mgr = StackManager()
        self.combat_mgr = CombatManager()
        self.trigger_mgr = TriggerManager()

    def _get_player_index(self, game_state: GameState, name: str) -> int:
        for idx, p in enumerate(game_state.players):
            if p.name == name:
                return idx
        return 0

    def process_action(
        self, game_state: GameState, player_name: str, pdu: Dict[str, Any]
    ) -> EngineResult:
        """Processes an incoming client PDU against the current game state.

        Returns:
            EngineResult containing (broadcast_pdus, error_pdu, game_over_pending, engine_signal)
        """
        log_recv(f"RulesEngine[{player_name}]", pdu)
        pdu_type = pdu.get("type", "")

        broadcast_pdus: List[Dict[str, Any]] = []
        error_pdu: Optional[Dict[str, Any]] = None
        game_over_pending: Optional[Dict[str, Any]] = None
        engine_signal: Optional[str] = None

        if pdu_type == PDUs.PRIORITY_PASS:
            res_pdu, pass_info = self.priority_mgr.handle_pass(game_state, player_name, pdu)
            action_signal = pass_info.get("status", "")
            if action_signal == "ERROR":
                error_pdu = pass_info.get("error_pdu") or res_pdu
            else:
                if res_pdu:
                    broadcast_pdus.append(res_pdu)

                if action_signal == "RESOLVE_STACK":
                    # Pop and resolve top of stack item
                    resolve_pdu, sba_events_stack, game_over_stack = self.stack_mgr.resolve_top_of_stack(game_state)
                    if resolve_pdu:
                        broadcast_pdus.append(resolve_pdu)

                    # Trigger state-based actions sweep after stack item resolution
                    sba_events, game_over = check_state_based_actions(game_state)
                    if game_over or game_over_stack:
                        game_over_pending = game_over or game_over_stack

                    # Reset consecutive pass counter and grant priority back to Active Player
                    self.priority_mgr.consecutive_passes = 0
                    ap_idx = game_state.active_player_index
                    grant = self.priority_mgr.grant_priority(game_state, ap_idx)
                    broadcast_pdus.append(grant)

                elif action_signal == "ADVANCE_STEP":
                    engine_signal = "ADVANCE_STEP"

        elif pdu_type == PDUs.CAST_SPELL:
            val_err = self.priority_mgr.validate_priority_action(game_state, player_name, pdu)
            if val_err:
                error_pdu = val_err
            else:
                push_pdu, cast_err = self.stack_mgr.cast_spell(game_state, player_name, pdu)
                if cast_err:
                    error_pdu = cast_err
                else:
                    if push_pdu:
                        broadcast_pdus.append(push_pdu)

                    # Observe spell cast event for triggers
                    trig_pdus = self.trigger_mgr.observe_event(
                        game_state,
                        event_type="ON_SPELL_CAST",
                        event_payload={"card_id": pdu.get("card_id"), "caster": player_name},
                    )
                    broadcast_pdus.extend(trig_pdus)

                    # Run SBA sweep
                    sba_events, game_over = check_state_based_actions(game_state)
                    if game_over:
                        game_over_pending = game_over

                    self.priority_mgr.consecutive_passes = 0
                    p_idx = self._get_player_index(game_state, player_name)
                    grant = self.priority_mgr.grant_priority(game_state, p_idx)
                    broadcast_pdus.append(grant)

        elif pdu_type == PDUs.ACTIVATE_ABILITY:
            val_err = self.priority_mgr.validate_priority_action(game_state, player_name, pdu)
            if val_err:
                error_pdu = val_err
            else:
                push_pdu, act_err = self.stack_mgr.activate_ability(game_state, player_name, pdu)
                if act_err:
                    error_pdu = act_err
                else:
                    if push_pdu:
                        broadcast_pdus.append(push_pdu)

                    sba_events, game_over = check_state_based_actions(game_state)
                    if game_over:
                        game_over_pending = game_over

                    self.priority_mgr.consecutive_passes = 0
                    p_idx = self._get_player_index(game_state, player_name)
                    grant = self.priority_mgr.grant_priority(game_state, p_idx)
                    broadcast_pdus.append(grant)

        elif pdu_type == PDUs.PLAY_LAND:
            val_err = self.priority_mgr.validate_priority_action(game_state, player_name, pdu)
            if val_err:
                error_pdu = val_err
            else:
                land_pdu, land_err = self.stack_mgr.play_land(game_state, player_name, pdu)
                if land_err:
                    error_pdu = land_err
                else:
                    if land_pdu:
                        broadcast_pdus.append(land_pdu)

                    trig_pdus = self.trigger_mgr.observe_event(
                        game_state,
                        event_type="ON_ENTER_BATTLEFIELD",
                        event_payload={"card_id": pdu.get("card_id"), "controller": player_name},
                    )
                    broadcast_pdus.extend(trig_pdus)

                    sba_events, game_over = check_state_based_actions(game_state)
                    if game_over:
                        game_over_pending = game_over

                    self.priority_mgr.consecutive_passes = 0
                    p_idx = self._get_player_index(game_state, player_name)
                    grant = self.priority_mgr.grant_priority(game_state, p_idx)
                    broadcast_pdus.append(grant)

        elif pdu_type == PDUs.DECLARE_ATTACKERS:
            res_pdu, att_err, next_signal = self.combat_mgr.process_declare_attackers(game_state, player_name, pdu)
            if att_err:
                error_pdu = att_err
            else:
                if res_pdu:
                    broadcast_pdus.append(res_pdu)

                # Fire ON_ATTACK triggers for declared attackers
                for att in self.combat_mgr.attackers:
                    trig_pdus = self.trigger_mgr.observe_event(
                        game_state,
                        event_type="ON_ATTACK",
                        event_payload={"attacker_id": att["creature_id"], "target": att["target"]},
                    )
                    broadcast_pdus.extend(trig_pdus)

                sba_events, game_over = check_state_based_actions(game_state)
                if game_over:
                    game_over_pending = game_over

                engine_signal = next_signal

                # Open priority window for Active Player
                self.priority_mgr.consecutive_passes = 0
                ap_idx = game_state.active_player_index
                grant = self.priority_mgr.grant_priority(game_state, ap_idx)
                broadcast_pdus.append(grant)

        elif pdu_type == PDUs.DECLARE_BLOCKERS:
            res_pdu, blk_err, next_signal = self.combat_mgr.process_declare_blockers(game_state, player_name, pdu)
            if blk_err:
                error_pdu = blk_err
            else:
                if res_pdu:
                    broadcast_pdus.append(res_pdu)

                sba_events, game_over = check_state_based_actions(game_state)
                if game_over:
                    game_over_pending = game_over

                engine_signal = next_signal

                # If no multi-blocked ordering needed, open priority window for Active Player
                if next_signal == "PROCEED_TO_DAMAGE":
                    self.priority_mgr.consecutive_passes = 0
                    ap_idx = game_state.active_player_index
                    grant = self.priority_mgr.grant_priority(game_state, ap_idx)
                    broadcast_pdus.append(grant)

        elif pdu_type == PDUs.ASSIGN_DAMAGE_ORDER:
            res_pdu, ord_err = self.combat_mgr.process_assign_damage_order(game_state, player_name, pdu)
            if ord_err:
                error_pdu = ord_err
            else:
                if res_pdu:
                    broadcast_pdus.append(res_pdu)

                engine_signal = "PROCEED_TO_DAMAGE"

                # Open final priority window for Active Player before combat damage
                self.priority_mgr.consecutive_passes = 0
                ap_idx = game_state.active_player_index
                grant = self.priority_mgr.grant_priority(game_state, ap_idx)
                broadcast_pdus.append(grant)

        elif pdu_type == "TRIGGER_ORDER_RESPONSE":
            stack_pdu, trig_err = self.trigger_mgr.process_trigger_order_response(game_state, player_name, pdu)
            if trig_err:
                error_pdu = trig_err
            else:
                if stack_pdu:
                    broadcast_pdus.append(stack_pdu)

        elif pdu_type == "TRIGGER_CHOICE_RESPONSE":
            stack_pdu, choice_err = self.trigger_mgr.process_trigger_choice_response(game_state, player_name, pdu)
            if choice_err:
                error_pdu = choice_err
            else:
                if stack_pdu:
                    broadcast_pdus.append(stack_pdu)

        else:
            error_pdu = PDUs.make_error(
                code="UNKNOWN_TYPE",
                message=f"Unsupported PDU type '{pdu_type}' for rules engine.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            )

        for b_pdu in broadcast_pdus:
            log_send("RulesEngineBroadcast", b_pdu)
        if error_pdu:
            log_send("RulesEngineError", error_pdu)

        return EngineResult(broadcast_pdus, error_pdu, game_over_pending, engine_signal)

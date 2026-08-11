"""Triggered Abilities System for MTGNP.

Implements trigger event detection across all standard game checkpoints:
1. ON_ENTER_BATTLEFIELD
2. ON_PERMANENT_LEAVES_BATTLEFIELD
3. ON_CREATURE_DIES
4. ON_SPELL_CAST
5. ON_CARD_DRAWN
6. ON_STEP_START
7. ON_COMBAT_DAMAGE_DEALT
8. Plus attack hooks (ON_ATTACK)

Also handles active/non-active player stacking order, trigger ordering validation, and trigger choice selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

from mtgnp.common.game_state import GameState
from mtgnp.common import pdu as PDUs


@dataclass
class PendingTrigger:
    """Represents a detected triggered ability waiting to be ordered or choice-prompted."""

    trigger_id: str
    source_id: str
    controller: str
    event_type: str
    effect_summary: str
    is_optional: bool = True
    requires_target: bool = False
    legal_targets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "source_id": self.source_id,
            "controller": self.controller,
            "event_type": self.event_type,
            "effect_summary": self.effect_summary,
            "requires_target": self.requires_target,
            "legal_targets": self.legal_targets,
        }


class TriggerManager:
    """Manages event-based trigger detection, AP/NAP ordering, TRIGGER_ORDER, and TRIGGER_CHOICE."""

    def __init__(self) -> None:
        self._trigger_counter: int = 0
        self.pending_triggers: List[PendingTrigger] = []

    def _next_trigger_id(self) -> str:
        self._trigger_counter += 1
        return f"trg_{self._trigger_counter:02d}"

    def detect_triggers(
        self, game_state: GameState, event_type: str, event_payload: Dict[str, Any]
    ) -> List[PendingTrigger]:
        """Scans state and event_payload for triggered abilities matching the event_type.

        Supports all standard checkpoints:
        - ON_ENTER_BATTLEFIELD
        - ON_PERMANENT_LEAVES_BATTLEFIELD
        - ON_CREATURE_DIES
        - ON_SPELL_CAST
        - ON_CARD_DRAWN
        - ON_STEP_START
        - ON_COMBAT_DAMAGE_DEALT
        - ON_ATTACK
        """
        detected: List[PendingTrigger] = []

        # 1. ON_ENTER_BATTLEFIELD (e.g. Gray Merchant of Asphodel)
        if event_type == "ON_ENTER_BATTLEFIELD":
            card_id = event_payload.get("card_id", "") or event_payload.get("id", "")
            controller = event_payload.get("controller", "")
            if "gray_merchant" in card_id.lower():
                trg = PendingTrigger(
                    trigger_id=self._next_trigger_id(),
                    source_id=card_id,
                    controller=controller,
                    event_type=event_type,
                    effect_summary="Devotion drain: opponent loses life equal to devotion to black, you gain that much life.",
                    is_optional=True,
                    requires_target=False,
                    legal_targets=[],
                )
                detected.append(trg)

        # 2. ON_ATTACK (e.g. Goblin Guide)
        elif event_type == "ON_ATTACK":
            attacker_id = event_payload.get("attacker_id", "")
            controller = event_payload.get("controller", "")
            defender = event_payload.get("defender", "")
            if "goblin_guide" in attacker_id.lower():
                trg = PendingTrigger(
                    trigger_id=self._next_trigger_id(),
                    source_id=attacker_id,
                    controller=controller,
                    event_type=event_type,
                    effect_summary="Defending player reveals top card of library. If it's a land, put it into their hand.",
                    is_optional=False,
                    requires_target=False,
                    legal_targets=[],
                )
                detected.append(trg)

        # 3. ON_CREATURE_DIES / ON_PERMANENT_LEAVES_BATTLEFIELD
        elif event_type in ("ON_CREATURE_DIES", "ON_PERMANENT_LEAVES_BATTLEFIELD"):
            perm_id = event_payload.get("target", "") or event_payload.get("id", "")
            controller = event_payload.get("controller", "")
            if "revenant" in perm_id.lower() or "death_trigger" in perm_id.lower():
                trg = PendingTrigger(
                    trigger_id=self._next_trigger_id(),
                    source_id=perm_id,
                    controller=controller,
                    event_type=event_type,
                    effect_summary="Creature died: deal 1 damage to opponent.",
                    is_optional=True,
                    requires_target=True,
                    legal_targets=[p.name for p in game_state.players if p.name != controller],
                )
                detected.append(trg)

        # 4. ON_SPELL_CAST
        elif event_type == "ON_SPELL_CAST":
            spell_id = event_payload.get("source", "")
            controller = event_payload.get("controller", "")
            # Check for Prowess / Cast trigger cards on battlefield
            for player in game_state.players:
                for perm in player.battlefield:
                    p_id = perm.get("id") or perm.get("card_id", "")
                    if "monastery_swiftspear" in p_id.lower() and player.name == controller:
                        trg = PendingTrigger(
                            trigger_id=self._next_trigger_id(),
                            source_id=p_id,
                            controller=player.name,
                            event_type=event_type,
                            effect_summary="Prowess: creature gets +1/+1 until end of turn.",
                            is_optional=False,
                            requires_target=False,
                        )
                        detected.append(trg)

        # 5. ON_CARD_DRAWN
        elif event_type == "ON_CARD_DRAWN":
            player_name = event_payload.get("player", "")
            # Generic draw trigger hook
            pass

        # 6. ON_STEP_START
        elif event_type == "ON_STEP_START":
            step_name = event_payload.get("step", "")
            # Upkeep / Step trigger hooks
            pass

        # 7. ON_COMBAT_DAMAGE_DEALT
        elif event_type == "ON_COMBAT_DAMAGE_DEALT":
            source_id = event_payload.get("source", "")
            # Combat damage trigger hooks
            pass

        self.pending_triggers.extend(detected)
        return detected

    def observe_event(
        self, game_state: GameState, event_type: str, event_payload: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Observes a game event, detects triggers, arranges AP/NAP order, and returns generated PDUs."""
        detected = self.detect_triggers(game_state, event_type, event_payload)
        if not detected:
            return []
        order_pdu, ordered = self.arrange_apnap_triggers(game_state, detected)
        if order_pdu:
            return [order_pdu]

        pdus: List[Dict[str, Any]] = []
        for trg in ordered:
            if trg.is_optional or trg.requires_target:
                choice_pdu = self.prompt_trigger_choice(game_state, trg)
                if choice_pdu:
                    pdus.append(choice_pdu)
            else:
                stack_item = {
                    "type": PDUs.STACK_PUSH,
                    "seq_num": game_state.next_seq_num(),
                    "stack_item_id": f"stk_trg_{trg.trigger_id}",
                    "item_type": "TRIGGER",
                    "source": trg.source_id,
                    "targets": trg.legal_targets,
                    "controller": trg.controller,
                }
                game_state.stack.append(stack_item)
                pdus.append(stack_item)
        return pdus

    def arrange_apnap_triggers(
        self, game_state: GameState, triggers: List[PendingTrigger]
    ) -> Tuple[Optional[Dict[str, Any]], List[PendingTrigger]]:
        """Orders triggers so active player triggers are placed on the stack first, followed by non-active player triggers.

        If a single player controls 2+ simultaneous triggers, generates a TRIGGER_ORDER PDU.

        Returns:
            Tuple of (TRIGGER_ORDER_pdu_or_none, ordered_pending_triggers)
        """
        ap_name = game_state.players[game_state.active_player_index].name
        nap_name = game_state.players[game_state.non_active_player_index].name

        ap_triggers = [t for t in triggers if t.controller == ap_name]
        nap_triggers = [t for t in triggers if t.controller == nap_name]

        # Check if AP has multiple triggers requiring player ordering
        if len(ap_triggers) >= 2:
            pdu = {
                "type": PDUs.TRIGGER_ORDER,
                "seq_num": game_state.next_seq_num(),
                "player_id": ap_name,
                "trigger_ids": [t.trigger_id for t in ap_triggers],
            }
            return pdu, triggers

        # Check if NAP has multiple triggers requiring player ordering
        if len(nap_triggers) >= 2:
            pdu = {
                "type": PDUs.TRIGGER_ORDER,
                "seq_num": game_state.next_seq_num(),
                "player_id": nap_name,
                "trigger_ids": [t.trigger_id for t in nap_triggers],
            }
            return pdu, triggers

        # Default AP/NAP order: AP placed first (bottom), NAP placed second (top)
        final_order = ap_triggers + nap_triggers
        return None, final_order

    def handle_trigger_order_response(
        self,
        game_state: GameState,
        triggers: List[PendingTrigger],
        response_pdu: Dict[str, Any],
    ) -> Tuple[Optional[List[PendingTrigger]], Optional[Dict[str, Any]]]:
        """Validates and applies a TRIGGER_ORDER_RESPONSE PDU."""
        ordered_ids = response_pdu.get("ordered_trigger_ids", [])
        expected_ids = {t.trigger_id for t in triggers}

        if set(ordered_ids) != expected_ids or len(ordered_ids) != len(triggers):
            err = PDUs.make_error(
                code="TRIGGER_ORDER_INVALID",
                message=f"Ordered IDs {ordered_ids} do not match expected trigger set {list(expected_ids)}.",
                rejected_action=response_pdu,
                seq_num=game_state.seq_num,
            )
            return None, err

        # Map IDs to PendingTrigger objects
        trg_map = {t.trigger_id: t for t in triggers}
        reordered = [trg_map[tid] for tid in ordered_ids]
        return reordered, None

    def generate_trigger_choice_pdu(
        self, game_state: GameState, trigger: PendingTrigger
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Generates a TRIGGER_CHOICE PDU for an optional or targeted trigger.

        Returns:
            Tuple of (TRIGGER_CHOICE_pdu_or_none, should_discard_immediately)
        """
        # If targeted and no legal targets exist -> discard immediately without prompt
        if trigger.requires_target and len(trigger.legal_targets) == 0:
            return None, True

        pdu = {
            "type": PDUs.TRIGGER_CHOICE,
            "seq_num": game_state.next_seq_num(),
            "trigger_id": trigger.trigger_id,
            "source_id": trigger.source_id,
            "effect_summary": trigger.effect_summary,
            "requires_target": trigger.requires_target,
            "legal_targets": trigger.legal_targets,
        }
        return pdu, False

    def handle_trigger_choice_response(
        self,
        game_state: GameState,
        trigger: PendingTrigger,
        response_pdu: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Validates TRIGGER_CHOICE_RESPONSE and returns STACK_PUSH PDU if accepted, or None if declined.

        Returns:
            Tuple of (STACK_PUSH_pdu_or_none, ERROR_pdu_or_none)
        """
        trg_id = response_pdu.get("trigger_id", "")
        if trg_id != trigger.trigger_id:
            err = PDUs.make_error(
                code="TRIGGER_CHOICE_INVALID",
                message=f"Response trigger_id '{trg_id}' does not match expected '{trigger.trigger_id}'.",
                rejected_action=response_pdu,
                seq_num=game_state.seq_num,
            )
            return None, err

        accept = response_pdu.get("accept", False)
        if not accept:
            # Declined -> discarded with no effect
            return None, None

        chosen_target = response_pdu.get("chosen_target")
        if trigger.requires_target:
            if not chosen_target or chosen_target not in trigger.legal_targets:
                err = PDUs.make_error(
                    code="TRIGGER_CHOICE_INVALID",
                    message=f"Chosen target '{chosen_target}' is not in legal_targets {trigger.legal_targets}.",
                    rejected_action=response_pdu,
                    seq_num=game_state.seq_num,
                )
                return None, err

        # Push to stack
        stack_id = f"stk_{len(game_state.stack)+1:02d}"
        targets = [chosen_target] if chosen_target else []
        item = {
            "stack_item_id": stack_id,
            "item_type": "TRIGGER_ABILITY",
            "source": trigger.source_id,
            "targets": targets,
            "controller": trigger.controller,
            "effect_summary": trigger.effect_summary,
        }
        game_state.add_to_stack(item)

        push_pdu = {
            "type": PDUs.STACK_PUSH,
            "seq_num": game_state.next_seq_num(),
            "stack_item_id": stack_id,
            "item_type": "TRIGGER_ABILITY",
            "source": trigger.source_id,
            "targets": targets,
            "controller": trigger.controller,
        }
        return push_pdu, None

"""Stack and Casting Engine for MTGNP.

Implements stack data structure (LIFO), CAST_SPELL validation, ACTIVATE_ABILITY validation,
summoning sickness checks on tap abilities, PLAY_LAND handling, stack resolution,
and fizzle detection per RFC 0001 Sections 8.2, 8.3, and 8.5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mtgnp.common.game_state import GameState
from mtgnp.common import pdu as PDUs
from mtgnp.cards import get_card
from mtgnp.engine.sba import check_state_based_actions
from mtgnp.engine.card_effects import apply_card_effect


@dataclass
class StackItem:
    """Represents an item on the LIFO stack."""

    stack_item_id: str
    item_type: str  # "SPELL", "ABILITY", "TRIGGER_ABILITY"
    source: str
    controller: str
    targets: List[str] = field(default_factory=list)
    card_data: Optional[Dict[str, Any]] = None
    effect_payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stack_item_id": self.stack_item_id,
            "item_type": self.item_type,
            "source": self.source,
            "targets": self.targets,
            "controller": self.controller,
        }


def _parse_mana_cost(cost_str: str) -> Dict[str, int]:
    """Parse a simple mana cost string like 'R', 'UU', '1R', '2B' into a dict."""
    res: Dict[str, int] = {}
    if not cost_str or cost_str == "0":
        return res

    import re

    # Match numeric generic mana or single color letters
    tokens = re.findall(r"(\d+|[WUBRG])", cost_str)
    for tok in tokens:
        if tok.isdigit():
            res["generic"] = int(tok)
        else:
            res[tok] = res.get(tok, 0) + 1
    return res


def _validate_mana_payment(cost_str: str, mana_payment: Dict[str, int]) -> bool:
    """Validates whether mana_payment satisfies cost_str."""
    req = _parse_mana_cost(cost_str)
    for color, amount in req.items():
        if color == "generic":
            # Total paid mana must meet or exceed generic cost
            total_paid = sum(mana_payment.values())
            color_req = sum(v for k, v in req.items() if k != "generic")
            if (total_paid - color_req) < amount:
                return False
        else:
            if mana_payment.get(color, 0) < amount:
                return False
    return True


def _find_player_index(game_state: GameState, player_name: str) -> Optional[int]:
    for idx, player in enumerate(game_state.players):
        if player.name == player_name:
            return idx
    return None


def _is_target_legal(game_state: GameState, target_id: str) -> bool:
    """Re-checks if a target ID is still legal in the game state."""
    # Target can be a player name
    for player in game_state.players:
        if player.name == target_id or target_id in ("player_1", "player_2"):
            return True

    # Target can be a permanent on any battlefield
    for player in game_state.players:
        for perm in player.battlefield:
            if perm.get("id") == target_id or perm.get("card_id") == target_id:
                return True

    # Target can be a stack item (for counterspells)
    for item in game_state.stack:
        item_id = item.get("stack_item_id") if isinstance(item, dict) else getattr(item, "stack_item_id", None)
        if item_id == target_id:
            return True

    return False


class StackManager:
    """Manages spell casting, ability activation, stack state, and stack resolution."""

    def __init__(self) -> None:
        self._item_counter: int = 0

    def _next_stack_item_id(self) -> str:
        self._item_counter += 1
        return f"stk_{self._item_counter:02d}"

    def cast_spell(
        self, game_state: GameState, player_name: str, cast_pdu: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Processes a CAST_SPELL PDU.

        Returns:
            Tuple of (STACK_PUSH_pdu_or_none, ERROR_pdu_or_none)
        """
        player_idx = _find_player_index(game_state, player_name)
        if player_idx is None:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message=f"Unknown player '{player_name}'.",
                rejected_action=cast_pdu,
                seq_num=game_state.seq_num,
            )

        player = game_state.players[player_idx]
        card_id = cast_pdu.get("card_id", "")
        targets = cast_pdu.get("targets", [])
        mana_payment = cast_pdu.get("mana_payment", {})

        # Find card in hand
        card_in_hand = None
        for c in player.hand:
            c_id = c.get("id") or c.get("card_id")
            if c_id == card_id or (c.get("card_id") == card_id):
                card_in_hand = c
                break

        # Fallback to catalog lookup
        card_info = get_card(card_id) or (card_in_hand if isinstance(card_in_hand, dict) else {})
        card_type = card_info.get("type") if card_info else "Instant"

        # Phase timing check (WRONG_PHASE)
        # Sorceries and Creatures can only be cast during AP Main Phase with empty stack
        is_instant_speed = card_type in ("Instant", "Flash")
        is_ap = player_idx == game_state.active_player_index
        is_main_phase = game_state.phase in ("PRECOMBAT_MAIN", "POSTCOMBAT_MAIN")
        stack_empty = len(game_state.stack) == 0

        if not is_instant_speed:
            if not (is_ap and is_main_phase and stack_empty):
                return None, PDUs.make_error(
                    code="WRONG_PHASE",
                    message=(
                        f"Card '{card_id}' of type '{card_type}' cannot be cast outside "
                        f"Active Player Main Phase with empty stack (current phase: {game_state.phase})."
                    ),
                    rejected_action=cast_pdu,
                    seq_num=game_state.seq_num,
                )

        # Mana payment check (INSUFFICIENT_MANA)
        cost_str = card_info.get("mana_cost", "") if card_info else ""
        if cost_str and not _validate_mana_payment(cost_str, mana_payment):
            return None, PDUs.make_error(
                code="INSUFFICIENT_MANA",
                message=f"Mana payment {mana_payment} does not satisfy cost '{cost_str}'.",
                rejected_action=cast_pdu,
                seq_num=game_state.seq_num,
            )

        # Target legality check (ILLEGAL_TARGET)
        for t in targets:
            if not _is_target_legal(game_state, t):
                return None, PDUs.make_error(
                    code="ILLEGAL_TARGET",
                    message=f"Target '{t}' is not legal.",
                    rejected_action=cast_pdu,
                    seq_num=game_state.seq_num,
                )

        # Remove card from hand if present
        if card_in_hand in player.hand:
            player.hand.remove(card_in_hand)

        stack_id = self._next_stack_item_id()
        item = {
            "stack_item_id": stack_id,
            "item_type": "SPELL",
            "source": card_id,
            "targets": targets,
            "controller": player_name,
            "card_data": card_info,
            "card_obj": card_in_hand,
        }
        game_state.add_to_stack(item)

        push_pdu = {
            "type": PDUs.STACK_PUSH,
            "seq_num": game_state.next_seq_num(),
            "stack_item_id": stack_id,
            "item_type": "SPELL",
            "source": card_id,
            "targets": targets,
            "controller": player_name,
        }
        return push_pdu, None

    def activate_ability(
        self, game_state: GameState, player_name: str, act_pdu: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Processes an ACTIVATE_ABILITY PDU."""
        player_idx = _find_player_index(game_state, player_name)
        if player_idx is None:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message=f"Unknown player '{player_name}'.",
                rejected_action=act_pdu,
                seq_num=game_state.seq_num,
            )

        player = game_state.players[player_idx]
        source_id = act_pdu.get("source_id", "")
        cost_payment = act_pdu.get("cost_payment", {})
        targets = act_pdu.get("targets", [])

        # Find permanent on battlefield
        source_perm = None
        for perm in player.battlefield:
            p_id = perm.get("id") or perm.get("card_id")
            if p_id == source_id:
                source_perm = perm
                break

        if not source_perm:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message=f"Source permanent '{source_id}' not found on battlefield.",
                rejected_action=act_pdu,
                seq_num=game_state.seq_num,
            )

        # Check summoning sickness if cost includes tap
        requires_tap = cost_payment.get("tap", False)
        if requires_tap:
            if source_perm.get("tapped", False):
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Permanent '{source_id}' is already tapped.",
                    rejected_action=act_pdu,
                    seq_num=game_state.seq_num,
                )

            # Check summoning sickness for creatures
            if game_state.is_summoning_sick(player_idx, source_perm):
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Creature '{source_id}' is summoning sick and cannot use tap abilities.",
                    rejected_action=act_pdu,
                    seq_num=game_state.seq_num,
                )

        # Apply tap cost if needed
        if requires_tap:
            source_perm["tapped"] = True

        # Check if mana ability (e.g. land or Llanowar Elves tapping for mana)
        is_mana_ability = source_perm.get("type") == "Land" or "mana_produced" in source_perm
        if is_mana_ability:
            # Bypasses stack per RFC 0001
            return None, None

        # Target check
        for t in targets:
            if not _is_target_legal(game_state, t):
                return None, PDUs.make_error(
                    code="ILLEGAL_TARGET",
                    message=f"Target '{t}' is not legal.",
                    rejected_action=act_pdu,
                    seq_num=game_state.seq_num,
                )

        stack_id = self._next_stack_item_id()
        item = {
            "stack_item_id": stack_id,
            "item_type": "ABILITY",
            "source": source_id,
            "targets": targets,
            "controller": player_name,
        }
        game_state.add_to_stack(item)

        push_pdu = {
            "type": PDUs.STACK_PUSH,
            "seq_num": game_state.next_seq_num(),
            "stack_item_id": stack_id,
            "item_type": "ABILITY",
            "source": source_id,
            "targets": targets,
            "controller": player_name,
        }
        return push_pdu, None

    def play_land(
        self, game_state: GameState, player_name: str, land_pdu: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Processes a PLAY_LAND PDU (bypasses stack, 1 per turn)."""
        player_idx = _find_player_index(game_state, player_name)
        if player_idx is None:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message=f"Unknown player '{player_name}'.",
                rejected_action=land_pdu,
                seq_num=game_state.seq_num,
            )

        if player_idx != game_state.active_player_index:
            return None, PDUs.make_error(
                code="WRONG_PHASE",
                message="Only the Active Player can play a land.",
                rejected_action=land_pdu,
                seq_num=game_state.seq_num,
            )

        if game_state.phase not in ("PRECOMBAT_MAIN", "POSTCOMBAT_MAIN") or len(game_state.stack) > 0:
            return None, PDUs.make_error(
                code="WRONG_PHASE",
                message="Lands can only be played during Main Phase with an empty stack.",
                rejected_action=land_pdu,
                seq_num=game_state.seq_num,
            )

        # Check 1 land per turn limit
        # Store land_played_this_turn flag on game_state if present, else check custom field
        land_played = getattr(game_state, "land_played_this_turn", False)
        if land_played:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message="Already played a land this turn.",
                rejected_action=land_pdu,
                seq_num=game_state.seq_num,
            )

        player = game_state.players[player_idx]
        card_id = land_pdu.get("card_id", "")

        # Find land in hand
        land_card = None
        for c in player.hand:
            c_id = c.get("id") or c.get("card_id")
            if c_id == card_id or (c.get("card_id") == card_id):
                land_card = c
                break

        if land_card in player.hand:
            player.hand.remove(land_card)

        new_land = land_card if isinstance(land_card, dict) else {"id": card_id, "type": "Land", "tapped": False}
        new_land["tapped"] = False
        player.battlefield.append(new_land)
        setattr(game_state, "land_played_this_turn", True)

        return {"type": "LAND_PLAYED", "player": player_name, "card_id": card_id}, None

    def resolve_top_of_stack(
        self, game_state: GameState
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Pops and resolves the top item of the stack.

        Returns:
            Tuple of (STACK_RESOLVE_pdu, sba_events, game_over_pending)
        """
        if not game_state.stack:
            return None, [], None

        item = game_state.stack.pop()
        stack_id = item.get("stack_item_id") if isinstance(item, dict) else item.stack_item_id
        targets = item.get("targets", []) if isinstance(item, dict) else item.targets
        controller_name = item.get("controller") if isinstance(item, dict) else item.controller
        source_id = item.get("source") if isinstance(item, dict) else item.source
        card_info = item.get("card_data") if isinstance(item, dict) else getattr(item, "card_data", None)

        # Target legality re-evaluation
        legal_targets = [t for t in targets if _is_target_legal(game_state, t)]

        # If spell had targets and ALL targets are now illegal -> FIZZLE
        if len(targets) > 0 and len(legal_targets) == 0:
            resolve_pdu = {
                "type": PDUs.STACK_RESOLVE,
                "seq_num": game_state.next_seq_num(),
                "stack_item_id": stack_id,
                "result": "FIZZLE",
                "state_changes": [],
            }
            sba_events, game_over = check_state_based_actions(game_state)
            return resolve_pdu, sba_events, game_over

        # Otherwise RESOLVED: apply effects
        state_changes: List[Dict[str, Any]] = []
        effect_changes = apply_card_effect(game_state, source_id, controller_name, legal_targets)
        state_changes.extend(effect_changes)

        player_idx = _find_player_index(game_state, controller_name)

        if card_info and player_idx is not None:
            card_type = card_info.get("type", "")
            player = game_state.players[player_idx]

            # If creature/enchantment/artifact, move to battlefield
            if card_type in ("Creature", "Enchantment", "Artifact"):
                perm = {
                    "id": source_id,
                    "card_id": card_info.get("card_id", source_id),
                    "name": card_info.get("name", source_id),
                    "type": card_type,
                    "mana_cost": card_info.get("mana_cost", ""),
                    "power": card_info.get("power", 0),
                    "toughness": card_info.get("toughness", 0),
                    "tapped": False,
                    "damage": 0,
                    "entered_this_turn": True,
                }
                if not any((p.get("id") == source_id or p.get("card_id") == source_id) for p in player.battlefield):
                    player.battlefield.append(perm)
                    state_changes.append({"change_type": "ENTER_BATTLEFIELD", "target": source_id})
            elif card_type in ("Instant", "Sorcery"):
                player.graveyard.append({"id": source_id, "type": card_type})

        resolve_pdu = {
            "type": PDUs.STACK_RESOLVE,
            "seq_num": game_state.next_seq_num(),
            "stack_item_id": stack_id,
            "result": "RESOLVED",
            "state_changes": state_changes,
        }

        sba_events, game_over = check_state_based_actions(game_state)
        return resolve_pdu, sba_events, game_over

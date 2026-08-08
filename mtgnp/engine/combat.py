"""Combat Sub-State Machine for MTGNP.

Implements all 7 combat sub-steps
1. BEGIN_COMBAT 
2. DECLARE_ATTACKERS 
3. DECLARE_BLOCKERS
4. ASSIGN_DAMAGE_ORDER 
5. FIRST_STRIKE_DAMAGE 
6. COMBAT_DAMAGE 
7. END_OF_COMBAT 
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
from mtgnp.common.game_state import GameState
from mtgnp.common import pdu as PDUs
from mtgnp.engine.sba import check_state_based_actions


class CombatManager:
    """Manages combat declarations, blocker constraints, damage assignment orders, first-strike exclusion, and combat damage resolution."""

    def __init__(self) -> None:
        self.attackers: List[Dict[str, str]] = []  # [{"creature_id": "...", "target": "..."}]
        self.blockers: List[Dict[str, str]] = []  # [{"creature_id": "...", "blocking_id": "..."}]
        self.damage_orders: Dict[str, List[str]] = {}  # attacker_id -> [blocker_id_1, blocker_id_2]
        self.first_strike_dealt: Set[str] = set()  # creature IDs that dealt damage in first strike step

    def reset_combat_state(self) -> None:
        """Cleans up internal combat tracking data structures."""
        self.attackers.clear()
        self.blockers.clear()
        self.damage_orders.clear()
        self.first_strike_dealt.clear()

    def process_declare_attackers(
        self, game_state: GameState, player_name: str, pdu: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        """Processes DECLARE_ATTACKERS PDU

        Returns:
            Tuple of (success_pdu_or_none, error_pdu_or_none, next_action_string)
        """
        # Validate sequence number (STALE_ACTION check)
        if pdu.get("seq_num") != game_state.seq_num:
            return None, PDUs.make_error(
                code="STALE_ACTION",
                message=f"Action seq_num {pdu.get('seq_num')} does not match current state seq_num {game_state.seq_num}.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            ), "ERROR"

        ap_idx = game_state.active_player_index
        ap_player = game_state.players[ap_idx]

        if player_name != ap_player.name:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message="Only the Active Player can declare attackers.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            ), "ERROR"

        attackers_list = pdu.get("attackers", [])
        if not isinstance(attackers_list, list):
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message="Field 'attackers' must be a list.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            ), "ERROR"

        # Empty attackers list is legal (no attack) -> skip directly to End of Combat
        if len(attackers_list) == 0:
            self.reset_combat_state()
            return {"type": "ATTACKERS_DECLARED", "count": 0}, None, "SKIP_TO_END_OF_COMBAT"

        # Validate each declared attacker
        validated_attackers: List[Dict[str, str]] = []
        for att in attackers_list:
            c_id = att.get("creature_id", "")
            target = att.get("target", "")

            # Find creature on AP battlefield
            perm = None
            for p in ap_player.battlefield:
                p_id = p.get("id") or p.get("card_id")
                if p_id == c_id:
                    perm = p
                    break

            if not perm:
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Attacker '{c_id}' not found on battlefield.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            if perm.get("tapped", False):
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Tapped creature '{c_id}' cannot attack.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            if game_state.is_summoning_sick(ap_idx, perm):
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Summoning sick creature '{c_id}' cannot attack unless it has Haste.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            # Extension: Standard MTG Defender keyword check
            abilities = perm.get("abilities_summary", [])
            if any("defender" in str(ab).lower() for ab in abilities):
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Creature '{c_id}' with Defender cannot attack.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            validated_attackers.append({"creature_id": c_id, "target": target})

        # Apply attack declaration: tap attackers and set flags
        for att in validated_attackers:
            c_id = att["creature_id"]
            for p in ap_player.battlefield:
                p_id = p.get("id") or p.get("card_id")
                if p_id == c_id:
                    p["tapped"] = True
                    p["attacking"] = True
                    p["attack_target"] = att["target"]

        self.attackers = validated_attackers
        return {"type": "ATTACKERS_DECLARED", "count": len(self.attackers)}, None, "PROCEED_TO_BLOCKERS"

    def process_declare_blockers(
        self, game_state: GameState, player_name: str, pdu: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        """Processes DECLARE_BLOCKERS PDU.

        Returns:
            Tuple of (success_pdu_or_none, error_pdu_or_none, next_action_string)
        """
        # Validate sequence number (STALE_ACTION check)
        if pdu.get("seq_num") != game_state.seq_num:
            return None, PDUs.make_error(
                code="STALE_ACTION",
                message=f"Action seq_num {pdu.get('seq_num')} does not match current state seq_num {game_state.seq_num}.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            ), "ERROR"

        nap_idx = game_state.non_active_player_index
        nap_player = game_state.players[nap_idx]

        if player_name != nap_player.name:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message="Only the defending player (Non-Active Player) can declare blockers.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            ), "ERROR"

        blockers_list = pdu.get("blockers", [])
        if not isinstance(blockers_list, list):
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message="Field 'blockers' must be a list.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            ), "ERROR"

        # Check per-blocker limit: each blocker creature can block at most 1 attacker
        seen_blockers: Set[str] = set()
        validated_blockers: List[Dict[str, str]] = []

        ap_player = game_state.players[game_state.active_player_index]
        attacking_ids = {a["creature_id"] for a in self.attackers}

        for blk in blockers_list:
            c_id = blk.get("creature_id", "")
            b_id = blk.get("blocking_id", "")

            if c_id in seen_blockers:
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Blocker '{c_id}' cannot block multiple attackers.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"
            seen_blockers.add(c_id)

            # Find blocker creature on NAP battlefield
            perm = None
            for p in nap_player.battlefield:
                p_id = p.get("id") or p.get("card_id")
                if p_id == c_id:
                    perm = p
                    break

            if not perm:
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Blocker '{c_id}' not found on battlefield.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            # Tapped blocker validation
            if perm.get("tapped", False):
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Tapped creature '{c_id}' cannot block.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            if b_id not in attacking_ids:
                return None, PDUs.make_error(
                    code="ILLEGAL_ACTION",
                    message=f"Target '{b_id}' is not an attacking creature.",
                    rejected_action=pdu,
                    seq_num=game_state.seq_num,
                ), "ERROR"

            validated_blockers.append({"creature_id": c_id, "blocking_id": b_id})

        # Apply block declaration
        for blk in validated_blockers:
            c_id = blk["creature_id"]
            for p in nap_player.battlefield:
                p_id = p.get("id") or p.get("card_id")
                if p_id == c_id:
                    p["blocking"] = blk["blocking_id"]

        self.blockers = validated_blockers

        # Check if any attacker is multiply-blocked (>= 2 blockers)
        blocker_counts: Dict[str, int] = {}
        for blk in self.blockers:
            b_id = blk["blocking_id"]
            blocker_counts[b_id] = blocker_counts.get(b_id, 0) + 1

        needs_order = any(count >= 2 for count in blocker_counts.values())
        if needs_order:
            return {"type": "BLOCKERS_DECLARED", "count": len(self.blockers)}, None, "AWAIT_DAMAGE_ORDER"
        else:
            return {"type": "BLOCKERS_DECLARED", "count": len(self.blockers)}, None, "PROCEED_TO_DAMAGE"

    def process_assign_damage_order(
        self, game_state: GameState, player_name: str, pdu: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Processes ASSIGN_DAMAGE_ORDER PDU."""
        # Validate sequence number (STALE_ACTION check)
        if pdu.get("seq_num") != game_state.seq_num:
            return None, PDUs.make_error(
                code="STALE_ACTION",
                message=f"Action seq_num {pdu.get('seq_num')} does not match current state seq_num {game_state.seq_num}.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            )

        ap_idx = game_state.active_player_index
        ap_player = game_state.players[ap_idx]

        if player_name != ap_player.name:
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message="Only the Active Player can assign damage order.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            )

        att_id = pdu.get("attacker_id", "")
        order = pdu.get("blocker_order", [])

        # Find actual blockers assigned to this attacker
        assigned_blockers = [b["creature_id"] for b in self.blockers if b["blocking_id"] == att_id]
        if set(order) != set(assigned_blockers) or len(order) != len(assigned_blockers):
            return None, PDUs.make_error(
                code="ILLEGAL_ACTION",
                message=f"Blocker order {order} does not match assigned blockers {assigned_blockers}.",
                rejected_action=pdu,
                seq_num=game_state.seq_num,
            )

        self.damage_orders[att_id] = list(order)
        return {"type": "DAMAGE_ORDER_ASSIGNED", "attacker_id": att_id, "order": order}, None

    def resolve_combat_damage(
        self, game_state: GameState, is_first_strike_step: bool = False
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Calculates simultaneous combat damage, generates COMBAT_DAMAGE_RESULT, and runs SBAs.

        Includes first-strike damage exclusion in regular damage step.
        """
        ap_idx = game_state.active_player_index
        nap_idx = game_state.non_active_player_index

        ap_player = game_state.players[ap_idx]
        nap_player = game_state.players[nap_idx]

        damage_events: List[Dict[str, Any]] = []

        # Map blockers to attackers
        attackers_map = {a["creature_id"]: a for a in self.attackers}

        # Find battlefield objects
        ap_creatures = { (p.get("id") or p.get("card_id")): p for p in ap_player.battlefield }
        nap_creatures = { (p.get("id") or p.get("card_id")): p for p in nap_player.battlefield }

        # Group blockers by attacker ID
        blockers_by_attacker: Dict[str, List[str]] = {}
        for blk in self.blockers:
            b_id = blk["blocking_id"]
            c_id = blk["creature_id"]
            if b_id not in blockers_by_attacker:
                blockers_by_attacker[b_id] = []
            blockers_by_attacker[b_id].append(c_id)

        # Process each attacker
        for att_id, att_info in attackers_map.items():
            att_perm = ap_creatures.get(att_id)
            if not att_perm:
                continue

            att_abilities = [str(a).lower() for a in att_perm.get("abilities_summary", [])]
            has_fs = any("first strike" in a for a in att_abilities)
            has_ds = any("double strike" in a for a in att_abilities)

            # First strike step filtering
            if is_first_strike_step:
                if not (has_fs or has_ds):
                    continue
                self.first_strike_dealt.add(att_id)

            # Regular damage step filtering (exclusion rule):
            # Exclude creatures with first strike (that lack double strike) that already dealt damage in FS step
            elif not is_first_strike_step:
                if has_fs and not has_ds and att_id in self.first_strike_dealt:
                    continue

            power = att_perm.get("power", 0)
            assigned_blks = blockers_by_attacker.get(att_id, [])

            if len(assigned_blks) == 0:
                # Unblocked attacker deals damage equal to power directly to defending player
                if power > 0:
                    nap_player.life -= power
                    damage_events.append({
                        "source": att_id,
                        "target": nap_player.name,
                        "amount": power,
                    })
            else:
                # Blocked attacker deals damage to blockers in assigned order
                order = self.damage_orders.get(att_id, assigned_blks)
                remaining_power = power

                for blk_id in order:
                    blk_perm = nap_creatures.get(blk_id)
                    if not blk_perm or remaining_power <= 0:
                        break

                    blk_toughness = blk_perm.get("toughness", 1)
                    blk_damage_needed = max(blk_toughness - blk_perm.get("damage", 0), 1)

                    dmg_to_assign = min(remaining_power, blk_damage_needed)
                    blk_perm["damage"] = blk_perm.get("damage", 0) + dmg_to_assign
                    remaining_power -= dmg_to_assign

                    damage_events.append({
                        "source": att_id,
                        "target": blk_id,
                        "amount": dmg_to_assign,
                    })

        # Process each blocker dealing damage to attacker
        for blk in self.blockers:
            blk_id = blk["creature_id"]
            att_id = blk["blocking_id"]

            blk_perm = nap_creatures.get(blk_id)
            att_perm = ap_creatures.get(att_id)

            if not blk_perm or not att_perm:
                continue

            blk_abilities = [str(a).lower() for a in blk_perm.get("abilities_summary", [])]
            has_fs = any("first strike" in a for a in blk_abilities)
            has_ds = any("double strike" in a for a in blk_abilities)

            if is_first_strike_step:
                if not (has_fs or has_ds):
                    continue
                self.first_strike_dealt.add(blk_id)
            elif not is_first_strike_step:
                if has_fs and not has_ds and blk_id in self.first_strike_dealt:
                    continue

            power = blk_perm.get("power", 0)
            if power > 0:
                att_perm["damage"] = att_perm.get("damage", 0) + power
                damage_events.append({
                    "source": blk_id,
                    "target": att_id,
                    "amount": power,
                })

        # Run State-Based Action sweep
        sba_events, game_over = check_state_based_actions(game_state)

        result_pdu = {
            "type": PDUs.COMBAT_DAMAGE_RESULT,
            "seq_num": game_state.next_seq_num(),
            "damage_events": damage_events,
            "life_totals": {
                game_state.players[0].name: game_state.players[0].life,
                game_state.players[1].name: game_state.players[1].life,
            },
            "creatures_died": [
                e["target"] for e in sba_events
                if e.get("event_type") == "CREATURE_DESTROYED" or e.get("change_type") == "DESTROY"
            ],
        }

        return result_pdu, sba_events, game_over

    def cleanup_combat(self, game_state: GameState) -> None:
        """Clears combat flags (attacking, blocking) from all permanents at End of Combat."""
        for player in game_state.players:
            for perm in player.battlefield:
                perm.pop("attacking", None)
                perm.pop("attack_target", None)
                perm.pop("blocking", None)
        self.reset_combat_state()

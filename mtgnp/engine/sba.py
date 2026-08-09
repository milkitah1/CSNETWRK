"""State-Based Actions (SBAs) Engine for MTGNP.

Implements SBA sweeps per RFC 0001 Section 8.4:
- Life <= 0 check (with mutual zero-life tiebreak rule: Active Player loses)
- Lethal creature damage (damage >= toughness) and <= 0 toughness checks
- Illegal aura attachments check
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from mtgnp.common.game_state import GameState


def check_state_based_actions(
    game_state: GameState,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Sweeps state-based actions repeatedly until no further changes occur.

    Returns:
        Tuple of (state_change_events, game_over_pending_or_none)
    """
    all_events: List[Dict[str, Any]] = []
    game_over_pending: Optional[Dict[str, Any]] = None

    state_changed = True
    while state_changed:
        state_changed = False

        # 1. Check life totals
        p0 = game_state.players[0]
        p1 = game_state.players[1]

        p0_dead = p0.life <= 0
        p1_dead = p1.life <= 0

        if p0_dead or p1_dead:
            if p0_dead and p1_dead:
                # Simultaneous zero-life: Active Player loses, Non-Active Player wins (RFC Sec 8.4)
                loser_idx = game_state.active_player_index
                winner_idx = game_state.non_active_player_index
            elif p0_dead:
                loser_idx = 0
                winner_idx = 1
            else:
                loser_idx = 1
                winner_idx = 0

            # Return a structured pending dict; caller must call trigger_game_over()
            game_over_pending = {
                "winner_id": game_state.players[winner_idx].name,
                "loser_id": game_state.players[loser_idx].name,
                "reason": "LIFE_ZERO",
            }
            # Terminal condition reached; return immediately
            break

        # 2. Check creature lethal damage & <= 0 toughness
        for player_idx, player in enumerate(game_state.players):
            to_remove: List[Dict[str, Any]] = []
            for perm in player.battlefield:
                # Check if it's a creature
                is_creature = (
                    perm.get("type") == "Creature"
                    or "toughness" in perm
                    or "power" in perm
                )
                if is_creature:
                    toughness = perm.get("toughness", 1)
                    damage = perm.get("damage", 0)
                    if toughness <= 0 or damage >= toughness:
                        to_remove.append(perm)

            for perm in to_remove:
                player.battlefield.remove(perm)
                player.graveyard.append(perm)
                card_id = perm.get("id") or perm.get("card_id", "unknown_card")
                all_events.append(
                    {
                        "event_type": "CREATURE_DESTROYED",
                        "change_type": "DESTROY",
                        "target": card_id,
                        "controller": player.name,
                        "card": perm,
                    }
                )
                state_changed = True

        # 3. Check illegal aura attachments
        # Collect all active battlefield card/permanent IDs
        all_perm_ids = set()
        for player in game_state.players:
            for perm in player.battlefield:
                p_id = perm.get("id") or perm.get("card_id")
                if p_id:
                    all_perm_ids.add(p_id)

        for player in game_state.players:
            auras_to_remove: List[Dict[str, Any]] = []
            for perm in player.battlefield:
                if perm.get("type") == "Enchantment" or "attached_to" in perm:
                    attached = perm.get("attached_to")
                    if attached and attached not in all_perm_ids:
                        auras_to_remove.append(perm)

            for aura in auras_to_remove:
                player.battlefield.remove(aura)
                player.graveyard.append(aura)
                aura_id = aura.get("id") or aura.get("card_id", "unknown_aura")
                all_events.append(
                    {
                        "event_type": "AURA_DETACHED",
                        "change_type": "GRAVEYARD",
                        "target": aura_id,
                        "controller": player.name,
                        "card": aura,
                    }
                )
                state_changed = True

    return all_events, game_over_pending

"""Card Effects Library for MTGNP.

Implements specific card resolution handlers for catalog cards:
- Direct damage (Lightning Bolt, Shock, Searing Spear, Lava Spike)
- Counterspells (Counterspell, Cancel, Negate)
- ETB Devotion Drain (Gray Merchant of Asphodel)
- Stat Buffs (Giant Growth)
- Creature Bounce (Unsummon)
- Mana Production (Basic lands, Llanowar Elves)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from mtgnp.common.game_state import GameState


def _find_player_by_id_or_name(game_state: GameState, target: str) -> Optional[int]:
    """Helper to locate a player index by name or position string ('player_1', 'player_2')."""
    if target == "player_1":
        return 0
    if target == "player_2":
        return 1

    for idx, p in enumerate(game_state.players):
        if p.name == target:
            return idx
    return None


def _find_creature_on_battlefield(game_state: GameState, target_id: str) -> Optional[Tuple[Dict[str, Any], int]]:
    """Helper to locate a creature on any player's battlefield.

    Returns (perm_dict, owner_player_index) or None.
    """
    for idx, player in enumerate(game_state.players):
        for perm in player.battlefield:
            p_id = perm.get("id") or perm.get("card_id")
            if p_id == target_id:
                return perm, idx
    return None


def calculate_devotion_to_black(game_state: GameState, player_index: int) -> int:
    """Calculates devotion to black for a player per MTG rules.

    Counts all 'B' mana symbol instances in mana costs of permanents controlled on battlefield.
    """
    player = game_state.players[player_index]
    devotion = 0
    for perm in player.battlefield:
        cost = perm.get("mana_cost", "")
        if not cost:
            # Fallback check card_id for known cards if cost not explicitly on perm
            c_id = perm.get("card_id", "")
            if "gray_merchant" in c_id:
                cost = "BB"  # Gray Merchant of Asphodel contributes BB (or 2B)
        devotion += cost.count("B")
    return max(devotion, 1)  # At least 1 for Gray Merchant itself entering battlefield


def apply_card_effect(
    game_state: GameState,
    source_id: str,
    controller_name: str,
    targets: List[str],
) -> List[Dict[str, Any]]:
    """Executes the specific card effect logic on legal targets.

    Returns:
        List of state_changes dicts describing what was modified.
    """
    state_changes: List[Dict[str, Any]] = []

    controller_idx = _find_player_by_id_or_name(game_state, controller_name)

    # Normalize source name (e.g. 'lightning_bolt_001' -> 'lightning_bolt')
    src_lower = source_id.lower()

    # 1. Direct Damage Spells
    if any(k in src_lower for k in ("lightning_bolt", "shock", "searing_spear", "lava_spike")):
        amount = 2 if "shock" in src_lower else 3

        for t in targets:
            p_idx = _find_player_by_id_or_name(game_state, t)
            if p_idx is not None:
                # Target is a player
                player = game_state.players[p_idx]
                player.life -= amount
                state_changes.append(
                    {"change_type": "DAMAGE", "target": player.name, "amount": amount}
                )
            else:
                # Target is a creature
                found = _find_creature_on_battlefield(game_state, t)
                if found:
                    perm, _ = found
                    perm["damage"] = perm.get("damage", 0) + amount
                    state_changes.append(
                        {"change_type": "DAMAGE", "target": t, "amount": amount}
                    )

    # 2. Counterspells (Counterspell, Cancel, Negate)
    elif any(k in src_lower for k in ("counterspell", "cancel", "negate")):
        for t in targets:
            # Target is a stack_item_id (e.g. 'stk_01')
            item_to_remove = None
            for item in game_state.stack:
                i_id = item.get("stack_item_id") if isinstance(item, dict) else getattr(item, "stack_item_id", None)
                if i_id == t:
                    item_to_remove = item
                    break

            if item_to_remove:
                game_state.stack.remove(item_to_remove)
                item_ctrl = item_to_remove.get("controller") if isinstance(item_to_remove, dict) else item_to_remove.controller
                c_idx = _find_player_by_id_or_name(game_state, item_ctrl)
                if c_idx is not None:
                    src = item_to_remove.get("source") if isinstance(item_to_remove, dict) else item_to_remove.source
                    game_state.players[c_idx].graveyard.append({"id": src, "type": "Spell"})
                state_changes.append({"change_type": "COUNTER", "target": t})

    # 3. Gray Merchant of Asphodel (Devotion to Black Drain)
    elif "gray_merchant" in src_lower:
        if controller_idx is not None:
            opponent_idx = 1 - controller_idx
            controller = game_state.players[controller_idx]
            opponent = game_state.players[opponent_idx]

            devotion = calculate_devotion_to_black(game_state, controller_idx)
            opponent.life -= devotion
            controller.life += devotion

            state_changes.append(
                {"change_type": "LIFE_LOSS", "target": opponent.name, "amount": devotion}
            )
            state_changes.append(
                {"change_type": "LIFE_GAIN", "target": controller.name, "amount": devotion}
            )

    # 4. Giant Growth (+3/+3 buff)
    elif "giant_growth" in src_lower:
        for t in targets:
            found = _find_creature_on_battlefield(game_state, t)
            if found:
                perm, _ = found
                perm["power"] = perm.get("power", 0) + 3
                perm["toughness"] = perm.get("toughness", 0) + 3
                state_changes.append(
                    {"change_type": "BUFF", "target": t, "power": 3, "toughness": 3}
                )

    # 5. Unsummon (Bounce creature to hand)
    elif "unsummon" in src_lower:
        for t in targets:
            found = _find_creature_on_battlefield(game_state, t)
            if found:
                perm, owner_idx = found
                game_state.players[owner_idx].battlefield.remove(perm)
                # Reset damage and temporary flags before returning to hand
                perm["damage"] = 0
                perm["tapped"] = False
                game_state.players[owner_idx].hand.append(perm)
                state_changes.append({"change_type": "BOUNCE", "target": t})

    # 6. Basic Lands & Llanowar Elves (Mana production)
    elif any(k in src_lower for k in ("mountain", "island", "swamp", "forest", "plains", "llanowar", "elvish")):
        color = "G" if ("llanowar" in src_lower or "elvish" in src_lower or "forest" in src_lower) else (
            "R" if "mountain" in src_lower else (
                "U" if "island" in src_lower else (
                    "B" if "swamp" in src_lower else "W"
                )
            )
        )
        state_changes.append({"change_type": "MANA_PRODUCED", "color": color, "amount": 1})

    return state_changes

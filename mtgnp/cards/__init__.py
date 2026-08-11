"""Card catalog package for MTGNP.

Phase 1 contains a small stubbed catalog loaded from `catalog.json`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any
from collections import defaultdict

_CATALOG: Dict[str, Any] | None = None


def load_catalog() -> Dict[str, Any]:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    p = Path(__file__).parent / "catalog.json"
    with p.open("r", encoding="utf-8") as fh:
        raw_cat = json.load(fh)

    _CATALOG = {}
    for card_id, card in raw_cat.items():
        # Cast common numeric fields strictly to int at ingestion
        for field in ["power", "toughness", "damage", "life", "generic_cost"]:
            if field in card and card[field] is not None:
                try:
                    card[field] = int(card[field])
                except (ValueError, TypeError):
                    pass
        _CATALOG[card_id] = card
    return _CATALOG

def get_card(card_id: str) -> Dict[str, Any]:
    if not card_id or not isinstance(card_id, str):
        return {}
    cat = load_catalog()
    if card_id in cat:
        return cat[card_id]
    # Check if card_id ends with or contains catalog template keys
    for k, card_dict in cat.items():
        if card_id.endswith(k) or k in card_id:
            return card_dict
    return cat.get(card_id, {})

def get_unique_cards() -> Dict[str, list[str]]:
    cards = load_catalog()
    cards_by_name = defaultdict(list)

    for card_id, card in cards.items():
        cards_by_name[card["name"]].append(card_id)

    return cards_by_name
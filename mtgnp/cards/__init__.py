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
    _CATALOG = {}
    p = Path(__file__).parent / "catalog.json"
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            _CATALOG.update(json.load(fh))

    master_p = Path(__file__).parent.parent.parent / "jsons" / "cards_list" / "master_card_list.json"
    if master_p.exists():
        try:
            with master_p.open("r", encoding="utf-8") as fh:
                master_list = json.load(fh)
                for item in master_list:
                    cid = item.get("card_id")
                    if cid and cid not in _CATALOG:
                        cost_parts = []
                        gen = int(item.get("generic", 0)) if str(item.get("generic", "0")).isdigit() else 0
                        if gen > 0:
                            cost_parts.append(str(gen))
                        for col in ("W", "U", "B", "R", "G"):
                            cnt = int(item.get(col, 0)) if str(item.get(col, "0")).isdigit() else 0
                            if cnt > 0:
                                cost_parts.append(col * cnt)
                        mana_cost = "".join(cost_parts)

                        _CATALOG[cid] = {
                            "card_id": cid,
                            "name": item.get("card_name", cid),
                            "type": item.get("card_type", ""),
                            "mana_cost": mana_cost,
                            "power": int(item.get("power", 0)) if str(item.get("power", "-")).isdigit() else 0,
                            "toughness": int(item.get("toughness", 0)) if str(item.get("toughness", "-")).isdigit() else 0,
                            "abilities_summary": [item.get("simplified_effect", "")],
                        }
        except Exception as e:
            print("CATALOG LOAD ERROR:", e)

    return _CATALOG


def get_mana_cost_for_card(card: Dict[str, Any]) -> str:
    if not card:
        return ""
    if card.get("mana_cost"):
        return card["mana_cost"]
    
    parts = []
    gen = int(card.get("generic", 0)) if str(card.get("generic", "0")).isdigit() else 0
    if gen > 0:
        parts.append(str(gen))
    for col in ("W", "U", "B", "R", "G"):
        cnt = int(card.get(col, 0)) if str(card.get(col, "0")).isdigit() else 0
        if cnt > 0:
            parts.append(col * cnt)
    if parts:
        return "".join(parts)
    
    color = card.get("color", "")
    cmc = int(card.get("CMC", 0)) if str(card.get("CMC", "0")).isdigit() else 0
    if color and color != "-":
        colored_cnt = len(color)
        generic_cnt = max(0, cmc - colored_cnt)
        prefix = str(generic_cnt) if generic_cnt > 0 else ""
        return f"{prefix}{color}"
    elif cmc > 0:
        return str(cmc)
    return ""


def get_card(card_id: str) -> Dict[str, Any]:
    cat = load_catalog()
    card = {}
    if card_id in cat:
        card = dict(cat[card_id])
    else:
        base = card_id.rsplit("_", 1)[0] if "_" in card_id else card_id
        for k, v in cat.items():
            k_base = k.rsplit("_", 1)[0] if "_" in k else k
            if k == base or k_base == base or v.get("name", "").lower() == base.replace("_", " ").lower():
                card = dict(v)
                break
    if card and "mana_cost" not in card:
        card["mana_cost"] = get_mana_cost_for_card(card)
    return card

def get_unique_cards() -> Dict[str, list[str]]:
    cards = load_catalog()
    cards_by_name = defaultdict(list)

    for card_id, card in cards.items():
        cards_by_name[card["name"]].append(card_id)

    return cards_by_name
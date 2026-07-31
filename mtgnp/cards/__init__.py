"""Card catalog package for MTGNP.

Phase 1 contains a small stubbed catalog loaded from `catalog.json`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

_CATALOG: Dict[str, Any] | None = None


def load_catalog() -> Dict[str, Any]:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    p = Path(__file__).parent / "catalog.json"
    with p.open("r", encoding="utf-8") as fh:
        _CATALOG = json.load(fh)
    return _CATALOG


def get_card(card_id: str) -> Dict[str, Any]:
    cat = load_catalog()
    return cat.get(card_id)

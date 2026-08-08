"""MTGNP Rules Engine package.

Contains priority management, state-based actions, stack resolution,
card effects, triggered abilities, combat state machine, and unified RulesEngine facade.
"""
from __future__ import annotations

from mtgnp.engine.priority import PriorityManager
from mtgnp.engine.stack import StackManager, StackItem
from mtgnp.engine.sba import check_state_based_actions
from mtgnp.engine.card_effects import apply_card_effect
from mtgnp.engine.triggers import TriggerManager
from mtgnp.engine.combat import CombatManager
from mtgnp.engine.rules_engine import RulesEngine, EngineResult

__all__ = [
    "PriorityManager",
    "StackManager",
    "StackItem",
    "check_state_based_actions",
    "apply_card_effect",
    "TriggerManager",
    "CombatManager",
    "RulesEngine",
    "EngineResult",
]

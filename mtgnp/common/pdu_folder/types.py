"""
This module contains classes for all PDU types.
Used for type checking.
"""
from typing import TypedDict


class ActivateAbility(TypedDict):
    type: str
    seq_num: int
    source_id: str
    ability_index: int
    targets: list
    cost_payment: dict

class AssignDamageOrder(TypedDict):
    type: str
    seq_num: int
    attacker_id: str
    blocker_order: list

class CastSpell(TypedDict):
    type: str
    seq_num: int
    card_id: str
    targets: list
    mana_payment: dict

class CombatDamageResult(TypedDict):
    type: str
    seq_num: int
    damage_events: list[dict]
    life_totals: dict[int, int]
    creatures_died: list

class Concede(TypedDict):
    type: str
    seq_num: int
    player_id: str

class DeclareAttackers(TypedDict):
    type: str
    seq_num: int
    attackers: list[dict[str, str]]

class DeclareBlockers(TypedDict):
    type: str
    seq_num: int
    blockers: list[dict[str, str]]

class Discard(TypedDict):
    type: str
    seq_num: int
    card_ids: list[str]

class Error(TypedDict):
    type: str
    seq_num: int
    code: str
    message: str
    rejected_action: dict

class GameOver(TypedDict):
    type: str
    seq_num: int
    winner_id: str
    loser_id: str
    reason: str

class GameStateUpdate(TypedDict):
    type: str
    seq_num: int
    state: GameState

class MulliganChoice(TypedDict):
    type: str
    seq_num: int
    keep: bool
    cards_to_bottom: list

class PhaseTransition(TypedDict):
    type: str
    seq_num: int
    to_phase: str
    active_player: str
    turn: int

class Ping(TypedDict):
    type: str
    seq_num: int
    timestamp: int

class PlayLand(TypedDict):
    type: str
    seq_num: int
    card_id: str

class PlayerReady(TypedDict):
    type: str
    seq_num: int
    player_id: str
    deck_list: list[str]

class Pong(TypedDict):
    type: str
    seq_num: int
    timestamp: int

class PriorityGrant(TypedDict):
    type: str
    seq_num: int
    player_id: str
    time_limit_ms: int

class PriorityPass(TypedDict):
    type: str
    seq_num: int

class StackPush(TypedDict):
    type: str
    seq_num: int
    stack_item_id: str
    item_type: str
    source: str
    targets: list[str]
    controller: str

class StackResolve(TypedDict):
    type: str
    seq_num: int
    stack_item_id: str
    result: str
    stack_changes: list[dict[str, str, int]]

class TriggerChoice(TypedDict):
    type: str
    seq_num: int
    trigger_id: str
    source_id: str
    effect_summary: str
    requires_target: bool
    legal_targets: list

class TriggerChoiceResponse(TypedDict):
    type: str
    seq_num: int
    trigger_id: str
    accept: bool
    chosen_target: str

class TriggerOrder(TypedDict):
    type: str
    seq_num: int
    player_id: str
    trigger_ids: list[str]

class TriggerOrderResponse(TypedDict):
    type: str
    seq_num: int
    ordered_trigger_ids: list[str]


# Helper
class Stack(TypedDict):
    stack_item_id: str
    item_type: str
    source: str
    targets: list[str]
    controller: str

class GameState(TypedDict):
    turn: int
    phase: str
    players_ready: int
    waiting_for: list[str]
    active_player: str
    priority_holder: str
    life_totals: dict[str, str]
    stack: Stack
    battlefield: dict[list[dict], list[dict]]
    graveyard: dict[list, list]
    hand: dict[list, list]
    hand_counts: dict[int, int]
    library_counts: dict[int, int]
    land_played_this_turn: bool
"""Game state model for MTGNP.

This module defines a lightweight, serializable game-state structure that
captures the core concepts described in the protocol: turn ownership,
priority, stack behavior, visible state, phases, steps, and summoning sick
restrictions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlayerState:
    """State for one player in the game."""

    name: str
    life: int = 20
    library: List[Dict[str, Any]] = field(default_factory=list)
    hand: List[Dict[str, Any]] = field(default_factory=list)
    battlefield: List[Dict[str, Any]] = field(default_factory=list)
    graveyard: List[Dict[str, Any]] = field(default_factory=list)
    has_priority: bool = False
    is_active_player: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "life": self.life,
            "library": self.library,
            "hand": self.hand,
            "battlefield": self.battlefield,
            "graveyard": self.graveyard,
            "has_priority": self.has_priority,
            "is_active_player": self.is_active_player,
        }


@dataclass
class GameState:
    """Authoritative game state for the match."""

    players: List[PlayerState] = field(default_factory=list)
    turn_number: int = 1
    phase: str = "BEGINNING_PHASE"
    step: str = "UNTAP_STEP"
    active_player_index: int = 0
    non_active_player_index: int = 1
    priority_player_index: Optional[int] = None
    stack: List[Dict[str, Any]] = field(default_factory=list)
    seq_num: int = 0
    last_action_seq_num: Optional[int] = None

    def __post_init__(self) -> None:
        if len(self.players) != 2:
            raise ValueError("GameState requires exactly two players")
        if self.players:
            self.players[self.active_player_index].is_active_player = True
            self.players[self.non_active_player_index].is_active_player = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "players": [player.to_dict() for player in self.players],
            "turn_number": self.turn_number,
            "phase": self.phase,
            "step": self.step,
            "active_player_index": self.active_player_index,
            "non_active_player_index": self.non_active_player_index,
            "priority_player_index": self.priority_player_index,
            "stack": self.stack,
            "seq_num": self.seq_num,
            "last_action_seq_num": self.last_action_seq_num,
        }

    def visible_state_for(self, player_index: int) -> Dict[str, Any]:
        state = self.to_dict()
        visible_players = []
        for idx, player in enumerate(self.players):
            if idx == player_index:
                visible_players.append(player.to_dict())
            else:
                opponent = player.to_dict()
                opponent["hand"] = []
                visible_players.append(opponent)
        state["players"] = visible_players
        return state

    def next_seq_num(self) -> int:
        self.seq_num += 1
        return self.seq_num

    def grant_priority(self, player_index: int) -> None:
        for idx, player in enumerate(self.players):
            player.has_priority = idx == player_index
        self.priority_player_index = player_index

    def pass_priority(self) -> None:
        if self.priority_player_index is None:
            return
        next_player = 1 - self.priority_player_index
        self.grant_priority(next_player)

    def add_to_stack(self, item: Dict[str, Any]) -> None:
        self.stack.append(item)

    def resolve_top_of_stack(self) -> Optional[Dict[str, Any]]:
        if not self.stack:
            return None
        return self.stack.pop()

    def is_summoning_sick(self, player_index: int, card: Dict[str, Any]) -> bool:
        if card.get("entered_this_turn") and not card.get("has_haste", False):
            return True
        return False


def create_initial_state(player_one: str, player_two: str) -> GameState:
    """Create a default initial game state for a two-player match."""

    players = [
        PlayerState(name=player_one),
        PlayerState(name=player_two),
    ]
    state = GameState(players=players)
    state.grant_priority(state.active_player_index)
    return state

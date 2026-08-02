"""
common/lifecycle.py
Author: Aaron Mikael C. Enriquez (Member 2)

Match lifecycle engine for MTGNP
This module drives macro game states (LOBBY -> GAME_SETUP -> MULLIGAN -> IN_GAME -> GAME_OVER)
and turn phase transitions while mutating the GameState object.

"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Tuple, Set
import random

from .game_state import GameState, PlayerState

# Represents the macro states of the whole game session (Section 6)
class MacroState(str, Enum):
    LOBBY = "LOBBY"                     # waiting for PLAYER_READY PDU from each connected player
    GAME_SETUP = "GAME_SETUP"           # setting up the game
    MULLIGAN = "MULLIGAN"               # performing mulligans
    IN_GAME = "IN_GAME"                 # in the middle of a game
    GAME_OVER = "GAME_OVER"             # game has ended, transitions to lobby state


# Turn phase and steps in chronological order (Section 7, 9)
class TurnPhase(str, Enum):
    UNTAP = "UNTAP"
    UPKEEP = "UPKEEP"
    DRAW = "DRAW"
    PRECOMBAT_MAIN = "PRECOMBAT_MAIN"
    BEGIN_COMBAT = "BEGIN_COMBAT"
    DECLARE_ATTACKERS = "DECLARE_ATTACKERS"
    DECLARE_BLOCKERS = "DECLARE_BLOCKERS"
    ASSIGN_DAMAGE_ORDER = "ASSIGN_DAMAGE_ORDER"
    FIRST_STRIKE_DAMAGE = "FIRST_STRIKE_DAMAGE"
    COMBAT_DAMAGE = "COMBAT_DAMAGE"
    END_OF_COMBAT = "END_OF_COMBAT"
    POSTCOMBAT_MAIN = "POSTCOMBAT_MAIN"
    END_STEP = "END_STEP"
    CLEANUP = "CLEANUP"

# Main controller and state machine for the entire game session
class GameLifecycleEngine:
    def __init__(self):
        self.macro_state: MacroState = MacroState.LOBBY
        self.game_state: Optional[GameState] = None
        
        # Track player registration in lobby
        self.registered_players: Dict[str, List[str]] = {}  # player_id -> deck_list
        self.mulligan_counts: Dict[str, int] = {}           # player_id -> count
        self.mulligan_kept: Set[str] = set()                # set of players who clicked keep
        
        # Turn cycle order
        self.turn_phases: List[TurnPhase] = [
            TurnPhase.UNTAP,
            TurnPhase.UPKEEP,
            TurnPhase.DRAW,
            TurnPhase.PRECOMBAT_MAIN,
            TurnPhase.BEGIN_COMBAT,
            TurnPhase.DECLARE_ATTACKERS,
            TurnPhase.DECLARE_BLOCKERS,
            TurnPhase.ASSIGN_DAMAGE_ORDER,
            TurnPhase.COMBAT_DAMAGE,
            TurnPhase.END_OF_COMBAT,
            TurnPhase.POSTCOMBAT_MAIN,
            TurnPhase.END_STEP,
            TurnPhase.CLEANUP,
        ]
        self._phase_index: int = 0

    # -------------------------------------------------------------------------
    # 1. LOBBY & PLAYER READY HANDLING
    # -------------------------------------------------------------------------
    """
    Validates PLAYER_READY submission.
    - Deck size must be between 1 and 50 cards.
    - Player ID must be unique within the lobby session.
    """
    def register_player_ready(self, player_id: str, deck_list: List[str]) -> Tuple[bool, str]:
        if self.macro_state != MacroState.LOBBY:
            return False, "Cannot set ready outside LOBBY state."

        if not (1 <= len(deck_list) <= 50):
            return False, f"Deck contains {len(deck_list)} cards; must be between 1 and 50."

        if player_id in self.registered_players and self.registered_players[player_id] != deck_list:
            # Overwrite earlier submission in LOBBY as per Section 6.2
            self.registered_players[player_id] = deck_list
            return True, ""

        self.registered_players[player_id] = deck_list
        return True, ""

    def unregister_player(self, player_id: str) -> None:
        """Removes a player from tracking if they disconnect during LOBBY."""
        if player_id in self.registered_players:
            del self.registered_players[player_id]

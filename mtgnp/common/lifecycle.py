"""
common/lifecycle.py
Author: Aaron Mikael C. Enriquez (Member 2)



"""
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple
import random
import json

# Represents the macro states of the whole game session
class GameState(Enum):
    LOBBY = auto()                  # waiting for PLAYER_READY PDU from each connected player
    GAME_SETUP = auto()             # setting up the game
    MULLIGAN = auto()               # performing mulligans
    IN_GAME = auto()                # in the middle of a game
    GAME_OVER = auto()              # game has ended, transitions to lobby state


# Represents the phases within a turn
class TurnPhase(Enum):
    UNTAP = auto()
    UPKEEP = auto()
    DRAW = auto()
    PRECOMBAT_MAIN = auto()
    COMBAT = auto()
    POSTCOMBAT_MAIN = auto()
    END = auto()
    CLEANUP = auto()

# Tracks all indivual player state throughout a match
class PlayerSession:
    def __init__(self, player_id: str, deck_list: List[int]):
        self.player_id: str = player_id
        self.deck: List[int] = deck_list.copy()
        self.library: List[int] = []
        self.hand: List[int] = []
        self.battlefield: List[dict] = []
        self.graveyard: List[int] = []
        self.life: int = 20
        self.mulligan_count: int = 0
        self.is_ready: bool = False
        self.has_kept_hand: bool = False
        self.land_played_this_turn: bool = False

# Main controller and state machine for the entire game session
class GameLifecycleEngine:
    def __init__(self, catalog_file_path: str = "cards/catalog.json"):
        self.state: GameState = GameState.LOBBY
        self.current_phase: Optional[TurnPhase] = None
        self.turn_number: int = 0
        self.players: Dict[str, PlayerSession] = {}
        self.active_player_id: Optional[str] = None
        self.starting_player_id: Optional[str] = None
        self.catalog: dict = self._load_catalog(catalog_file_path)

    def _load_catalog(self, path: str) -> dict:
        """Helper to load the card catalog for deck validation."""
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
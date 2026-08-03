"""
common/lifecycle.py
Author: Aaron Mikael C. Enriquez (Member 2)

Game lifecycle engine for MTGNP
This module drives macro game states (LOBBY -> GAME_SETUP -> MULLIGAN -> IN_GAME -> GAME_OVER)
and turn phase transitions while mutating the canonical GameState object.

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
    # 1. LOBBY & PLAYER READY HANDLING (Section 6.2 and 6.3)
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

    # -------------------------------------------------------------------------
    # 2. GAME_SETUP (Section 6.3)
    # -------------------------------------------------------------------------
    """
    Executes setup operations
    1. Set life totals to 20.
    2. Shuffle decks.
    3. Draw initial 7-card hands.
    4. Flip coin to decide starting player.
    """
    def run_game_setup(self) -> GameState:
        self.macro_state = MacroState.GAME_SETUP
        player_ids = list(self.registered_players.keys())
        
        # Coin flip for starting player
        if random.choice([True, False]):
            p1_id, p2_id = player_ids[0], player_ids[1]
        else:
            p1_id, p2_id = player_ids[1], player_ids[0]

        # Initialize canonical PlayerStates
        p1_state = PlayerState(name=p1_id, life=20)
        p2_state = PlayerState(name=p2_id, life=20)

        # Shuffle & load library (using card strings/dicts)
        p1_deck = [{"id": cid} for cid in self.registered_players[p1_id]]
        p2_deck = [{"id": cid} for cid in self.registered_players[p2_id]]
        random.shuffle(p1_deck)
        random.shuffle(p2_deck)

        # Draw 7 cards each
        p1_state.hand = [p1_deck.pop() for _ in range(min(7, len(p1_deck)))]
        p2_state.hand = [p2_deck.pop() for _ in range(min(7, len(p2_deck)))]
        
        p1_state.library = p1_deck
        p2_state.library = p2_deck

        # Build canonical GameState
        self.game_state = GameState(
            players=[p1_state, p2_state],
            turn_number=0,  # Set to 0 during MULLIGAN; 1 when IN_GAME begins
            phase=TurnPhase.UNTAP.value,
            step=TurnPhase.UNTAP.value,
            active_player_index=0,
            non_active_player_index=1,
        )

        # Track mulligans
        self.mulligan_counts = {p1_id: 0, p2_id: 0}
        self.mulligan_kept.clear()

        # Advance to MULLIGAN
        self.macro_state = MacroState.MULLIGAN
        return self.game_state

    # -------------------------------------------------------------------------
    # 3. MULLIGAN STATE (London Mulligan Rule | Section 6.4)
    # -------------------------------------------------------------------------
    """
    Processes a MULLIGAN_CHOICE PDU.
    - If keep is False: redraws 7 new cards and increments mulligan count.
    - If keep is True: validates that len(cards_to_bottom) == mulligan_count and puts them at library bottom.
    """
    def process_mulligan(self, player_id: str, keep: bool, cards_to_bottom: List[str]) -> Tuple[bool, str]:
        if self.macro_state != MacroState.MULLIGAN:
            return False, "Not in MULLIGAN state."

        p_idx = self._get_player_index(player_id)
        if p_idx is None:
            return False, "Invalid player ID."

        p_state = self.game_state.players[p_idx]

        if not keep:
            # Redraw hand: return current hand to library, shuffle, draw 7
            p_state.library.extend(p_state.hand)
            p_state.hand.clear()
            random.shuffle(p_state.library)

            draw_count = min(7, len(p_state.library))
            p_state.hand = [p_state.library.pop() for _ in range(draw_count)]

            self.mulligan_counts[player_id] += 1
            return True, ""
        else:
            # Player keeps hand: validate cards to bottom
            required_bottom = self.mulligan_counts[player_id]
            if len(cards_to_bottom) != required_bottom:
                return False, f"Must place exactly {required_bottom} cards on bottom."

            # Check cards exist in hand
            hand_card_ids = [c["id"] for c in p_state.hand]
            for cid in cards_to_bottom:
                if cid not in hand_card_ids:
                    return False, f"Card {cid} is not in hand."
                hand_card_ids.remove(cid)

            # Move cards from hand to bottom of library
            new_hand = []
            for c in p_state.hand:
                if c["id"] in cards_to_bottom:
                    cards_to_bottom.remove(c["id"])
                    p_state.library.insert(0, c)  # Index 0 = bottom of library
                else:
                    new_hand.append(c)
            p_state.hand = new_hand

            self.mulligan_kept.add(player_id)

            # Transition to IN_GAME when both players keep
            if len(self.mulligan_kept) == 2:
                self.start_in_game()

            return True, ""

    # -------------------------------------------------------------------------
    # 4. IN_GAME & TURN/PHASE ENGINE
    # -------------------------------------------------------------------------
    """Starts the game loop (Section 6.5). Turn counter set to 1."""
    def start_in_game(self) -> None:
        self.macro_state = MacroState.IN_GAME
        self.game_state.turn_number = 1
        self._phase_index = 0
        self.game_state.phase = TurnPhase.UNTAP.value
        self.game_state.step = TurnPhase.UNTAP.value
        self.game_state.grant_priority(self.game_state.active_player_index)

    """
    Advances to the next step/phase.
    Increments turn counter & switches active player after Cleanup step.
    """
    def advance_phase(self) -> TurnPhase:
        if self.macro_state != MacroState.IN_GAME:
            return TurnPhase(self.game_state.phase)

        self._phase_index = (self._phase_index + 1) % len(self.turn_phases)
        next_phase = self.turn_phases[self._phase_index]

        # Cleanup completed -> New turn
        if next_phase == TurnPhase.UNTAP:
            self.game_state.turn_number += 1
            # Switch active player
            self.game_state.active_player_index = 1 - self.game_state.active_player_index
            self.game_state.non_active_player_index = 1 - self.game_state.active_player_index

        self.game_state.phase = next_phase.value
        self.game_state.step = next_phase.value

        # Grant priority to active player for new step
        self.game_state.grant_priority(self.game_state.active_player_index)
        return next_phase

    # -------------------------------------------------------------------------
    # 5. GAME_OVER & RESET
    # -------------------------------------------------------------------------
    """
    Checks win/loss triggers (Section 6.5):
    - Life <= 0
    - Library empty when drawing
    Returns tuple of (winner_id, loser_id, reason) if over, else None.
    """
    def check_game_over_conditions(self) -> Optional[Tuple[str, str, str]]:
        if not self.game_state or self.macro_state != MacroState.IN_GAME:
            return None

        p1, p2 = self.game_state.players[0], self.game_state.players[1]

        if p1.life <= 0 and p2.life <= 0:
            # Active player loses if simultaneous
            loser = self.game_state.players[self.game_state.active_player_index].name
            winner = self.game_state.players[self.game_state.non_active_player_index].name
            return winner, loser, "LIFE_ZERO"
        elif p1.life <= 0:
            return p2.name, p1.name, "LIFE_ZERO"
        elif p2.life <= 0:
            return p1.name, p2.name, "LIFE_ZERO"

        return None
    
    """Transitions state machine to GAME_OVER."""
    def trigger_game_over(self, winner_id: str, loser_id: str, reason: str) -> Dict[str, str]:
        self.macro_state = MacroState.GAME_OVER
        return {
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason  # LIFE_ZERO, DECK_EMPTY, CONCEDE, DISCONNECT
        }
    
    """Resets engine state to allow a new game on the same TCP connection (Section 6.6)."""
    def reset_to_lobby(self) -> None:
        self.macro_state = MacroState.LOBBY
        self.game_state = None
        self.registered_players.clear()
        self.mulligan_counts.clear()
        self.mulligan_kept.clear()
        self._phase_index = 0

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    def _get_player_index(self, player_id: str) -> Optional[int]:
        if not self.game_state:
            return None
        for idx, p in enumerate(self.game_state.players):
            if p.name == player_id:
                return idx
        return None
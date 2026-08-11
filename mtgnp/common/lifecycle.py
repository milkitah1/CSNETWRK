"""
Game lifecycle engine for MTGNP
This module drives macro game states (LOBBY -> GAME_SETUP -> MULLIGAN -> IN_GAME -> GAME_OVER)
and turn phase transitions while mutating the canonical GameState object.

"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Set
import random
import threading
from typing import Any

from .game_state import GameState, PlayerState

# Represents the macro states of the whole game session
class MacroState(str, Enum):
    LOBBY = "LOBBY"
    SETUP = "SETUP"
    GAME_SETUP = "SETUP"
    MULLIGAN = "MULLIGAN"
    IN_GAME = "IN_GAME"
    GAME_OVER = "GAME_OVER"


# Turn phase and steps in chronological order
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

# ---------------------------------------------------------------------------
# LifecycleManager — single authoritative game-over gate
# ---------------------------------------------------------------------------
class LifecycleManager:
    """Thin wrapper that prevents duplicate GAME_OVER triggers and owns the broadcast callback."""

    def __init__(self) -> None:
        self._game_over_fired = False
        self._lock = threading.Lock()
        # Injected by the server after construction
        self.on_game_over: Optional[Callable[[str, str, str], None]] = None

    def trigger_game_over(self, reason: str, winner_id: str, loser_id: str) -> bool:
        """Fire GAME_OVER exactly once. Returns True if this call was the one
        that fired it, False if it was already fired (duplicate guard)."""
        with self._lock:
            if self._game_over_fired:
                return False
            self._game_over_fired = True
        if self.on_game_over:
            self.on_game_over(winner_id, loser_id, reason)
        return True

    def reset(self) -> None:
        """Clear the fired flag so a new game can end properly."""
        with self._lock:
            self._game_over_fired = False

    @property
    def is_over(self) -> bool:
        return self._game_over_fired


# Main controller and state machine for the entire game session
class GameLifecycleEngine:
    def __init__(self, max_players: int = 2):
        self.macro_state: MacroState = MacroState.LOBBY
        self.game_state: Optional[GameState] = None

        # Lobby / player join tracking (thread-safe)
        self.max_players = int(max_players)
        self._lock = threading.Condition()
        self.joined_players: Dict[str, Dict[str, Any]] = {}  # player_id -> {"ready": bool, "meta": Any}

        # Track player registration (decks) submitted during LOBBY
        self.registered_players: Dict[str, List[str]] = {}  # player_id -> deck_list
        self.mulligan_counts: Dict[str, int] = {}           # player_id -> count
        self.mulligan_kept: Set[str] = set()                # set of players who clicked keep

        # Single authoritative game-over gate
        self.lifecycle = LifecycleManager()
        
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
            TurnPhase.FIRST_STRIKE_DAMAGE,
            TurnPhase.COMBAT_DAMAGE,
            TurnPhase.END_OF_COMBAT,
            TurnPhase.POSTCOMBAT_MAIN,
            TurnPhase.END_STEP,
            TurnPhase.CLEANUP,
        ]
        self._phase_index: int = 0

        # Phases that are fully automatic — no player holds priority.
        # UNTAP is the only step in this set per standard game rules.
        self.AUTOMATIC_STEPS: Set[str] = {TurnPhase.UNTAP.value}

        # Cleanup-step discard pending state.
        # When the active player holds more than seven cards at the Cleanup
        # step, the server awaits a DISCARD PDU before the turn can end.
        self.discard_pending: bool = False
        self.awaiting_discard_player: Optional[str] = None

    def get_lobby_state(self) -> dict:
        return {
            "phase": "LOBBY",
            "players": len(self.joined_players),
            "players_ready": len(self.registered_players),
            "waiting_for": [
                pid
                for pid, info in self.joined_players.items()
                if not info.get("ready", False)
            ]
        }

    def get_visible_state(self, player_id: str) -> dict:
        """
        Returns the game state visible to a specific player.
        Hides opponent private information such as hand contents.
        """

        if self.game_state is None:
            return {
                "phase": "LOBBY",
                "players_ready": 0,
                "waiting_for": []
            }

        player_state = None
        opponent_state = None

        # Find requesting player and opponent
        for player in self.game_state.players:
            if player.name == player_id:
                player_state = player
            else:
                opponent_state = player

        if player_state is None:
            raise ValueError("Player not found")

        state = {
            "turn": self.game_state.turn_number,
            "phase": self.macro_state.value,

            "active_player": (
                self.game_state.players[self.game_state.active_player_index].name
                if self.game_state.players
                else None
            ),

            "life_totals": {
                player_state.name: player_state.life,
                opponent_state.name: opponent_state.life
                if opponent_state else None
            },

            # Only this player's hand
            "hand": [
                card["id"] if isinstance(card, dict) else card
                for card in player_state.hand
            ],

            # Opponent hand size only
            "hand_counts": {
                opponent_state.name: len(opponent_state.hand)
                if opponent_state else 0
            },

            "library_counts": {
                player_state.name: len(player_state.library),
                opponent_state.name: len(opponent_state.library)
                if opponent_state else 0
            },

            "battlefield": {
                player_state.name: player_state.battlefield,
                opponent_state.name: opponent_state.battlefield
                if opponent_state else []
            },

            "graveyard": {
                player_state.name: player_state.graveyard,
                opponent_state.name: opponent_state.graveyard
                if opponent_state else []
            },

            "stack": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.game_state.stack]
        }

        # Only include turn phases after mulligan
        if self.macro_state == MacroState.IN_GAME:
            state["phase"] = self.game_state.phase
            state["step"] = self.game_state.step
            # Expose which player currently holds priority (None during automatic phases)
            if self.game_state.priority_player_index is not None:
                state["priority_holder"] = self.game_state.players[self.game_state.priority_player_index].name
            else:
                state["priority_holder"] = None
            state["land_played_this_turn"] = getattr(self.game_state, "land_played_this_turn", False)

        return state

    # -------------------------------------------------------------------------
    # 1. LOBBY & PLAYER READY HANDLING
    # -------------------------------------------------------------------------
    """
    Validates PLAYER_READY submission.
    - Deck size must be between 1 and 50 cards.
    - Player ID must be unique within the lobby session.
    """
    def register_player_ready(self, player_id: str, deck_list: List[str]) -> Tuple[bool, str]:
        if self.macro_state == MacroState.GAME_OVER:
            self.reset_to_lobby()

        if self.macro_state != MacroState.LOBBY:
            return False, "Cannot set ready outside LOBBY state."

        if not (1 <= len(deck_list) <= 50):
            return False, f"Deck contains {len(deck_list)} cards; must be between 1 and 50."

        if player_id in self.registered_players and self.registered_players[player_id] != deck_list:
            # Overwrite earlier submission in LOBBY
            self.registered_players[player_id] = deck_list
            return True, ""

        self.registered_players[player_id] = deck_list
        return True, ""

    def unregister_player(self, player_id: str) -> None:
        """Removes a player from tracking if they disconnect during LOBBY or game."""
        if player_id in self.registered_players:
            del self.registered_players[player_id]
        # also remove from joined / ready tracking
        with self._lock:
            if player_id in self.joined_players:
                del self.joined_players[player_id]
                self._lock.notify_all()
        self.reset_to_lobby()

    # -------------------------------------------------------------------------
    # 2. GAME_SETUP
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
        p1_deck = [{"id": f"{p1_id}_{i}_{cid}", "card_id": cid} for i, cid in enumerate(self.registered_players[p1_id])]
        p2_deck = [{"id": f"{p2_id}_{i}_{cid}", "card_id": cid} for i, cid in enumerate(self.registered_players[p2_id])]
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

        # Consume the ready flags so the same two connections must send a fresh
        # PLAYER_READY PDU before the next game can begin.
        with self._lock:
            for info in self.joined_players.values():
                info["ready"] = False

        self.discard_pending = False
        self.awaiting_discard_player = None

        # Advance to MULLIGAN
        self.macro_state = MacroState.MULLIGAN
        return self.game_state

    # -------------------------------------------------------------------------
    # Lobby methods (thread-safe)
    # -------------------------------------------------------------------------
    def add_player(self, player_id: str, meta: Optional[Any] = None) -> None:
        """Add a connected player to the lobby. Raises RuntimeError if lobby full."""
        with self._lock:
            if player_id not in self.joined_players and len(self.joined_players) >= self.max_players:
                raise RuntimeError("lobby is full")
            self.joined_players[player_id] = {"ready": False, "meta": meta}
            self._lock.notify_all()

    def remove_player(self, player_id: str) -> None:
        with self._lock:
            if player_id in self.joined_players:
                del self.joined_players[player_id]
                self._lock.notify_all()

    def set_ready(self, player_id: str, ready: bool = True) -> None:
        """Mark a player as ready/unready and notify waiters."""
        with self._lock:
            if player_id not in self.joined_players:
                raise KeyError(player_id)
            self.joined_players[player_id]["ready"] = bool(ready)
            self._lock.notify_all()

    def is_ready(self, player_id: str) -> bool:
        return bool(self.joined_players.get(player_id, {}).get("ready", False))

    def players(self) -> List[str]:
        return list(self.joined_players.keys())

    def ready_count(self) -> int:
        return sum(1 for p in self.joined_players.values() if p.get("ready"))

    def all_ready(self) -> bool:
        if len(self.joined_players) < self.max_players:
            return False
        return all(p.get("ready") for p in self.joined_players.values())

    def wait_for_all_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until the lobby has `max_players` joined and all are ready.

        Returns True if the condition was reached, False if the timeout expired first.
        """
        with self._lock:
            if self.all_ready():
                return True
            waited = self._lock.wait_for(self.all_ready, timeout=timeout)
            return bool(waited)

    # -------------------------------------------------------------------------
    # 3. MULLIGAN STATE (London Mulligan Rule)
    # -------------------------------------------------------------------------
    """
    Processes a MULLIGAN_CHOICE PDU.
    - If keep is False: redraws 7 new cards and increments mulligan count.
    - If keep is True: validates that len(cards_to_bottom) == mulligan_count and puts them at library bottom.
    """
    def process_mulligan(self, player_id: str, keep: bool, cards_to_bottom: List[str]) -> Tuple[bool, str, bool]: #second bool to check if both players kept
        if self.macro_state != MacroState.MULLIGAN:
            return False, "Not in MULLIGAN state.", False

        p_idx = self._get_player_index(player_id)
        if p_idx is None:
            return False, "Invalid player ID.", False   

        p_state = self.game_state.players[p_idx]

        if not keep:
            # Redraw hand: return current hand to library, shuffle, draw 7
            
            p_state.library.extend(p_state.hand)
            p_state.hand.clear()
            random.shuffle(p_state.library)

            draw_count = min(7, len(p_state.library))
            p_state.hand = [p_state.library.pop() for _ in range(draw_count)]

            self.mulligan_counts[player_id] += 1
            return True, "", False
        else:
            if player_id in self.mulligan_kept:
                return False, "Player has already kept their hand."
            # Player keeps hand: validate cards to bottom
            required_bottom = self.mulligan_counts[player_id]
            if len(cards_to_bottom) != required_bottom:
                return False, f"Must place exactly {required_bottom} cards on bottom.", False

            # Check cards exist in hand
            hand_card_ids = [c["id"] for c in p_state.hand]
            for cid in cards_to_bottom:
                if cid not in hand_card_ids:
                    return False, f"Card {cid} is not in hand.", False
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
                return True, "", True  # both players kept

            return True, "", False  # not both players kept

    # -------------------------------------------------------------------------
    # 4. IN_GAME & TURN/PHASE ENGINE
    # -------------------------------------------------------------------------
    def start_in_game(self) -> None:
        self.macro_state = MacroState.IN_GAME
        self.game_state.turn_number = 1
        self._phase_index = 0
        self.game_state.phase = TurnPhase.UNTAP.value
        self.game_state.step = TurnPhase.UNTAP.value
        # UNTAP is automatic — immediately advance past it to UPKEEP (which grants priority)
        self._untap_permanents()
        # advance_phase() will move us to UPKEEP and return the PRIORITY_GRANT; discard the tuple
        self.advance_phase()

    """
    Advances to the next step/phase.
    Increments turn counter & switches active player after Cleanup step.
    Returns (next_phase, game_over_dict_or_None, priority_grant_pdu_or_None).
    """
    def advance_phase(self) -> Tuple[TurnPhase, Optional[Dict[str, str]], Optional[Dict[str, Any]]]:
        if self.macro_state != MacroState.IN_GAME:
            return TurnPhase(self.game_state.phase), None, None

        self._phase_index = (self._phase_index + 1) % len(self.turn_phases)
        next_phase = self.turn_phases[self._phase_index]

        # Cleanup completed -> start the next player's turn
        # UNTAP is fully automatic: we skip through it immediately and
        # return the UPKEEP phase + its PRIORITY_GRANT to the caller,
        # so the caller broadcasts PHASE_TRANSITION -> UPKEEP (not UNTAP).
        if next_phase == TurnPhase.UNTAP:
            final_phase, game_over, priority_grant_pdu = self._begin_next_turn()
            return final_phase, game_over, priority_grant_pdu

        self.game_state.phase = next_phase.value
        self.game_state.step = next_phase.value

        # Entering CLEANUP. If the active player holds more than
        # seven cards they MUST discard down to seven before the turn can end.
        # We pause here (no priority is granted) and await a DISCARD PDU.
        if next_phase == TurnPhase.CLEANUP:
            ap = self.game_state.players[self.game_state.active_player_index]
            if len(ap.hand) > 7:
                self.discard_pending = True
                self.awaiting_discard_player = ap.name
                return next_phase, None, None

        # DRAW step: draw one card for the active player.
        # Skip draw on turn 1 (first player does not draw on their first turn).
        # If library is empty when a draw is required -> DECK_EMPTY loss.
        if next_phase == TurnPhase.DRAW:
            ap_idx = self.game_state.active_player_index
            ap = self.game_state.players[ap_idx]
            opponent = self.game_state.players[1 - ap_idx]
            if self.game_state.turn_number > 1 or ap_idx != 0:
                # Draw is required
                if len(ap.library) == 0:
                    # Active player cannot draw -> they lose
                    return next_phase, {
                        "winner_id": opponent.name,
                        "loser_id": ap.name,
                        "reason": "DECK_EMPTY",
                    }, None
                ap.hand.append(ap.library.pop())

        # A new priority window needs a new token.  Reusing the token from the
        # prior step lets an old action be replayed after a phase transition.
        self.game_state.grant_priority(self.game_state.active_player_index)
        self.game_state.next_seq_num()
        grant_pdu = {
            "type": "PRIORITY_GRANT",
            "player_id": self.game_state.players[self.game_state.active_player_index].name,
            "seq_num": self.game_state.seq_num,
            "time_limit_ms": 30000,
        }
        return next_phase, None, grant_pdu

    def _untap_permanents(self) -> None:
        """Untap all permanents controlled by the active player."""
        if self.game_state is None:
            return
        ap = self.game_state.players[self.game_state.active_player_index]
        for perm in ap.battlefield:
            perm["tapped"] = False
            perm.pop("entered_this_turn", None)  # clear summoning sickness flag

    def _begin_next_turn(self) -> Tuple[TurnPhase, Optional[Dict[str, str]], Optional[Dict[str, Any]]]:
        """Start the next player's turn: increment the turn
        counter, switch the active player, run untap actions automatically,
        then advance to UPKEEP.
        Returns (final_phase, game_over, priority_grant_pdu) from advance_phase(UPKEEP)."""
        self._clear_cleanup_effects()
        self.game_state.turn_number += 1
        # Switch active player
        self.game_state.active_player_index = 1 - self.game_state.active_player_index
        self.game_state.non_active_player_index = 1 - self.game_state.active_player_index
        for idx, player in enumerate(self.game_state.players):
            player.is_active_player = idx == self.game_state.active_player_index
        self.game_state.phase = TurnPhase.UNTAP.value
        self.game_state.step = TurnPhase.UNTAP.value
        self.discard_pending = False
        self.awaiting_discard_player = None
        # Run untap automatically, then advance to UPKEEP (which grants priority)
        self._untap_permanents()
        return self.advance_phase()

    def _clear_cleanup_effects(self) -> None:
        """Remove all damage from creatures and clear any
        'until end of turn' markers after a successful cleanup discard."""
        for player in self.game_state.players:
            for perm in player.battlefield:
                perm.pop("damage", None)
                perm.pop("_until_end_of_turn", None)

    def process_discard(self, player_id: str, card_ids: List[str]) -> Tuple[bool, str, Dict[str, str]]:
        """Validate and apply a DISCARD PDU during the CLEANUP step.

        Returns (ok, error_msg, phase_transition). phase_transition is non-empty
        (pointing to the next turn's UNTAP) only once the hand is at seven or
        fewer cards, at which point the server immediately begins the next turn.
        """
        if self.macro_state != MacroState.IN_GAME or self.game_state is None:
            return False, "Not in IN_GAME state.", {}
        if not self.discard_pending or self.game_state.phase != TurnPhase.CLEANUP.value:
            return False, "No discard is required at this time.", {}
        if player_id != self.awaiting_discard_player:
            return False, "Only the active player may discard at cleanup.", {}

        p_state = self.game_state.players[self.game_state.active_player_index]
        hand_ids = [c["id"] if isinstance(c, dict) else c for c in p_state.hand]

        # Every requested card must be currently in hand
        for cid in card_ids:
            if cid not in hand_ids:
                return False, f"Card {cid} is not in the active player's hand.", {}
            hand_ids.remove(cid)

        # Player may only discard down to seven, never below
        max_discard = max(0, len(p_state.hand) - 7)
        if len(card_ids) > max_discard:
            return False, f"May only discard down to seven cards (at most {max_discard}).", {}

        # Move discarded cards to the graveyard
        for cid in card_ids:
            for c in list(p_state.hand):
                card_id = c["id"] if isinstance(c, dict) else c
                if card_id == cid:
                    p_state.hand.remove(c)
                    p_state.graveyard.append(c)
                    break

        if len(p_state.hand) > 7:
            return True, "", {}  # still over seven — await another DISCARD PDU

        # Hand is now at seven or fewer -> finish cleanup and start next turn.
        # Use advance_phase() so the UNTAP wrap is handled exactly once (it
        # routes through _begin_next_turn internally); calling _begin_next_turn
        # directly would double-increment the turn counter.
        self._clear_cleanup_effects()
        next_phase, game_over, priority_grant_pdu = self.advance_phase()
        return True, "", {
            "to_phase": next_phase.value,
            "turn": self.game_state.turn_number,
            "active_player": self.game_state.players[self.game_state.active_player_index].name,
            "priority_grant": priority_grant_pdu,
            "game_over": game_over,
        }

    # -------------------------------------------------------------------------
    # 5. GAME_OVER & RESET
    # -------------------------------------------------------------------------
    """
    Checks win/loss triggers:
    - Life <= 0
    - Library empty when drawing
    Returns tuple of (winner_id, loser_id, reason) if over, else None.
    """
    def check_game_over_conditions(self) -> Optional[Tuple[str, str, str]]:
        if not self.game_state or self.macro_state != MacroState.IN_GAME:
            return None

        p1, p2 = self.game_state.players[0], self.game_state.players[1]

        if p1.life <= 0 and p2.life <= 0:
            loser = self.game_state.players[self.game_state.active_player_index].name
            winner = self.game_state.players[self.game_state.non_active_player_index].name
            return winner, loser, "LIFE_ZERO"
        elif p1.life <= 0:
            return p2.name, p1.name, "LIFE_ZERO"
        elif p2.life <= 0:
            return p1.name, p2.name, "LIFE_ZERO"

        # DECK_EMPTY: active player has no library and is in DRAW step
        if self.game_state.phase == TurnPhase.DRAW.value:
            ap = self.game_state.players[self.game_state.active_player_index]
            opp = self.game_state.players[self.game_state.non_active_player_index]
            if len(ap.library) == 0:
                return opp.name, ap.name, "DECK_EMPTY"

        return None
    
    """Transitions state machine to GAME_OVER."""
    def trigger_game_over(self, winner_id: str, loser_id: str, reason: str) -> Dict[str, str]:
        self.macro_state = MacroState.GAME_OVER
        # Also fire through LifecycleManager (idempotent)
        self.lifecycle.trigger_game_over(reason, winner_id, loser_id)
        return {
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason  # LIFE_ZERO, DECK_EMPTY, CONCEDE, DISCONNECT
        }
    
        """Resets engine state to allow a new game on the same TCP connection."""
    def reset_to_lobby(self) -> None:
        self.macro_state = MacroState.LOBBY
        self.game_state = None
        self.registered_players.clear()
        self.mulligan_counts.clear()
        self.mulligan_kept.clear()
        self.discard_pending = False
        self.awaiting_discard_player = None
        self._phase_index = 0

        # Keep the existing TCP-connected players in the lobby.
        # They only need to submit fresh PLAYER_READY PDUs for the rematch.
        with self._lock:
            for info in self.joined_players.values():
                info["ready"] = False
            self._lock.notify_all()

        self.lifecycle.reset()  # allow next game to fire GAME_OVER again

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    def get_opponent(self, player_id: str) -> Optional[str]:
        """Return the opponent's player_id, or None if game_state is absent."""
        if not self.game_state:
            return None
        for p in self.game_state.players:
            if p.name != player_id:
                return p.name
        return None

    def _get_player_index(self, player_id: str) -> Optional[int]:
        if not self.game_state:
            return None
        for idx, p in enumerate(self.game_state.players):
            if p.name == player_id:
                return idx
        return None

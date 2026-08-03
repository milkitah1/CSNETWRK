"""Priority State Machine for MTGNP Rules Engine.

Implements PRIORITY_GRANT, PRIORITY_PASS, sequence number (priority token)
validation, consecutive pass tracking, and step/stack triggers per RFC 0001 Section 8.1.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
from mtgnp.common.game_state import GameState
from mtgnp.common import pdu as PDUs


class PriorityManager:
    """Manages priority token assignment, pass sequences, and validation."""

    def __init__(self) -> None:
        self.consecutive_passes: int = 0

    def grant_priority(
        self, game_state: GameState, player_index: int, time_limit_ms: int = 30000
    ) -> Dict[str, Any]:
        """Grants priority to the specified player and issues a PRIORITY_GRANT PDU."""
        if not (0 <= player_index < len(game_state.players)):
            raise ValueError(f"Invalid player index: {player_index}")

        game_state.grant_priority(player_index)
        seq_num = game_state.next_seq_num()

        pdu = {
            "type": PDUs.PRIORITY_GRANT,
            "player_id": game_state.players[player_index].name,
            "seq_num": seq_num,
            "time_limit_ms": time_limit_ms,
        }
        return pdu

    def validate_priority_action(
        self, game_state: GameState, player_name: str, action_pdu: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Validates priority holding and seq_num match.

        Returns an ERROR PDU dict if validation fails, or None if valid.
        """
        # Find player index by name
        player_index: Optional[int] = None
        for idx, player in enumerate(game_state.players):
            if player.name == player_name:
                player_index = idx
                break

        if player_index is None or game_state.priority_player_index != player_index:
            return PDUs.make_error(
                code="NOT_YOUR_PRIORITY",
                message=f"Action sent by '{player_name}' while not holding priority.",
                rejected_action=action_pdu,
                seq_num=game_state.seq_num,
            )

        client_seq_num = action_pdu.get("seq_num")
        if client_seq_num != game_state.seq_num:
            return PDUs.make_error(
                code="STALE_ACTION",
                message=(
                    f"Action seq_num {client_seq_num} does not match current "
                    f"priority token {game_state.seq_num}."
                ),
                rejected_action=action_pdu,
                seq_num=game_state.seq_num,
            )

        return None

    def reset_passes(self) -> None:
        """Resets the consecutive pass counter (e.g. after spell cast or ability activation)."""
        self.consecutive_passes = 0

    def handle_pass(
        self,
        game_state: GameState,
        player_name: str,
        pass_pdu: Dict[str, Any],
        time_limit_ms: int = 30000,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Handles a PRIORITY_PASS PDU from a player.

        Returns:
            Tuple of (pdu_response, result_info) where result_info contains:
            - status: "CONTINUE", "RESOLVE_STACK", "ADVANCE_STEP", or "ERROR"
        """
        err = self.validate_priority_action(game_state, player_name, pass_pdu)
        if err is not None:
            return err, {"status": "ERROR"}

        self.consecutive_passes += 1
        current_holder = game_state.priority_player_index
        assert current_holder is not None

        if self.consecutive_passes >= 2:
            self.consecutive_passes = 0
            # Two consecutive passes
            if len(game_state.stack) > 0:
                # Top item resolves; AP gets priority next
                grant_pdu = self.grant_priority(
                    game_state, game_state.active_player_index, time_limit_ms
                )
                return grant_pdu, {"status": "RESOLVE_STACK"}
            else:
                # Stack empty; step/phase ends
                grant_pdu = self.grant_priority(
                    game_state, game_state.active_player_index, time_limit_ms
                )
                return grant_pdu, {"status": "ADVANCE_STEP"}
        else:
            # First pass; pass priority to the opponent
            next_holder = 1 - current_holder
            grant_pdu = self.grant_priority(game_state, next_holder, time_limit_ms)
            return grant_pdu, {"status": "CONTINUE"}

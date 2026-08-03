"""PDU type constants and helpers for MTGNP.

This module centralizes PDU type strings used throughout the project and
provides a helper for generating ERROR PDUs.

Seq_num rules (summary):
- `seq_num` is required for PDUs that create or change priority-bearing actions.
- `seq_num` monotonicity and validation are enforced at the server's validator.

"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Core PDUs (as specified in RFC)
PING = "PING"
PONG = "PONG"
HELLO = "HELLO"
WELCOME = "WELCOME"
JOIN = "JOIN"
START_GAME = "START_GAME"
GAME_STATE_UPDATE = "GAME_STATE_UPDATE"
ACTION_REQUEST = "ACTION_REQUEST"
ACTION_RESPONSE = "ACTION_RESPONSE"
ERROR = "ERROR"
KEEP_ALIVE = "KEEP_ALIVE"
PRIORITY_PASS = "PRIORITY_PASS"
PRIORITY_GRANT = "PRIORITY_GRANT"
TRIGGER_ORDER = "TRIGGER_ORDER"
TRIGGER_CHOICE = "TRIGGER_CHOICE"
TRIGGER_RESOLVE = "TRIGGER_RESOLVE"
SBAS = "SBAS"
STEP_CHANGE = "STEP_CHANGE"
TURN_CHANGE = "TURN_CHANGE"
CHAT = "CHAT"
CONCEDE = "CONCEDE"
CONNECT = "CONNECT"
RECONNECT = "RECONNECT"
DISCONNECT = "DISCONNECT"
STATE_REQUEST = "STATE_REQUEST"
STATE_RESPONSE = "STATE_RESPONSE"
PLAYER_READY = "PLAYER_READY"


def make_error(code: Any, message: str, rejected_action: Optional[Dict[str, Any]] = None, seq_num: Optional[int] = None) -> Dict[str, Any]:
    pdu: Dict[str, Any] = {
        "type": ERROR,
        "code": code,
        "message": message,
    }
    if rejected_action is not None:
        pdu["rejected_action"] = rejected_action
    if seq_num is not None:
        pdu["seq_num"] = int(seq_num)
    return pdu

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .common import pdu as PDUs

#function when client receives pdu
class ClientErrorHandler:
    """Client-side ERROR dispatcher.

    Responsibilities:
    - Map incoming PDUs to handler methods
    - Update `client` state (player_id, ready, start_game) where appropriate
    - Forward PDUs to the client's receive queue by default
    - Allow registering simple callbacks for specific PDU types
    """

    def __init__(self, client: Any) -> None:
        self.client = client
        self._callbacks: Dict[str, Callable[[dict], None]] = {}
        self.handlers = {
            "LOBBY_FULL": self._handle_lobby_full,
        }

    def _handle_lobby_full(self, pkt: dict) -> None:
        print("Lobby is full. Cannot join the game.")

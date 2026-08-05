from __future__ import annotations

from typing import Any

from .common import pdu as PDUs


class PDUHandler:
    """Class-based PDU dispatcher for a single client handler instance.

    Dispatches PDUs via a mapping of PDU type -> bound method, matching the
    pattern requested by the user.
    """

    def __init__(self, client: Any) -> None:
        self.client = client
        self.handlers = {
            PDUs.PING: self.handle_ping,
            PDUs.HELLO: self.handle_hello,
            PDUs.PLAYER_READY: self.handle_player_ready,
        }

    def handle_pdu(self, pkt: dict) -> None:
        t = pkt.get("type")
        handler = self.handlers.get(t)
        if handler is None:
            self.client._send(PDUs.make_error(400, f"unhandled pdu type: {t}"))
            return
        handler(pkt)

    def handle_ping(self, pkt: dict) -> None:
        self.client._send({"type": PDUs.PONG})

    def handle_hello(self, pkt: dict) -> None:
        name = pkt.get("name") or f"{self.client.addr}"
        self.client.player_id = str(name)

        try:
            self.client._send({"type": PDUs.HELLO, "player_id": self.client.player_id})
        except RuntimeError:
            # lobby full
            self.client._send(PDUs.make_error(400, "LOBBY_FULL"))
            self.client.running = False
            return
        self.client._send({"type": PDUs.WELCOME, "message": "Welcome to MTGNP"})

    def handle_player_ready(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error(400, "NOT_REGISTERED"))
            return
        name = pkt.get("name") or f"{self.client.addr}"
        deckList = pkt.get("decklist") or None

        self.client.server.gameEngine.register_player_ready(self.client.player_id, deckList)

        # acknowledge
        self.client._send({"type": "PLAYER_READY_ACK", "name": name, "decklist": deckList})

from __future__ import annotations
import traceback
from typing import Any
import uuid
from .common import pdu as PDUs

#handler for the clienhandler class from the server
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
        # Generate unique player ID
        self.client.player_id = str(uuid.uuid4())
        # Register player in the lifecycle-managed lobby
        try:
            self.client.server.gameEngine.add_player(self.client.player_id)
        except RuntimeError:
            self.client._send(PDUs.make_error(400, "LOBBY_FULL"))
            self.client.running = False
            return
        self.client.server.broadcast({
            "type": PDUs.GAME_STATE_UPDATE,
            "state": self.client.server.gameEngine.get_visible_state()
        })

        # Acknowledge registration
        try:
            self.client._send({"type": PDUs.HELLO, "player_id": self.client.player_id})
        except Exception:
            try:
                self.client.server.gameEngine.remove_player(self.client.player_id)
            except Exception:
                pass
            self.client.running = False
            return
        self.client._send({"type": PDUs.WELCOME, "message": "Welcome to MTGNP"})

    def handle_player_ready(self, pkt: dict) -> None:
        if not self.client.player_id:
            self.client._send(PDUs.make_error(400, "NOT_REGISTERED"))
            return
        name = pkt.get("name") or f"{self.client.addr}"
        deckList = pkt.get("decklist") or None

        # validate deck
        if not deckList or not isinstance(deckList, list):
            self.client._send(PDUs.make_error(400, "INVALID_DECK"))
            return

        # register player as ready in lifecycle and register deck
        try:
            try:
                self.client.server.gameEngine.set_ready(self.client.player_id)
            except KeyError:
                self.client._send(PDUs.make_error(400, "NOT_IN_LOBBY"))
                return

            ok, err = self.client.server.gameEngine.register_player_ready(self.client.player_id, deckList)
            if not ok:
                # if registration failed, un-ready the player
                try:
                    self.client.server.gameEngine.set_ready(self.client.player_id, False)
                except Exception:
                    pass
                self.client._send(PDUs.make_error(400, err))
                return
            self.client.server.broadcast({
                "type": PDUs.GAME_STATE_UPDATE,
                "state": self.client.server.gameEngine.get_visible_state()
            })
        except Exception as e:
            traceback.print_exc()
            self.client._send(PDUs.make_error(400, str(e)))
            return
        
        # acknowledge
        self.client._send({"type": "PLAYER_READY_ACK"})

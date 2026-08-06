from __future__ import annotations

from typing import Optional
import time
import queue

from ..common import pdu as PDUs


class LobbyState:
    """Encapsulates the interactive lobby UI and behavior.

    This class exposes a `run` method that implements the previous
    `Client.interactive_lobby` loop against a supplied `client` instance.
    It reads/upates fields populated by `ClientPDUHandler` and uses
    `client.send_pdu` for outgoing PDUs.
    """

    def __init__(self, client: "Client") -> None:
        self.client = client

    def run(self, name: str = "player") -> None:
        try:
            welcome = self.client.hello(name)
            print("Connected to MTGNP Server")

            name = welcome.get("player_id", name)

            decklist = None

            while True:
                # drain any queued PDUs (they've already been handled by handler)
                while True:
                    try:
                        pkt = self.client._recv_q.get_nowait()
                    except queue.Empty:
                        break
                    t = pkt.get("type")
                    if t == PDUs.START_GAME:
                        print("\n==> START_GAME received — game starting")
                        self.client._start_game = True
                    elif t == PDUs.PLAYER_READY:
                        self.client.players_count = pkt.get("players", self.client.players_count)
                    elif t == "PLAYER_READY_ACK":
                        self.client._ready = True
                    elif t == PDUs.ERROR:
                        print(f"ERROR from server: {pkt.get('message')}")

                if self.client._start_game:
                    break

                # render lobby UI
                print("\n========== LOBBY ==========\n")
                print(f"Players: {self.client.players_count} / {self.client.pdu_handler.client._start_game and 2 or 2}\n")
                print(f"You are {'ready' if self.client._ready else 'not ready'}.\n")
                if not self.client._ready:
                    print("1. Ready")
                print("2. Load deck")
                print("q. Quit")

                choice = input("Select: ").strip().lower()
                if choice == "1" and not self.client._ready:
                    try:
                        if not decklist:
                            raise RuntimeError("No deck loaded")
                        
                        self.client.send_pdu({"type": PDUs.PLAYER_READY, "decklist": decklist, "player_id": self.client.player_id})
                    except Exception as e:
                        print(f"failed to send PLAYER_READY: {e}")
                elif choice == "2":
                    deck_file = input("Enter deck filename: ").strip()
                    try:
                        decklist = self.client.load_deck(deck_file)
                        print(f"Loaded deck with {len(decklist)} cards.")
                    except Exception as e:
                        print(f"failed to load deck: {e}")
                elif choice == "q":
                    break
                elif self.client._start_game:
                    break
                else:
                    time.sleep(0.1)

           
        finally:
            print()

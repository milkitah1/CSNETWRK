"""CLI mulligan decision state machine for MTGNP.

Handles initial hand evaluation, keep vs. mulligan decisions, and card selection to place on bottom of library.
"""
from typing import TYPE_CHECKING
import queue
import time

if TYPE_CHECKING:
    from ..client import Client

from ..common import pdu as PDUs


class MulliganState:

    def __init__(self, client: "Client"):
        self.client = client
        self.submitted = False

    def run(self):
        """
        Handles player mulligan decisions.
        """

        while True:

            # Process incoming PDUs first
            while True:
                try:
                    pkt = self.client._recv_q.get_nowait()
                except queue.Empty:
                    break

                t = pkt.get("type")

                if t == PDUs.PHASE_TRANSITION:
                    if (
                        pkt.get("from_phase") == "MULLIGAN"
                        and pkt.get("to_phase") == "UNTAP"
                    ):
                        print("\n==> MULLIGAN phase ended — game starting")
                        return

                elif t == PDUs.GAME_OVER:
                    # Game ended during mulligan (e.g. disconnect)
                    return

                elif t == PDUs.GAME_STATE_UPDATE:
                    self.client.game_state = pkt.get("state")

            # If we already chose, wait for opponent
            if self.submitted:
                print("\nWaiting for opponent...")
                time.sleep(1)
                continue

            time.sleep(1)

            state = self.client.game_state

            print("\n========== MULLIGAN ==========")

            print("\nYour hand:")
            for i, card in enumerate(state["hand"], start=1):
                print(f"{i}. {card}")

            print("\n1. Keep hand")
            print("2. Mulligan")

            choice = input("Select: ").strip()

            if choice == "1":
                self.keep_hand()

            elif choice == "2":
                self.take_mulligan()

            else:
                print("Invalid choice")


    def keep_hand(self):
        state = self.client.game_state
        mulligan_count = self.client.mulligan_count

        cards_to_bottom = []

        if mulligan_count > 0:
            print(
                f"\nChoose {mulligan_count} card(s) to put on the bottom."
            )

            while len(cards_to_bottom) < mulligan_count:
                choice = int(input("Card number: ")) - 1

                if choice < 0 or choice >= len(state["hand"]):
                    print("Invalid card.")
                    continue

                card = state["hand"][choice]

                if card in cards_to_bottom:
                    print("Already selected.")
                    continue

                cards_to_bottom.append(card)

        self.client.send_pdu({
            "type": PDUs.MULLIGAN_CHOICE,
            "keep": True,
            "cards_to_bottom": cards_to_bottom
        })

        # Important: prevent showing menu again
        self.submitted = True


    def take_mulligan(self):
        """
        Send MULLIGAN_CHOICE keep=false.
        Server redraws and sends GAME_STATE_UPDATE.
        """

        self.client.mulligan_count += 1

        self.client.send_pdu({
            "type": PDUs.MULLIGAN_CHOICE,
            "keep": False,
            "cards_to_bottom": []
        })

        # Still waiting for new hand
        self.submitted = False
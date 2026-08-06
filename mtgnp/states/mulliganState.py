from ..common import pdu as PDUs


class MulliganState:

    def __init__(self, client):
        self.client = client

    def run(self):
        """
        Handles player mulligan decisions.
        """

        while True:
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
                break

            elif choice == "2":
                self.take_mulligan()

            else:
                print("Invalid choice")

    def keep_hand(self):
        """
        Send MULLIGAN_CHOICE keep=true.

        If mulligan_count > 0, player must choose cards
        to put on bottom.
        """

        mulligan_count = self.client.mulligan_count

        cards_to_bottom = []

        if mulligan_count > 0:
            cards_to_bottom = self.choose_bottom_cards(
                mulligan_count
            )

        self.client.send_pdu({
            "type": PDUs.MULLIGAN_CHOICE,
            "seq_num": self.client.last_game_state_seq,
            "keep": True,
            "cards_to_bottom": cards_to_bottom
        })


    def take_mulligan(self):
        """
        Send MULLIGAN_CHOICE keep=false.
        Server will redraw and send GAME_STATE_UPDATE.
        """

        self.client.mulligan_count += 1

        self.client.send_pdu({
            "type": PDUs.MULLIGAN_CHOICE,
            "seq_num": self.client.last_game_state_seq,
            "keep": False,
            "cards_to_bottom": []
        })


    def choose_bottom_cards(self, count):
        """
        London mulligan:
        after keeping, choose N cards to put bottom.
        """

        hand = self.client.game_state["player"]["hand"]

        print(
            f"\nChoose {count} card(s) to put on bottom:"
        )

        for i, card in enumerate(hand, start=1):
            print(f"{i}. {card}")

        selected = []

        while len(selected) < count:
            choice = int(
                input("Card number: ")
            )

            selected.append(
                hand[choice - 1]
            )

        return selected
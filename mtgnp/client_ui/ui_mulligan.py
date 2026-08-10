from mtgnp.client_ui.ui_helper import * 
from mtgnp.client_ui.ui_lobby import CardDetailDisplay 
import time
class MulliganState:
    def __init__(
            self,  client
        ):
        self.client = client
        self.window_height = (PAGE_SIZE + PADDING)
        self.mulligan_count = 0
        self.does_keep = False
        self.bottomed_indices: set[int] = set()
        self.bottomed_cards = []
        self.selected_index = 0
    
        # Dimensions and Coordinates for the hand display and detail window
        window_width1 = PAGE_WIDTH + PADDING*2
        window_width2 = 23 + PADDING*2
        start_y1 = 2
        start_x1 = center_something_global(window_width1 + window_width2 + 5) # center 2 windows, add 5 padding
        start_x2 = start_x1 + window_width1 + 5

        # Create WINDOWS that displays cards, details, and selection
        self.hand_window = curses.newwin(self.window_height, window_width1, start_y1, start_x1)
        self.details_window = CardDetailDisplay(self.window_height, window_width2, start_y1, start_x2)


    def init_hand_mulligan(self):
         #wait for the game state to have a hand before proceeding
        self.hand_window.border(*MENU_BORDER_CHARS)
        
        self.hand_window.addstr(1, 2, "Mulligan Counter:")
        self.hand_window.addstr(2, 2, f"{self.mulligan_count}")
        self.hand_window.addstr(3, 2, "=================================")
        self.hand_window.addstr(4, 2, "Your cards: ")
        self.hand_window.addstr(self.window_height - 4, 2, "=================================")
        self.hand_window.addstr(self.window_height - 3, 2, "Keep or Mulligan?")
        self.hand_window.addstr(self.window_height - 2, 2, "[Y/N]")

    def init_hand_bottom(self):
        self.hand_window.erase()
        self.hand_window.border(*MENU_BORDER_CHARS)
                
        self.hand_window.addstr(1, 2, "Cards to Bottom:")
        self.hand_window.addstr(2, 2, f"{self.mulligan_count - len(self.bottomed_indices)}")
        self.hand_window.addstr(3, 2, "=================================")
        self.hand_window.addstr(4, 2, "Your cards: ")
        self.hand_window.addstr(self.window_height - 4, 2, "=================================")
        self.hand_window.addstr(self.window_height - 3, 2, "Bottom a card [+/-]")
        self.hand_window.addstr(self.window_height - 2, 2, "Press Esc to finish")

    def display_card_detail(self):
        card_id = self.hand[self.selected_index]
        self.details_window.display_card_details(card_id)
        self.hand_window.refresh()

    def render_hand(self):
        row = 6
        self.wait_for_hand()
        hand = self.client.game_state.get("hand")
        # Redraw cards
        for i, card in enumerate(hand):
            attr = curses.A_NORMAL

            if i in self.bottomed_indices:
                attr |= curses.color_pair(1)

            if i == self.selected_index:
                attr |= curses.A_REVERSE

            self.hand_window.addstr(
                row + i,
                2,
                card,
                attr
            )
        self.hand_window.refresh()


    def handle_key_mulligan(self, key):
        key = normalize_key(key)

        # Move selection
        if key == curses.KEY_UP:
            if self.selected_index > 0:
                self.selected_index -= 1

        elif key == curses.KEY_DOWN:
            if self.selected_index < len(self.hand) - 1:
                self.selected_index += 1


        # Keep
        elif key == (ord("y")):
            self.does_keep = True

        # Mulligan
        elif key == (ord("n")):
            self.does_keep = False
            self.mulligan_count += 1

        self.render_hand()
        self.display_card_detail()


    def handle_key_bottom(self, key):
        curses.start_color()
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)

        # Move selection
        if key == curses.KEY_UP:
            if self.selected_index > 0:
                self.selected_index -= 1

        elif key == curses.KEY_DOWN:
            if self.selected_index < len(self.hand) - 1:
                self.selected_index += 1

        
        # 
        elif key == ord("+"):
            if self.selected_index not in self.bottomed_indices:
                if len(self.bottomed_indices) < self.mulligan_count:
                    self.bottomed_indices.add(self.selected_index)
                    self.hand_window.addstr(2, 2, f"{self.mulligan_count - len(self.bottomed_indices)}")

        # Un-bottom TODO: include some error handling 
        elif key == ord("-"):
            if self.selected_index in self.bottomed_indices:
                self.bottomed_indices.remove(self.selected_index)
                self.hand_window.addstr(2, 2, f"{self.mulligan_count - len(self.bottomed_indices)}")

        self.render_hand()
        self.display_card_detail()


    def bottom_cards(self) -> list[str]:
        self.init_hand_bottom()
        self.display_card_detail()

        key = ""
        self.hand_window.keypad(True)

        while True:
            self.render_hand()

            key = self.hand_window.getch()
            self.handle_key_bottom(key)

            if len(self.bottomed_indices) == self.mulligan_count and key == 27:
                break

        self.hand_window.keypad(False)
        self.bottomed_cards = [self.hand[i] for i in self.bottomed_indices]
        

    def keep_or_mulligan(self):
    # Wait until the server sends the player's hand
        self.wait_for_hand()

        self.init_hand_mulligan()
        self.display_card_detail()

        key = ""
        self.hand_window.keypad(True)

        while key not in (ord("y"), ord("n")):
            self.render_hand()

            key = self.hand_window.getch()
            self.handle_key_mulligan(key)

        self.hand_window.keypad(False)

        return self.does_keep
   
    def wait_for_hand(self):
        while True:
            game_state = self.client.game_state

            if game_state and "hand" in game_state:
                self.hand = game_state["hand"]
                return

            # Don't busy-loop at 100% CPU
            time.sleep(0.05)

        


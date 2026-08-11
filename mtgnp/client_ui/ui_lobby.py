import curses
import textwrap
from typing import Dict
from collections import Counter
from mtgnp.client_ui.ui_helper import * 
from mtgnp.cards import get_unique_cards, get_card

from mtgnp.common import pdu as PDUs

def lobby_get_name(stdscr):
    # Clear whole screen
    stdscr.clear()
    stdscr.refresh()

    # Ask for name and let user see their input
    stdscr.addstr("What is your name?\n")
    curses.echo()
    playername = stdscr.getstr(13).decode("utf-8")
    curses.noecho()

    stdscr.clear()
    stdscr.refresh()
    return playername

class CardListDisplay:
    def __init__(self, wheight, wwidth, starty, startx, page_size, page_width):
        self.cards_window = curses.newwin(wheight, wwidth, starty, startx)
        self.unique_cards: Dict[str, list[str]] = get_unique_cards()
        self.card_names = list(self.unique_cards.keys())
        self.page_size = page_size
        self.text_width = page_width
        self.page_start = 0
        
        self.selected_index = 0
        self.start_x = startx
        self.start_y = starty
        self.page_width = page_width

    def get_card_copies(self, name: str) -> int:
        return len(self.unique_cards[name])

    def print_cards_list(self):
        self.cards_window.erase()
        self.cards_window.border(*MENU_BORDER_CHARS)

        page_end = min(self.page_start + self.page_size, len(self.unique_cards))

        for row, card_index in enumerate(range(self.page_start, page_end)):
            name = self.card_names[card_index]
    
            remaining = self.get_card_copies(name) # get how many of current card is left
    
            attr = curses.A_REVERSE if card_index == self.selected_index else curses.A_NORMAL
            
            self.cards_window.addstr(row + 1, 2, f"{name}: {remaining} left", attr)
        self.cards_window.refresh()

    def navigate_cards_list(self, key):
        if key == curses.KEY_UP:
            if self.selected_index > self.page_start:
                self.selected_index -= 1
        
        elif key == curses.KEY_DOWN:
            if self.selected_index < min(self.page_start + self.page_size - 1, len(self.unique_cards) - 1):
                self.selected_index += 1
    
        elif key == curses.KEY_LEFT:
            if self.page_start >= self.page_size:
                self.page_start -= self.page_size
                self.selected_index = self.page_start
    
        elif key == curses.KEY_RIGHT:
            if self.page_start + self.page_size < len(self.unique_cards):
                self.page_start += self.page_size
                self.selected_index = self.page_start

    def get_highlighted_card_id(self) -> str | None:
        """Returns the details of lowest index card from unique cards list.
        Note: Make sure to check if None, None is returned."""
        # Get name of currently highlighted
        name = self.card_names[self.selected_index]

        # Get num of copies
        card_copies = self.get_card_copies(name)
        if not card_copies:
            return None
        
        card_id = self.unique_cards[name][0]

        return card_id
    
    def get_highlighted_name(self):
        return self.card_names[self.selected_index]
        
class CardDetailDisplay:
    def __init__(self, wheight, wwidth, starty, startx):
        self.window = curses.newwin(wheight, wwidth, starty, startx)
        self.height = wheight
        self.width = wwidth

    def get_card_details(self, card_id: str):
        """Retrieve a card based on id. Returns a list 
        of textwrapped-strings to be printed in the
        CardDetailDisplay window. 

        Note: Can reduce more useless keys by following card_id's format
        """
        card = get_card(card_id)

        details = list()

        for key, value in card.items():
            
            if key == "card_id" or key == "color":
                continue

            elif key == "name":
                name = textwrap.wrap(value, width=self.width-10) # -10 for name and padding
                details.append(f"name: {name[0]}")
                details.extend(name[1:])

            elif key == "simplified_effect":
                details.append("")
                details.append(f"{key}: ")
                effect = textwrap.wrap(value, width=self.width-4) # -4 for padding
                details += effect

            else:
                details.append(f"{key}: {value}")

        return details

    def display_card_details(self, card_id: str):
        self.window.erase()
        self.window.border(*CARD_BORDER_CHARS)

        if not card_id:
            self.window.addstr(1, 2, "No copies remaining :<")
            self.window.refresh()
            return

        details = self.get_card_details(card_id)
        for row, line in enumerate(details):
            if row+2 < self.height:
                self.window.addstr(1 + row, 2, line)


        self.window.refresh()

class SelectionWindow:
    def __init__(self, wheight, wwidth, starty, startx):
        self.window = curses.newwin(wheight, wwidth, starty, startx)
        self.height = wheight
        self.width = wwidth

        self.selected_cards: list = []

    def lookup_catalog(self, card_id):
        return get_card(card_id)["name"]

    def count_cards(self) -> int:
        return len(self.selected_cards)

    def add_card(self, card_list_window: CardListDisplay):
        # Retrieve lowest index card id
        card_id = card_list_window.get_highlighted_card_id()

        # ERROR CHECK: Return and do not add if no more card ids
        if not card_id:
            return

        # Get card name, then other cards with same name
        card = get_card(card_id)
        name = card.get("name")
        same_cards = card_list_window.unique_cards[name]

        # Remove the selected card by id, append to selected_cards
        same_cards.remove(card_id)
        self.selected_cards.append(card_id)

    def put_back_card(self, card_list_window: CardListDisplay):
        # Get the highlighted card type from the available pool
        target_name = card_list_window.get_highlighted_name()

        # Find the first selected copy with the same name
        for selected_id in self.selected_cards:
            if get_card(selected_id)["name"] == target_name:
                self.selected_cards.remove(selected_id)
                card_list_window.unique_cards[target_name].append(selected_id)
                break

    def refresh(self):
        self.window.erase()

        self.window.border(*MENU_BORDER_CHARS)

        self.window.addstr(1, 2, "Press + to add a card")
        self.window.addstr(2, 2, "Press - to put back a card")
        self.window.addstr(3, 2, "Press Esc to finish choosing")
        self.window.addstr(4, 1, "===================================")
        self.window.addstr(5, 2, f"Cards chosen: {self.count_cards()}")
        row = 7

        counts = Counter()
        for card_id in self.selected_cards:
            counts[self.lookup_catalog(card_id)] += 1

        max_rows = self.height - row - 1
        usable_width = self.width - 4
        for name, amount in list(counts.items())[: max_rows]:
            text = f"({amount}x) {name}"
            self.window.addstr(row, 2, text[:usable_width])
            row += 1

        self.window.refresh()


class LobbyCardSelectionState:
    def __init__(self, screen: curses.window):
        self.screen = screen

        # Coordinate stuff for the windows
        window_height = (PAGE_SIZE + PADDING)
        window_width1 = PAGE_WIDTH + PADDING*2
        window_width2 = 23 + PADDING*2

        start_y1 = 2
        start_y2 = start_y1 + PAGE_SIZE + PADDING*2

        # X coordinates for 1-CardListDisplay, 2-CardDetailDisplay, 3-SelectionWindow
        start_x1 = center_something_global(window_width1 + window_width2 + 5) # center 2 windows, add 5 padding
        start_x2 = start_x1 + window_width1 + 5
        start_x3 = center_something_global(window_width1)

        # Create WINDOWS that displays cards, details, and selection
        self.cards_window = CardListDisplay(window_height, window_width1, start_y1, start_x1, PAGE_SIZE, PAGE_WIDTH)
        self.details_window = CardDetailDisplay(window_height, window_width2, start_y1, start_x2)
        self.selection_window = SelectionWindow(window_height, window_width1, start_y2, start_x3)


    def render(self):
        self.cards_window.print_cards_list()

        card_id = self.cards_window.get_highlighted_card_id()
        self.details_window.display_card_details(card_id)

        self.selection_window.refresh()
    
    def handle_key(self, key):
        if key in ARROW_KEYS:
            self.cards_window.navigate_cards_list(key)

        elif key == ord("+"):
            self.selection_window.add_card(self.cards_window)

        elif key == ord("-"):
            self.selection_window.put_back_card(self.cards_window)

        self.render()

    def get_cards(self):
        self.render()

        key=""
        self.screen.keypad(True)

        while key != 27:

            key = self.screen.getch()

            self.handle_key(key)

        self.screen.keypad(False)

        return self.selection_window.selected_cards


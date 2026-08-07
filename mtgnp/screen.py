""" Handles the client rendering. Does not handle PDUs for now.
Scroll down to main function below for high-level overview.
"""

import curses
import textwrap
from typing import Dict
from collections import Counter
from cards import get_unique_cards, get_card

global MENU_BORDER_CHARS
MENU_BORDER_CHARS = (
    '"', '"',
    '=', '=',
    '/', '\\',
    '\\', '/'
)

global CARD_BORDER_CHARS
CARD_BORDER_CHARS = (
    '|', '|',
    '-', '-',
    '/', '\\',
    '\\', '/'
)

global ARROW_KEYS
ARROW_KEYS = (
    curses.KEY_UP,
    curses.KEY_DOWN,
    curses.KEY_LEFT,
    curses.KEY_RIGHT,
)

global INPUT_KEYS
INPUT_KEYS = (
    ord("+"),
    ord("-")
)

def center_something_global(len: int):
    return (WIDTH - len) // 2

def get_global_center(stdscr):
    global WIDTH
    height, WIDTH = stdscr.getmaxyx()

    global CENTER
    CENTER = WIDTH // 2

def center_something_local(dimension: int, length: int):
    return (dimension - length) // 2

def get_card_details(card: Dict):
    """Retrieve keys and values from a card dict. Returns
    a list of textwrapped-strings to be printed in the
    CardDetailDisplay window. 

    Note: Can reduce more useless keys by following card_id's format
    """
    details = list()

    for key, value in card.items():
        
        if key == "card_id":
            continue
        elif key == "name":
            name = textwrap.wrap(value, width=17)
            details.append(f"name: {name[0]}")
            details.extend(name[1:])
        elif key == "simplified_effect":
            details.append("")
            details.append(f"{key}: ")
            effect = textwrap.wrap(value, width=23)
            details += effect
        else:
            details.append(f"{key}: {value}")

    return details

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

    def handle_arrow_key(self, key):
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

        self.print_cards_list()

    def get_highlighted_card_details(self):
        """Returns the details of lowest index card from unique cards list.
        Note: Make sure to check if None, None is returned."""
        # Get name of currently highlighted
        name = self.card_names[self.selected_index]

        # Get num of copies
        card_copies = self.get_card_copies(name)
        if not card_copies:
            return None, None
        
        card_id = self.unique_cards[name][0]
        card = get_card_details(get_card(card_id))

        return card, card_id

    def get_highlighted_name(self):
        return self.card_names[self.selected_index]
        
class CardDetailDisplay:
    def __init__(self, wheight, wwidth, starty, startx):
        self.window = curses.newwin(wheight, wwidth, starty, startx)

    def display_card_details(self, details: list[str]):
        if not details:
            return

        self.window.erase()
        self.window.border(*CARD_BORDER_CHARS)

        for i, line in enumerate(details):
            self.window.addstr(1 + i, 2, line)

        self.window.refresh()

class SelectionWindow:
    def __init__(self, wheight, wwidth, starty, startx):
        self.window = curses. newwin(wheight, wwidth, starty, startx)
        self.height = wheight
        self.width = wwidth

        self.selected_cards: list = []
        self.refresh()

    def lookup_catalog(self, card_id):
        return get_card(card_id)["name"]

    def count_cards(self) -> int:
        return len(self.selected_cards)

    def add_card(self, card_list_window: CardListDisplay):
        # Retrieve lowest index card id
        _, card_id = card_list_window.get_highlighted_card_details()

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


    def handle_key(self, key):
        if key == "+":
            if self.selected_index < min(self.page_start + self.page_size - 1, len(self.unique_cards) - 1):
                self.selected_index += 1
    
        elif key == "-":
            if self.page_start >= self.page_size:
                self.page_start -= self.page_size
                self.selected_index = self.page_start

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

def lobby_get_name(stdscr):
    # Clear whole screen
    stdscr.clear()
    stdscr.refresh()

    # Ask for name and let user see their input
    stdscr.addstr("What is your name?\n")
    curses.echo()
    playername = stdscr.getstr(13)
    curses.noecho()

    return playername

def lobby_get_cards(stdscr):
    # Clear whole screen
    stdscr.clear()
    stdscr.refresh()


    # Coordinate stuff for the windows
    PAGE_WIDTH = 33    # 33 is max str length for card name
    PAGE_SIZE = 16     # 16 cards displayed at a time
    PADDING = 2
    window_height = (PAGE_SIZE + PADDING)
    window_width1 = PAGE_WIDTH + PADDING*2
    window_width2 = 23 + PADDING*2

    start_y1 = 2
    start_y2 = start_y1 + PAGE_SIZE + PADDING*2

    # X coordinates for 1-CardListDisplay, 2-CardDetailDisplay, 3-SelectionWindow
    start_x1 = center_something_global(window_width1 + window_width2 + 5) # center 2 windows, add 5 padding
    start_x2 = start_x1 + window_width1 + 5
    start_x3 = center_something_global(window_width1)

    # Create window that displays list of cards
    cards_window = CardListDisplay(window_height, window_width1, start_y1, start_x1, PAGE_SIZE, PAGE_WIDTH)
    cards_window.print_cards_list()
    
    # Create window that displays details of cards
    details_window = CardDetailDisplay(window_height, window_width2, start_y1, start_x2)
    details, _ = cards_window.get_highlighted_card_details()
    details_window.display_card_details(details)

    # Create window that displays currently selected cards
    selection_window = SelectionWindow(window_height, window_width1, start_y2, start_x3)


    # Accept input from player
    stdscr.keypad(True)
    key = ""

    # Exit loop if user presses Esc (27)
    while key != 27:
        key = stdscr.getch()
        if key in ARROW_KEYS:
            cards_window.handle_arrow_key(key)
            details, _ = cards_window.get_highlighted_card_details()
            details_window.display_card_details(details)

        elif key in INPUT_KEYS:
            if key == ord("+"):
                selection_window.add_card(cards_window)

            elif key == ord("-"):
                selection_window.put_back_card(cards_window)

            selection_window.refresh()
            cards_window.print_cards_list()

    stdscr.keypad(False)

    stdscr.clear()
    stdscr.refresh()

    return selection_window.selected_cards

    

def main(stdscr):
    """ Main function, might get refactored to not be dependent on main
    when this file starts to handle PDU rendering."""
    get_global_center(stdscr)

    name = lobby_get_name(stdscr)
    stdscr.clear()
    stdscr.refresh()
    stdscr.addstr(name)
    cards = lobby_get_cards(stdscr)  


curses.wrapper(main)
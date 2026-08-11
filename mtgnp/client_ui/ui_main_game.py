import textwrap

# import everything from the other ui modules so 
# other files can just import only this one
from mtgnp.client_ui.ui_helper import *
from mtgnp.client_ui.ui_lobby import *
from mtgnp.client_ui.ui_mulligan import *
from mtgnp.cards import get_card
from typing import Any, Optional

# ============================================================
# GAME UI CONSTANTS
# ============================================================

HEADER_HEIGHT = 3
FOOTER_HEIGHT = 3

OPPONENT_BATTLEFIELD_HEIGHT = 14
PLAYER_BATTLEFIELD_HEIGHT = 14

LOWER_HEIGHT = (65 - HEADER_HEIGHT - OPPONENT_BATTLEFIELD_HEIGHT 
                - PLAYER_BATTLEFIELD_HEIGHT - FOOTER_HEIGHT)

HAND_WIDTH_RATIO = 0.50

VIEW_HAND = "HAND"
VIEW_BATTLEFIELD = "BATTLEFIELD"
VIEW_GRAVEYARD = "GRAVEYARD"
VIEW_STACK = "STACK"
VIEW_CARD_INFO = "CARD INFO"
VIEW_ACTIONS = "ACTIONS"
VIEW_HELP = "HELP"
    



# ============================================================
# MAIN GAME UI
# ============================================================

class GameUI:
    MIN_HEIGHT = 45
    MIN_WIDTH = 90

    def __init__(self, screen: curses.window, name):
        self.screen = screen
        self.height, self.width = screen.getmaxyx()

        # Current secondary view
        self.active_view: Optional[str] = None
        self.selected_index = 0
        self.selected_card_id: Optional[str] = None

        # Windows
        self.header_window = None
        self.opponent_field_window = None
        self.player_field_window = None
        self.hand_window = None
        self.stack_window = None
        self.status_window = None
        self.active_view_window = None
        self.footer_window = None

        self.create_windows()

    def resize(self):
        update_screen_size(self.screen)
        self.height, self.width = self.screen.getmaxyx()
        self.screen.erase()
        self.screen.refresh()
        self.create_windows()

    # ========================================================
    # WINDOW CREATION
    # ========================================================
    def create_windows(self):
        lower_height = max(5, self.height - HEADER_HEIGHT - OPPONENT_BATTLEFIELD_HEIGHT - PLAYER_BATTLEFIELD_HEIGHT - FOOTER_HEIGHT)

        # Header
        self.header_window = curses.newwin(HEADER_HEIGHT, self.width, 0, 0)

        # Battlefield
        opponent_y = HEADER_HEIGHT
        self.opponent_field_window = curses.newwin(OPPONENT_BATTLEFIELD_HEIGHT, self.width, opponent_y, 0)

        player_y = (opponent_y + OPPONENT_BATTLEFIELD_HEIGHT)
        self.player_field_window = curses.newwin(PLAYER_BATTLEFIELD_HEIGHT, self.width, player_y, 0)

        # Lower section
        lower_y = (player_y + PLAYER_BATTLEFIELD_HEIGHT)
        hand_width = int(self.width * HAND_WIDTH_RATIO)
        right_width = self.width - hand_width

        # Your hand
        self.hand_window = curses.newwin(lower_height, hand_width, lower_y, 0)

        stack_height = lower_height // 2
        status_height = lower_height - stack_height

        self.stack_window = curses.newwin(stack_height, right_width, lower_y, hand_width)
        self.status_window = curses.newwin(status_height, right_width, lower_y + stack_height, hand_width)

        active_y = HEADER_HEIGHT
        active_height = max(5, self.height - HEADER_HEIGHT - FOOTER_HEIGHT)
        self.active_view_window = curses.newwin(active_height, self.width, active_y, 0)

        # Footer
        footer_y = max(0, self.height - FOOTER_HEIGHT)
        self.footer_window = curses.newwin(FOOTER_HEIGHT, self.width, footer_y, 0)

    # ========================================================
    # MAIN RENDER
    # ========================================================
    def render(self, state: dict[str, Any]):
        if not check_minimum_size(self.screen, self.MIN_HEIGHT, self.MIN_WIDTH):
            return

        # Always render these
        self.render_header(state)
        self.render_footer()

        # Normal game screen
        if self.active_view is None:
            self.render_opponent_battlefield(state)
            self.render_player_battlefield(state)
            self.render_hand(state)
            self.render_stack(state)
            self.render_player_status(state)

        # Secondary view
        else:
            self.render_active_view(state)

    # ========================================================
    # HEADER
    # ========================================================
    def render_header(self, state):
        window = self.header_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        turn            = state.get("turn", "?")
        phase           = state.get("phase", "?")
        active_player   = state.get("active_player", "?")
        priority_holder = state.get("priority_holder","?")
        land_played     = state.get("land_played_this_turn",False)
        life            = state.get("life_totals",{})
        p1_life         = life.get("player_1","?")
        p2_life         = life.get("player_2","?")

        text = (
            f" TURN {turn} "
            f"| {phase} "
            f"| AP: {active_player} "
            f"| PRIORITY: {priority_holder} "
            f"| P1: {p1_life} HP "
            f"| P2: {p2_life} HP "
            f"| LAND: "
            f"{'YES' if land_played else 'NO'} "
        )

        self.safe_addstr(window, 1, 2, text)
        window.refresh()

    # ========================================================
    # OPPONENT BATTLEFIELD
    # ========================================================
    def render_opponent_battlefield(self, state):
        window = self.opponent_field_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)
        self.safe_addstr(window, 0, 2, " PLAYER 2 BATTLEFIELD ")

        battlefield = state.get("battlefield", {}).get("player_2", [])

        self.render_permanents(window,battlefield)
        window.refresh()

    # ========================================================
    # PLAYER BATTLEFIELD
    # ========================================================
    def render_player_battlefield(self, state):
        window = self.player_field_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)
        self.safe_addstr(window,0,2," PLAYER 1 BATTLEFIELD ")

        battlefield = state.get("battlefield", {}).get("player_1", [])

        self.render_permanents(window, battlefield)
        window.refresh()

    # ========================================================
    # PERMANENTS
    # ========================================================
    def render_permanents(self, window: curses.window, permanents: list[dict], start_y: int = 2):
        if not permanents:
            self.safe_addstr(window,2,2,"(empty)")
            return

        x = 2
        y = start_y
        card_width = 20
        window_height, window_width = (window.getmaxyx())

        for permanent in permanents:
            card_id     = permanent.get("id", "?")
            tapped      = permanent.get("tapped", False)
            damage      = permanent.get("damage", 0)
            power       = permanent.get("power")
            toughness   = permanent.get("toughness")

            name = get_card(card_id)["name"] # used to be name = card_id
            text = f"[{name}]"

            if tapped:
                text += " TAPPED"

            elif "tapped" in permanent:
                text += " READY"

            if power is not None and toughness is not None:
                text += f" {power}/{toughness}"

            if damage:
                text += f" DMG:{damage}"

            # Move to next row if necessary
            if x + card_width >= window_width - 2:
                x = 2
                y += 3

            if y >= window_height - 1:
                break

            self.safe_addstr(window, y, x, text[:card_width])
            x += card_width

    # ========================================================
    # HAND
    # ========================================================
    def render_hand(self, state):
        window = self.hand_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        hand = state.get("hand",[])
        self.safe_addstr(window, 0, 2, f" YOUR HAND ({len(hand)}) ")

        if not hand:
            self.safe_addstr(window, 2, 2, "(empty)")
            window.refresh()
            return

        for index, card_id in enumerate(hand):
            y = 2 + index

            if y >= window.getmaxyx()[0] - 1:
                break

            prefix = ("> " if index == self.selected_index else "  ")

            name = get_card(card_id)["name"]
            self.safe_addstr(window, y, 2, f"{prefix}{name}") # CHANGED: card_id replaced into name

        window.refresh()

    # ========================================================
    # STACK
    # ========================================================
    def render_stack(self, state):
        window = self.stack_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        stack = state.get(
            "stack",[])

        self.safe_addstr(window,0, 2, f" STACK ({len(stack)}) ")

        if not stack:
            self.safe_addstr(window, 2, 2, "(empty)")
            window.refresh()
            return

        for index, item in enumerate(stack):
            y = 2 + index

            if y >= window.getmaxyx()[0] - 1:
                break

            source = item.get("source", "?")
            item_type = item.get("item_type", "?")
            controller = item.get("controller", "?")

            text = (
                f"{index + 1}. "
                f"{source} "
                f"({item_type}) "
                f"[{controller}]"
            )

            self.safe_addstr(window,y,2,text)

        window.refresh()

    # ========================================================
    # PLAYER STATUS
    # ========================================================
    def render_player_status(self, state):
        window = self.status_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        self.safe_addstr(window, 0,2 , " PLAYER STATUS ")

        # Get values from state and graveyard
        life        = state.get("life_totals", {})
        hand        = state.get("hand_counts", {})
        library     = state.get("library_counts", {})
        graveyard   = state.get("graveyard", {})
        p1_hand     = len(state.get("hand", []))
        p2_hand     = hand.get("player_2", 0)
        p1_gy       = len(graveyard.get("player_1", []))
        p2_gy       = len(graveyard.get("player_2", []))

        self.safe_addstr(window,  2, 2, f"P1  HP: {life.get('player_1', '?')}")
        self.safe_addstr(window,  3, 2, f"P2  HP: {life.get('player_2', '?')}")
        self.safe_addstr(window,  5, 2, f"P1  Hand: {p1_hand}")
        self.safe_addstr(window,  6, 2, f"P2  Hand: {p2_hand}")
        self.safe_addstr(window,  8, 2, f"P1  Deck: "f"{library.get('player_1', '?')}")
        self.safe_addstr(window,  9, 2, f"P2  Deck: "f"{library.get('player_2', '?')}")
        self.safe_addstr(window, 11, 2, f"P1  GY: {p1_gy}")
        self.safe_addstr(window, 12, 2, f"P2  GY: {p2_gy}")

        window.refresh()

    # ========================================================
    # FOOTER
    # ========================================================
    def render_footer(self):
        window = self.footer_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        controls = [
            ("H", "HAND"),
            ("B", "BATTLEFIELD"),
            ("G", "GRAVEYARD"),
            ("S", "STACK"),
            ("I", "CARD INFO"),
            ("A", "ACTIONS"),
            ("P", "PASS"),
            ("?", "HELP"),
            ("Q", "QUIT"),
        ]

        x = 2
        for key, label in controls:
            text = f"[{key}] {label}"

            if x + len(text) >= self.width - 1:
                break

            self.safe_addstr(window, 1, x, text)
            x += len(text) + 2

        window.refresh()

    # ========================================================
    # ACTIVE VIEW
    # ========================================================
    def render_active_view(self, state):
        window = self.active_view_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        if self.active_view == VIEW_HAND:
            self.render_hand_view(window, state)

        elif self.active_view == VIEW_BATTLEFIELD:
            self.render_battlefield_view(window, state)

        elif self.active_view == VIEW_GRAVEYARD:
            self.render_graveyard_view(window, state)

        elif self.active_view == VIEW_STACK:
            self.render_stack_view(window,state)

        elif self.active_view == VIEW_CARD_INFO:
            self.render_card_info_view(window, state)

        elif self.active_view == VIEW_ACTIONS:
            self.render_actions_view(window,state)

        elif self.active_view == VIEW_HELP:
            self.render_help_view(window,state)

        window.refresh()

    # ========================================================
    # HAND VIEW
    # ========================================================
    def render_hand_view(self, window, state):
        hand = state.get("hand", [])
        self.safe_addstr(window, 0, 2, " HAND ")

        if not hand:
            self.safe_addstr(window, 2, 2, "(empty)")
            return

        self.safe_addstr(window, 2, 2, "↑ ↓ Select")
        self.safe_addstr(window, 3, 2, "ENTER: View card")
        self.safe_addstr(window, 4, 2, "ESC: Back")

        for index, card_id in enumerate(hand):
            y = 7 + index
            if y >= window.getmaxyx()[0] - 1:
                break

            name = get_card(card_id)["name"]

            prefix = ("> " if index == self.selected_index else "  ")
            self.safe_addstr(window, y, 4, f"{prefix}{name}")

    # ========================================================
    # BATTLEFIELD VIEW
    # ========================================================
    def render_battlefield_view(self, window, state):

        self.safe_addstr(window, 0, 2, " BATTLEFIELD ")

        battlefield = state.get("battlefield", {})
        p1 = battlefield.get("player_1", [])
        p2 = battlefield.get("player_2", [])

        self.safe_addstr(window, 2, 2, "PLAYER 2")

        self.render_permanents(window, p2, start_y=4)

        middle = window.getmaxyx()[0] // 2
        self.safe_addstr(window, middle, 2, "PLAYER 1")

        # Give the player's permanents a little extra vertical separation.
        self.render_permanents(window, p1, start_y=middle + 2)

    # ========================================================
    # GRAVEYARD VIEW
    # ========================================================
    def render_graveyard_view(self, window, state):
        self.safe_addstr(window, 0, 2, " GRAVEYARD ")

        graveyard = state.get("graveyard", {})
        cards     = graveyard.get("player_1", [])

        # No cards in graveyard
        if not cards:
            self.safe_addstr(window, 2, 2, "(empty)")
            return

        self.safe_addstr(window, 2, 2, "↑ ↓ Select")
        self.safe_addstr(window, 3, 2, "ENTER: View card")
        self.safe_addstr(window, 4, 2, "ESC: Back")

        # Display cards in graveyard
        for index, card_id in enumerate(cards):
            y = 7 + index

            if y >= window.getmaxyx()[0] - 1:
                break

            prefix = ("> " if index == self.selected_index else "  ")
            self.safe_addstr(window, y, 4, f"{prefix}{card_id}")

    # ========================================================
    # STACK VIEW
    # ========================================================
    def render_stack_view(self, window, state):
        stack = state.get("stack", [])

        self.safe_addstr(window, 0, 2, " STACK ")

        if not stack:
            self.safe_addstr(window, 2, 2, "(empty)")
            return

        for index, item in enumerate(stack):
            y = 2 + index

            source = item.get( "source", "?")
            item_type = item.get("item_type", "?")

            self.safe_addstr(window, y, 2, f"{index + 1}. " f"{source} ({item_type})")

    # ========================================================
    # CARD INFO VIEW
    # ========================================================
    def render_card_info_view(self, window, state):

        self.safe_addstr(window, 0, 2, " CARD INFO ")
        self.safe_addstr(window, 2, 2, "Select a card from the relevant view.")
        self.safe_addstr(window, 4, 2, "ENTER: Inspect")
        self.safe_addstr(window, 5, 2, "ESC: Back")

        if self.selected_card_id is None:
            self.safe_addstr(window, 2, 2, "No card selected.")
            self.safe_addstr(window, 4, 2, "ESC: Back")
            return

        card = get_card(self.selected_card_id)

        # Check first if card exists
        if card is None:
            self.safe_addstr(window, 2, 2, "Card not found.")
            self.safe_addstr(window, 3, 2, f"ID: {self.selected_card_id}")
            self.safe_addstr(window, 5, 2, "ESC: Back")
            return

        # Get relevant fields
        name        = card.get("name", self.selected_card_id)
        card_type   = card.get("card_type")
        subtype     = card.get("subtype")
        mana_cost   = card.get("mana_cost")
        power       = card.get("power")
        toughness   = card.get("toughness")
        effect      = card.get("simplified_effect")

        row = 2
        self.safe_addstr(window, row, 2, str(name))
        row += 2

        # Print the fields if they exist
        if card_type is not None:
            self.safe_addstr(window, row, 2, f"Type: {card_type}")
            row += 1

        if subtype:
            self.safe_addstr(window, row, 2, f"Subtype: {subtype}")
            row += 1

        if mana_cost is not None:
            self.safe_addstr(window, row, 2, f"Mana Cost: {mana_cost}")
            row += 1

        if power is not None or toughness is not None:
            power_text = power if power is not None else "-"
            toughness_text = toughness if toughness is not None else "-"

            self.safe_addstr(window, row, 2, f"Power/Toughness: {power_text}/{toughness_text}")
            row += 1


        # Print the effect with textwrap
        if effect:
            row += 1
            self.safe_addstr(window, row, 2, "Effect:")
            row += 1

            usable_width = window.getmaxyx()[1] - 4
            wrapped_effect = textwrap.wrap(str(effect), width=usable_width)

            for line in wrapped_effect:
                if row >= window.getmaxyx()[0] - 3:
                    break

                self.safe_addstr(window, row, 2, line)
                row += 1


        # Controls
        height = window.getmaxyx()[0]
        self.safe_addstr(window, height - 2, 2, "I: Card Info")
        self.safe_addstr(window, height - 2, 20, "ESC: Back")

    # ========================================================
    # ACTIONS VIEW
    # ========================================================
    def get_available_actions(self, state):
        actions = []

        priority_holder = state.get("priority_holder")
        active_player = state.get("active_player")
        phase = state.get("phase")

        if priority_holder != self.player_id: 
            pass # TODO

        return actions

    
    def render_actions_view(self, window, state):
        self.safe_addstr(window, 0, 2, " ACTIONS ")

        # actions = self.get_available_actions(state)
        actions = []

        if not actions:
            self.safe_addstr(window, 2, 2, "No actions available.")
            self.safe_addstr(window, 4, 2, "ESC: Back")
            return

        for index, action in enumerate(actions):
            y = 2 + index

            if y >= window.getmaxyx()[0] - 3:
                break

            prefix = "> " if index == self.selected_index else "  "
            self.safe_addstr(window, y, 4, f"{prefix}{action['label']}")

        self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "ENTER: Choose")
        self.safe_addstr(window, window.getmaxyx()[0] - 2, 20, "ESC: Back")

    # ========================================================
    # HELP VIEW
    # ========================================================
    def render_help_view(self, window, state):

        self.safe_addstr(window, 0, 2, " HELP ")

        help_lines = [
            "[H] Hand",
            "[B] Battlefield",
            "[G] Graveyard",
            "[S] Stack",
            "[I] Card Info",
            "[A] Actions",
            "[P] Pass Priority",
            "[?] Help",
            "[Q] Quit",
            "",
            "Inside a menu:",
            "↑ ↓    Navigate",
            "ENTER  Select / Inspect",
            "ESC    Return to game",
        ]

        for index, line in enumerate(help_lines):
            self.safe_addstr(window, 2 + index, 4, line)

    # ========================================================
    # INPUT
    # ========================================================
    def handle_key(self, key, state):
        if key == curses.KEY_RESIZE:
            self.resize()
            self.render(state)
            return None

        key = normalize_key(key)
        
        # NORMAL GAME SCREEN
        if self.active_view is None:
            return self.handle_game_key(key, state)

        # SECONDARY VIEW
        return self.handle_view_key(key, state)

    # ========================================================
    # GLOBAL / GAME INPUT
    # ========================================================
    def handle_game_key(self, key, state):
        # Quit
        if key == ord("q"):
            return "QUIT"

        # Menu shortcuts
        elif key == ord("h"):
            self.open_view(VIEW_HAND)

        elif key == ord("b"):
            self.open_view(VIEW_BATTLEFIELD)

        elif key == ord("g"):
            self.open_view(VIEW_GRAVEYARD)
        
        elif key == ord("s"):
            self.open_view(VIEW_STACK)

        elif key == ord("i"):
            if self.selected_card_id:
                self.open_view(VIEW_CARD_INFO)

        elif key == ord("a"):
            self.open_view(VIEW_ACTIONS)

        elif key == ord("?"):
            self.open_view(VIEW_HELP)

        # Pass priority
        elif key == ord("p"):
            return "PASS"

        # Do nothing if unregistered key press
        return None

    # ========================================================
    # VIEW INPUT
    # ========================================================
    def handle_view_key(self, key, state):
        # ESC = return to normal game screen
        if key == ESCAPE:
            self.close_view()
            return None

        # Navigation
        if key == curses.KEY_UP:
            self.navigate_up()
        elif key == curses.KEY_DOWN:
            self.navigate_down(state)

        # Selection
        elif key in ENTER_KEYS:
            return self.select_current(state)
        return None

    # ========================================================
    # VIEW MANAGEMENT
    # ========================================================

    def open_view(self, view_name: str):
        self.active_view = view_name
        self.selected_index = 0     # Reset selection when entering a new menu.

    def close_view(self):
        self.active_view = None
        self.selected_index = 0
        self.selected_card_id = None

    # ========================================================
    # NAVIGATION
    # ========================================================

    def navigate_up(self):
        if self.selected_index > 0:
            self.selected_index -= 1

    def navigate_down(self, state):

        # ----------------------------------------------------
        # Determine how many selectable things exist.
        #
        # This can become view-specific later.
        # ----------------------------------------------------

        count = self.get_current_item_count(state)

        if self.selected_index < count - 1:
            self.selected_index += 1

    # ========================================================
    # CURRENT ITEM COUNT
    # ========================================================
    def get_current_item_count(self, state):

        if self.active_view == VIEW_HAND:
            return len(state.get("hand", []))

        elif self.active_view == VIEW_GRAVEYARD:
            return len(state.get("graveyard", {}).get("player_1", []))

        elif self.active_view == VIEW_STACK:
            return len(state.get("stack", []))

        return 0

    # ========================================================
    # SELECT
    # ========================================================
    def select_current(self, state):

        if self.active_view == VIEW_HAND:
            hand = state.get("hand", [])

            if not hand:
                return None

            self.selected_card_id = hand[self.selected_index]
            self.active_view = VIEW_CARD_INFO


        elif self.active_view == VIEW_GRAVEYARD:
            graveyard = state.get("graveyard", {}).get("player_1", [])

            if not graveyard:
                return None

            self.selected_card_id = (graveyard[self.selected_index])
            self.active_view = VIEW_CARD_INFO


        elif self.active_view == VIEW_ACTIONS:
            actions = self.get_available_actions(state)

            if not actions:
                return

            return actions[self.selected_index]

        return None

    # ========================================================
    # SAFE PRINT
    # ========================================================
    def safe_addstr(self, window, y: int, x: int, text: str, attr=curses.A_NORMAL):
        """
        Prevent curses from crashing if text reaches
        the edge of the window.
        """
        height, width = window.getmaxyx()

        if y < 0 or y >= height:
            return

        if x < 0 or x >= width:
            return

        available = width - x - 1
        if available <= 0:
            return

        try:
            window.addstr(y, x, text[:available], attr)

        except curses.error:
            pass
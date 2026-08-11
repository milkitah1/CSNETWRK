"""Curses-based main game UI interface and view controller for MTGNP.

Renders header, opponent battlefield, player battlefield, hand, stack, status panel,
and secondary views (Actions, Combat, Trigger Ordering, Discard, Card Info).
"""
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
VIEW_TARGETING = "TARGETING"
VIEW_COMBAT = "COMBAT"
VIEW_ASSIGN_BLOCKER = "ASSIGN_BLOCKER"
VIEW_DAMAGE_ORDER = "DAMAGE_ORDER"
VIEW_TRIGGER_ORDER = "TRIGGER_ORDER"
VIEW_TRIGGER_CHOICE = "TRIGGER_CHOICE"
VIEW_DISCARD = "DISCARD"
    



# ============================================================
# MAIN GAME UI
# ============================================================

def build_mana_payment(card_info: dict) -> dict:
    cost_str = card_info.get("mana_cost", "") or card_info.get("cost", "") or ""
    import re
    res = {}
    tokens = re.findall(r"(\d+|[WUBRG])", str(cost_str))
    for tok in tokens:
        if tok.isdigit():
            res["generic"] = int(tok)
        else:
            res[tok] = res.get(tok, 0) + 1
    return res

def check_requires_tap(card_info: dict) -> bool:
    if "requires_tap" in card_info:
        return bool(card_info["requires_tap"])
    if "tap_cost" in card_info:
        return bool(card_info["tap_cost"])
    effect = (str(card_info.get("effect", "")) + " " + str(card_info.get("simplified_effect", ""))).lower()
    card_type = (str(card_info.get("type", "")) + " " + str(card_info.get("card_type", ""))).lower()
    return "tap" in effect or "land" in card_type

class GameUI:
    MIN_HEIGHT = 45
    MIN_WIDTH = 90

    def __init__(self, screen: curses.window, name):
        self.screen = screen
        self.height, self.width = screen.getmaxyx()
        self.player_id = name

        # Current secondary view
        self.active_view: Optional[str] = None
        self.selected_index = 0
        self.selected_card_id: Optional[str] = None
        self.pending_cast_card_id: Optional[str] = None
        self.selected_combat_units: set[str] = set()
        self.blocker_assignments: dict[str, str] = {}
        self.pending_blocker_id: Optional[str] = None
        self.damage_blocker_order: list[str] = []
        self.selected_discard_cards: set[str] = set()
        self.trigger_order_ids: list[str] = []

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
        self.render_footer(state)

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

    def get_player_state(self, state: dict, category: str):
        """Returns (local_player_data, opponent_data) for state dicts (life_totals, battlefield, graveyard)."""
        data = state.get(category, {})
        if not isinstance(data, dict):
            return [], []

        player_id = getattr(self, "player_id", None)
        if player_id and player_id in data:
            p1_val = data[player_id]
            opp_vals = [v for k, v in data.items() if k != player_id]
            p2_val = opp_vals[0] if opp_vals else []
            return p1_val, p2_val

        if "player_1" in data or "player_2" in data:
            return data.get("player_1", []), data.get("player_2", [])

        keys = list(data.keys())
        if len(keys) >= 2:
            return data[keys[0]], data[keys[1]]
        elif len(keys) == 1:
            return data[keys[0]], []

        return [], []

    # ========================================================
    # HEADER
    # ========================================================
    def render_header(self, state):
        window = self.header_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        turn = state.get("turn", 0)
        phase = state.get("phase", "MULLIGAN")
        active_player = state.get("active_player") or "-"
        priority_holder = state.get("priority_holder") or "None"
        land_played = state.get("land_played_this_turn", False)

        p1_life, p2_life = self.get_player_state(state, "life_totals")
        p1_str = str(p1_life) if p1_life not in ([], None) else "20"
        p2_str = str(p2_life) if p2_life not in ([], None) else "20"

        player_id = getattr(self, "player_id", None)
        is_my_turn = active_player and active_player == player_id
        turn_label = "[YOUR TURN]" if is_my_turn else f"[{active_player}'s Turn]"

        text = (
            f" TURN {turn} "
            f"| {phase} "
            f"| {turn_label} "
            f"| PRIORITY: {priority_holder} "
            f"| P1: {p1_str} HP "
            f"| P2: {p2_str} HP "
            f"| LAND: {'YES' if land_played else 'NO'} "
        )

        attr = curses.A_REVERSE if is_my_turn else curses.A_NORMAL
        self.safe_addstr(window, 1, 2, text, attr)
        window.refresh()

    # ========================================================
    # OPPONENT BATTLEFIELD
    # ========================================================
    def render_opponent_battlefield(self, state):
        window = self.opponent_field_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)
        self.safe_addstr(window, 0, 2, " OPPONENT BATTLEFIELD ")

        _, p2_bf = self.get_player_state(state, "battlefield")

        self.render_permanents(window, p2_bf if isinstance(p2_bf, list) else [])
        window.refresh()

    # ========================================================
    # PLAYER BATTLEFIELD
    # ========================================================
    def render_player_battlefield(self, state):
        window = self.player_field_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)
        self.safe_addstr(window, 0, 2, " YOUR BATTLEFIELD ")

        p1_bf, _ = self.get_player_state(state, "battlefield")

        self.render_permanents(window, p1_bf if isinstance(p1_bf, list) else [])
        window.refresh()

    # ========================================================
    # PERMANENTS
    # ========================================================
    def render_permanents(self, window: curses.window, permanents: list[dict], start_y: int = 2, selected_idx: Optional[int] = None):
        if not permanents:
            self.safe_addstr(window, 2, 2, "(empty)")
            return

        x = 2
        y = start_y
        card_width = 30
        window_height, window_width = (window.getmaxyx())

        for index, permanent in enumerate(permanents):
            card_id     = permanent.get("id", "?")
            tapped      = permanent.get("tapped", False)
            damage      = permanent.get("damage", 0)
            power       = permanent.get("power")
            toughness   = permanent.get("toughness")

            card_info = get_card(card_id) or get_card(card_id.rsplit("_", 1)[0]) or {}
            name = card_info.get("name", card_id)

            prefix = "> " if (selected_idx is not None and index == selected_idx) else "  "

            suffix = ""
            if tapped:
                suffix += " TAP"

            if power is not None and toughness is not None:
                suffix += f" {power}/{toughness}"

            if damage:
                suffix += f" DMG:{damage}"

            max_name_len = card_width - len(prefix) - len(suffix) - 2
            if max_name_len > 3 and len(name) > max_name_len:
                disp_name = name[:max_name_len - 1] + "…"
            else:
                disp_name = name

            text = f"{prefix}[{disp_name}]{suffix}"

            if x + card_width >= window_width - 2:
                x = 2
                y += 2

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

        self.safe_addstr(window, 0, 2, " PLAYER STATUS ")

        p1_life, p2_life = self.get_player_state(state, "life_totals")
        p1_gy, p2_gy = self.get_player_state(state, "graveyard")
        library = state.get("library_counts", {})
        p1_hand = len(state.get("hand", []))
        p2_hand = list(state.get("hand_counts", {}).values())[0] if state.get("hand_counts") else 0
        p1_gy_count = len(p1_gy) if isinstance(p1_gy, list) else 0
        p2_gy_count = len(p2_gy) if isinstance(p2_gy, list) else 0

        player_id = getattr(self, "player_id", "P1")
        opp_label = "OPP"
        lib_vals = list(library.values())
        p1_lib = lib_vals[0] if lib_vals else "?"
        p2_lib = lib_vals[1] if len(lib_vals) > 1 else "?"

        self.safe_addstr(window, 2, 2, f"{player_id[:6]:<6} | HP: {p1_life:<2} | Hand: {p1_hand:<2} | Deck: {p1_lib:<2} | GY: {p1_gy_count}")
        self.safe_addstr(window, 3, 2, f"{opp_label:<6} | HP: {p2_life:<2} | Hand: {p2_hand:<2} | Deck: {p2_lib:<2} | GY: {p2_gy_count}")

        # Turn & Priority status indicator
        active_player = state.get("active_player")
        is_my_turn = active_player and active_player == player_id

        if is_my_turn:
            self.safe_addstr(window, 5, 2, "== YOUR TURN ==")
        else:
            self.safe_addstr(window, 5, 2, f"== {opp_label}'s TURN ==")

        priority_holder = state.get("priority_holder")
        if priority_holder and priority_holder == player_id:
            self.safe_addstr(window, 6, 2, ">> YOUR PRIORITY <<")
        elif priority_holder:
            self.safe_addstr(window, 6, 2, f"Waiting: {priority_holder}")
        else:
            self.safe_addstr(window, 6, 2, "(Auto phase...)")

        window.refresh()

    # ========================================================
    # FOOTER
    # ========================================================
    def render_footer(self, state=None):
        window = self.footer_window

        window.erase()
        window.border(*MENU_BORDER_CHARS)

        priority_holder = (state or {}).get("priority_holder")
        player_id = getattr(self, "player_id", None)
        we_have_priority = priority_holder and priority_holder == player_id

        controls = [
            ("H", "HAND"),
            ("B", "FIELD"),
            ("G", "GRAVEYARD"),
            ("S", "STACK"),
            ("A", "ACTIONS"),
            ("P", "PASS" if we_have_priority else "WAIT"),
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

        elif self.active_view == VIEW_TARGETING:
            self.render_targeting_view(window, state)

        elif self.active_view == VIEW_COMBAT:
            self.render_combat_view(window, state)

        elif self.active_view == VIEW_ASSIGN_BLOCKER:
            self.render_assign_blocker_view(window, state)

        elif self.active_view == VIEW_DAMAGE_ORDER:
            self.render_damage_order_view(window, state)

        elif self.active_view == VIEW_TRIGGER_ORDER:
            self.render_trigger_order_view(window, state)

        elif self.active_view == VIEW_TRIGGER_CHOICE:
            self.render_trigger_choice_view(window, state)

        elif self.active_view == VIEW_DISCARD:
            self.render_discard_view(window, state)

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

        p1_bf, p2_bf = self.get_player_state(state, "battlefield")

        self.safe_addstr(window, 2, 2, "OPPONENT BATTLEFIELD")
        self.render_permanents(window, p2_bf if isinstance(p2_bf, list) else [], start_y=4)

        middle = window.getmaxyx()[0] // 2
        self.safe_addstr(window, middle, 2, "YOUR BATTLEFIELD (↑ ↓ Select, ENTER to Activate)")
        self.render_permanents(window, p1_bf if isinstance(p1_bf, list) else [], start_y=middle + 2, selected_idx=self.selected_index)

    # ========================================================
    # GRAVEYARD VIEW
    # ========================================================
    def render_graveyard_view(self, window, state):
        self.safe_addstr(window, 0, 2, " GRAVEYARD ")

        cards, _ = self.get_player_state(state, "graveyard")

        if not isinstance(cards, list) or not cards:
            self.safe_addstr(window, 2, 2, "(empty)")
            return

        self.safe_addstr(window, 2, 2, "↑ ↓ Select")
        self.safe_addstr(window, 3, 2, "ENTER: View card")
        self.safe_addstr(window, 4, 2, "ESC: Back")

        for index, card_id in enumerate(cards):
            y = 7 + index

            if y >= window.getmaxyx()[0] - 1:
                break

            card_info = get_card(card_id) or get_card(card_id.rsplit("_", 1)[0]) or {}
            name = card_info.get("name", card_id)

            prefix = ("> " if index == self.selected_index else "  ")
            self.safe_addstr(window, y, 4, f"{prefix}{name}")

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
        priority_holder = state.get("priority_holder")
        player_id = getattr(self, "player_id", None)
        we_have_priority = priority_holder and priority_holder == player_id

        actions = []
        if we_have_priority:
            actions.append({"label": "Pass Priority", "action": "PASS"})
        actions.append({"label": "Concede Game", "action": {"type": PDUs.CONCEDE}})

        phase = str(state.get("phase", "")).upper()
        hand = state.get("hand", [])
        if state.get("request_discard") or phase == "CLEANUP" and len(hand) > 7:
            actions.insert(0, {"label": "Discard Cards", "action": "OPEN_DISCARD"})
        if state.get("pending_trigger_order"):
            actions.insert(0, {"label": "Order Triggers", "action": "OPEN_TRIGGER_ORDER"})
        if state.get("pending_trigger_choice"):
            actions.insert(0, {"label": "Trigger Choice", "action": "OPEN_TRIGGER_CHOICE"})
        if state.get("awaiting_damage_order") or phase == "ASSIGN_DAMAGE_ORDER":
            actions.insert(0, {"label": "Assign Damage Order", "action": "OPEN_DAMAGE_ORDER"})
        elif "ATTACK" in phase or "BLOCK" in phase or "COMBAT" in phase:
            actions.insert(0, {"label": f"Combat View ({phase})", "action": "OPEN_COMBAT"})
        return actions

    
    def render_actions_view(self, window, state):
        self.safe_addstr(window, 0, 2, " ACTIONS ")

        actions = self.get_available_actions(state)

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
    # TARGETING VIEW
    # ========================================================
    def get_available_targets(self, state):
        targets = [
            {"label": "Opponent (Player 2)", "id": "player_2"},
            {"label": "Yourself (Player 1)", "id": "player_1"}
        ]
        bf1, bf2 = self.get_player_state(state, "battlefield")
        for perm in bf1:
            p_id = perm.get("id", "?")
            card_info = get_card(p_id) or get_card(p_id.rsplit("_", 1)[0]) or {}
            if "Land" in str(card_info.get("card_type", "")):
                continue
            p_name = card_info.get("name", p_id)
            targets.append({"label": f"Your: {p_name} ({p_id})", "id": p_id})

        for perm in bf2:
            p_id = perm.get("id", "?")
            card_info = get_card(p_id) or get_card(p_id.rsplit("_", 1)[0]) or {}
            if "Land" in str(card_info.get("card_type", "")):
                continue
            p_name = card_info.get("name", p_id)
            targets.append({"label": f"Opponent: {p_name} ({p_id})", "id": p_id})

        return targets

    def render_targeting_view(self, window, state):
        self.safe_addstr(window, 0, 2, " SELECT TARGET ")
        card_info = get_card(self.pending_cast_card_id) if self.pending_cast_card_id else {}
        card_name = card_info.get("name", self.pending_cast_card_id or "?")
        self.safe_addstr(window, 2, 2, f"Casting: {card_name}")
        self.safe_addstr(window, 4, 2, "Available Targets:")

        targets = self.get_available_targets(state)
        for index, target in enumerate(targets):
            y = 6 + index
            if y >= window.getmaxyx()[0] - 3:
                break
            prefix = "> " if index == self.selected_index else "  "
            self.safe_addstr(window, y, 4, f"{prefix}{target['label']}")

        self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "ENTER: Confirm Target")
        self.safe_addstr(window, window.getmaxyx()[0] - 2, 25, "ESC: Cancel")

    # ========================================================
    # COMBAT VIEW
    # ========================================================
    def get_active_attackers(self, state):
        attackers = state.get("attackers", [])
        if not attackers:
            _, opp_bf = self.get_player_state(state, "battlefield")
            attackers = [{"creature_id": p.get("id"), "target": p.get("attack_target", "player_1")} for p in opp_bf if "attack_target" in p]
        return attackers

    def render_combat_view(self, window, state):
        phase = str(state.get("phase", "")).upper()
        self.safe_addstr(window, 0, 2, f" COMBAT: {phase} ")

        if "BLOCK" in phase:
            bf, _ = self.get_player_state(state, "battlefield")
            creatures = [p for p in bf if not p.get("tapped", False) and "Land" not in str((get_card(p.get("id", "")) or get_card(p.get("id", "").rsplit("_", 1)[0]) or {}).get("card_type", ""))]
            self.safe_addstr(window, 2, 2, "Select creature to assign blocking (ENTER to pair):")
            if not creatures:
                self.safe_addstr(window, 4, 2, "(No untapped creatures available to block)")
            for index, perm in enumerate(creatures):
                c_id = perm.get("id", "?")
                c_name = get_card(c_id).get("name", c_id) if get_card(c_id) else c_id
                assigned_att = self.blocker_assignments.get(c_id)
                if assigned_att:
                    att_name = get_card(assigned_att).get("name", assigned_att) if get_card(assigned_att) else assigned_att
                    status = f"[X] Blocking: {att_name}"
                else:
                    status = "[ ] Unassigned"
                prefix = "> " if index == self.selected_index else "  "
                self.safe_addstr(window, 4 + index, 4, f"{prefix}{status} {c_name} ({c_id})")

            confirm_idx = len(creatures)
            prefix = "> " if self.selected_index == confirm_idx else "  "
            self.safe_addstr(window, 5 + confirm_idx, 4, f"{prefix}[ Submit Blockers ]")

            self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "ENTER: Assign/Confirm Blockers | ESC: Back")
        else:
            bf, _ = self.get_player_state(state, "battlefield")
            creatures = [p for p in bf if not p.get("tapped", False) and "Land" not in str((get_card(p.get("id", "")) or get_card(p.get("id", "").rsplit("_", 1)[0]) or {}).get("card_type", ""))]
            self.safe_addstr(window, 2, 2, "Select creatures to attack (SPACE to toggle):")
            if not creatures:
                self.safe_addstr(window, 4, 2, "(No untapped creatures available to attack)")
            for index, perm in enumerate(creatures):
                c_id = perm.get("id", "?")
                c_name = get_card(c_id).get("name", c_id) if get_card(c_id) else c_id
                selected = "[X]" if c_id in self.selected_combat_units else "[ ]"
                prefix = "> " if index == self.selected_index else "  "
                self.safe_addstr(window, 4 + index, 4, f"{prefix}{selected} {c_name} ({c_id})")

            confirm_idx = len(creatures)
            prefix = "> " if self.selected_index == confirm_idx else "  "
            self.safe_addstr(window, 5 + confirm_idx, 4, f"{prefix}[ Submit Attackers ]")

            self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "SPACE: Toggle | ENTER: Confirm Attackers | ESC: Back")

    def render_assign_blocker_view(self, window, state):
        self.safe_addstr(window, 0, 2, " PAIR BLOCKER TO ATTACKER ")
        b_name = get_card(self.pending_blocker_id).get("name", self.pending_blocker_id) if self.pending_blocker_id and get_card(self.pending_blocker_id) else self.pending_blocker_id
        self.safe_addstr(window, 2, 2, f"Blocker: {b_name}")
        self.safe_addstr(window, 4, 2, "Select which attacker to block:")

        attackers = self.get_active_attackers(state)
        for index, att in enumerate(attackers):
            att_id = att.get("creature_id", "?")
            att_name = get_card(att_id).get("name", att_id) if get_card(att_id) else att_id
            prefix = "> " if index == self.selected_index else "  "
            self.safe_addstr(window, 6 + index, 4, f"{prefix}{att_name} ({att_id})")

        self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "ENTER: Assign | ESC: Cancel")

    def render_damage_order_view(self, window, state):
        self.safe_addstr(window, 0, 2, " ASSIGN DAMAGE ORDER ")
        attacker_id = state.get("damage_order_attacker", "Attacker")
        self.safe_addstr(window, 2, 2, f"Attacker: {attacker_id}")
        self.safe_addstr(window, 4, 2, "Order blockers (First receives damage first):")

        if not self.damage_blocker_order:
            self.damage_blocker_order = list(state.get("blockers_to_order", []))

        for index, b_id in enumerate(self.damage_blocker_order):
            b_name = get_card(b_id).get("name", b_id) if get_card(b_id) else b_id
            prefix = "> " if index == self.selected_index else "  "
            self.safe_addstr(window, 6 + index, 4, f"{prefix}{index + 1}. {b_name} ({b_id})")

        self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "ENTER: Submit Order | ESC: Cancel")

    def render_trigger_order_view(self, window, state):
        self.safe_addstr(window, 0, 2, " ORDER TRIGGERS ")
        self.safe_addstr(window, 2, 2, "Reorder simultaneous triggers (First on top of stack):")
        
        prompt = state.get("pending_trigger_order", {})
        if not self.trigger_order_ids:
            self.trigger_order_ids = list(prompt.get("trigger_ids", []))

        for index, t_id in enumerate(self.trigger_order_ids):
            prefix = "> " if index == self.selected_index else "  "
            self.safe_addstr(window, 4 + index, 4, f"{prefix}{index + 1}. {t_id}")

        self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "ENTER: Confirm Order | ESC: Cancel")

    def render_trigger_choice_view(self, window, state):
        self.safe_addstr(window, 0, 2, " TRIGGER CHOICE ")
        prompt = state.get("pending_trigger_choice", {})
        summary = prompt.get("effect_summary", "Triggered Effect")
        self.safe_addstr(window, 2, 2, f"Effect: {summary}")
        self.safe_addstr(window, 4, 2, "[Y] Accept Trigger | [N] Decline Trigger")

    def render_discard_view(self, window, state):
        self.safe_addstr(window, 0, 2, " DISCARD CARDS ")
        hand = state.get("hand", [])
        needed = max(1, len(hand) - 7)
        self.safe_addstr(window, 2, 2, f"Select {needed} card(s) to discard (SPACE to toggle):")

        for index, c_id in enumerate(hand):
            c_name = get_card(c_id).get("name", c_id) if get_card(c_id) else c_id
            selected = "[X]" if c_id in self.selected_discard_cards else "[ ]"
            prefix = "> " if index == self.selected_index else "  "
            self.safe_addstr(window, 4 + index, 4, f"{prefix}{selected} {c_name} ({c_id})")

        self.safe_addstr(window, window.getmaxyx()[0] - 2, 2, "SPACE: Toggle | ENTER: Confirm Discard | ESC: Cancel")

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

        # Concede
        elif key == ord("c"):
            return {"type": PDUs.CONCEDE}

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

        # Space toggles combat / discard selection
        if self.active_view == VIEW_COMBAT and key == ord(" "):
            bf, _ = self.get_player_state(state, "battlefield")
            creatures = [p for p in bf if not p.get("tapped", False) and "Land" not in str((get_card(p.get("id", "")) or get_card(p.get("id", "").rsplit("_", 1)[0]) or {}).get("card_type", ""))]
            if 0 <= self.selected_index < len(creatures):
                c_id = creatures[self.selected_index].get("id")
                if c_id:
                    if c_id in self.selected_combat_units:
                        self.selected_combat_units.remove(c_id)
                    else:
                        self.selected_combat_units.add(c_id)
            return None

        if self.active_view == VIEW_DISCARD and key == ord(" "):
            hand = state.get("hand", [])
            if 0 <= self.selected_index < len(hand):
                c_id = hand[self.selected_index]
                if c_id in self.selected_discard_cards:
                    self.selected_discard_cards.remove(c_id)
                else:
                    self.selected_discard_cards.add(c_id)
            return None

        if self.active_view == VIEW_TRIGGER_CHOICE:
            if key == ord("y") or key == ord("Y"):
                prompt = state.get("pending_trigger_choice", {})
                targets = prompt.get("legal_targets", [])
                chosen_target = targets[0] if targets else None
                self.close_view()
                return {
                    "type": PDUs.TRIGGER_CHOICE_RESPONSE,
                    "trigger_id": prompt.get("trigger_id", ""),
                    "accept": True,
                    "chosen_target": chosen_target
                }
            elif key == ord("n") or key == ord("N"):
                prompt = state.get("pending_trigger_choice", {})
                self.close_view()
                return {
                    "type": PDUs.TRIGGER_CHOICE_RESPONSE,
                    "trigger_id": prompt.get("trigger_id", ""),
                    "accept": False
                }

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

        elif self.active_view == VIEW_BATTLEFIELD:
            bf, _ = self.get_player_state(state, "battlefield")
            return len(bf)

        elif self.active_view == VIEW_GRAVEYARD:
            gy, _ = self.get_player_state(state, "graveyard")
            return len(gy)

        elif self.active_view == VIEW_STACK:
            return len(state.get("stack", []))

        elif self.active_view == VIEW_TARGETING:
            return len(self.get_available_targets(state))

        elif self.active_view == VIEW_COMBAT:
            bf, _ = self.get_player_state(state, "battlefield")
            creatures = [p for p in bf if not p.get("tapped", False) and "Land" not in str((get_card(p.get("id", "")) or get_card(p.get("id", "").rsplit("_", 1)[0]) or {}).get("card_type", ""))]
            return len(creatures) + 1

        elif self.active_view == VIEW_ASSIGN_BLOCKER:
            return len(self.get_active_attackers(state))

        elif self.active_view == VIEW_DAMAGE_ORDER:
            return len(self.damage_blocker_order or state.get("blockers_to_order", []))

        elif self.active_view == VIEW_TRIGGER_ORDER:
            return len(self.trigger_order_ids or state.get("pending_trigger_order", {}).get("trigger_ids", []))

        elif self.active_view == VIEW_DISCARD:
            return len(state.get("hand", []))

        elif self.active_view == VIEW_ACTIONS:
            return len(self.get_available_actions(state))

        return 0

    # ========================================================
    # SELECT
    # ========================================================
    def select_current(self, state):

        if self.active_view == VIEW_HAND:
            hand = state.get("hand", [])

            if not hand or self.selected_index >= len(hand):
                return None

            card_id = hand[self.selected_index]
            raw_id = card_id.get("id", card_id.get("card_id", "")) if isinstance(card_id, dict) else card_id

            if isinstance(raw_id, str) and raw_id:
                card_info = get_card(raw_id) or get_card(raw_id.rsplit("_", 1)[0]) or (card_id if isinstance(card_id, dict) else {})
            else:
                card_info = card_id if isinstance(card_id, dict) else {}
            card_type = (str(card_info.get("card_type", "")) + " " + str(card_info.get("type", ""))).lower()

            if "land" in card_type:
                return {"type": PDUs.PLAY_LAND, "card_id": card_id}
            else:
                mana_pay = build_mana_payment(card_info)
                requires_target = bool(card_info.get("targets")) or ("target" in str(card_info.get("effect", "")).lower() or "target" in str(card_info.get("simplified_effect", "")).lower())
                if requires_target:
                    self.pending_cast_card_id = card_id
                    self.open_view(VIEW_TARGETING)
                    return None
                else:
                    return {"type": PDUs.CAST_SPELL, "card_id": card_id, "targets": [], "mana_payment": mana_pay}

        elif self.active_view == VIEW_BATTLEFIELD:
            bf, _ = self.get_player_state(state, "battlefield")
            if not bf or self.selected_index >= len(bf):
                return None
            perm = bf[self.selected_index]
            card_id = perm.get("id", "")
            card_info = get_card(card_id) or get_card(card_id.rsplit("_", 1)[0]) or {}
            cost_pay = {"tap": check_requires_tap(card_info), "mana": build_mana_payment(card_info)}
            return {"type": PDUs.ACTIVATE_ABILITY, "card_id": card_id, "cost_payment": cost_pay}

        elif self.active_view == VIEW_TARGETING:
            targets = self.get_available_targets(state)
            if not targets or self.selected_index >= len(targets):
                return None
            chosen = targets[self.selected_index]["id"]
            card_id = self.pending_cast_card_id
            card_info = get_card(card_id) or get_card(card_id.rsplit("_", 1)[0]) or {}
            mana_pay = build_mana_payment(card_info)
            self.close_view()
            return {"type": PDUs.CAST_SPELL, "card_id": card_id, "targets": [chosen], "mana_payment": mana_pay}

        elif self.active_view == VIEW_COMBAT:
            phase = str(state.get("phase", "")).upper()
            bf, _ = self.get_player_state(state, "battlefield")
            creatures = [p for p in bf if not p.get("tapped", False) and "Land" not in str((get_card(p.get("id", "")) or get_card(p.get("id", "").rsplit("_", 1)[0]) or {}).get("card_type", ""))]
            if "BLOCK" in phase:
                if 0 <= self.selected_index < len(creatures):
                    b_id = creatures[self.selected_index].get("id")
                    if b_id:
                        if b_id in self.blocker_assignments:
                            del self.blocker_assignments[b_id]
                        else:
                            self.pending_blocker_id = b_id
                            self.open_view(VIEW_ASSIGN_BLOCKER)
                        return None
                blockers = [{"blocker_id": b, "attacker_id": a} for b, a in self.blocker_assignments.items()]
                self.blocker_assignments.clear()
                self.close_view()
                return {"type": PDUs.DECLARE_BLOCKERS, "blockers": blockers}
            else:
                if 0 <= self.selected_index < len(creatures):
                    c_id = creatures[self.selected_index].get("id")
                    if c_id in self.selected_combat_units:
                        self.selected_combat_units.remove(c_id)
                    else:
                        self.selected_combat_units.add(c_id)
                    return None
                attackers = [{"creature_id": cid, "target": "player_2"} for cid in self.selected_combat_units]
                self.selected_combat_units.clear()
                self.close_view()
                return {"type": PDUs.DECLARE_ATTACKERS, "attackers": attackers}

        elif self.active_view == VIEW_ASSIGN_BLOCKER:
            attackers = self.get_active_attackers(state)
            if 0 <= self.selected_index < len(attackers):
                att_id = attackers[self.selected_index].get("creature_id")
                if self.pending_blocker_id and att_id:
                    self.blocker_assignments[self.pending_blocker_id] = att_id
            self.pending_blocker_id = None
            self.open_view(VIEW_COMBAT)
            return None

        elif self.active_view == VIEW_DAMAGE_ORDER:
            attacker_id = state.get("damage_order_attacker", "Attacker")
            order = list(self.damage_blocker_order)
            self.damage_blocker_order.clear()
            self.close_view()
            return {"type": PDUs.ASSIGN_DAMAGE_ORDER, "attacker_id": attacker_id, "blocker_order": order}

        elif self.active_view == VIEW_TRIGGER_ORDER:
            order = list(self.trigger_order_ids)
            self.trigger_order_ids.clear()
            self.close_view()
            return {"type": PDUs.TRIGGER_ORDER_RESPONSE, "ordered_trigger_ids": order}

        elif self.active_view == VIEW_DISCARD:
            cards = list(self.selected_discard_cards)
            self.selected_discard_cards.clear()
            self.close_view()
            return {"type": PDUs.DISCARD, "card_ids": cards}

        elif self.active_view == VIEW_GRAVEYARD:
            graveyard, _ = self.get_player_state(state, "graveyard")

            if not graveyard or self.selected_index >= len(graveyard):
                return None

            self.selected_card_id = (graveyard[self.selected_index])
            self.active_view = VIEW_CARD_INFO


        elif self.active_view == VIEW_ACTIONS:
            actions = self.get_available_actions(state)

            if not actions or self.selected_index >= len(actions):
                return None

            selected_action = actions[self.selected_index]
            self.close_view()
            if selected_action.get("action") == "OPEN_COMBAT":
                self.open_view(VIEW_COMBAT)
                return None
            elif selected_action.get("action") == "OPEN_DAMAGE_ORDER":
                self.open_view(VIEW_DAMAGE_ORDER)
                return None
            elif selected_action.get("action") == "OPEN_TRIGGER_ORDER":
                self.open_view(VIEW_TRIGGER_ORDER)
                return None
            elif selected_action.get("action") == "OPEN_TRIGGER_CHOICE":
                self.open_view(VIEW_TRIGGER_CHOICE)
                return None
            elif selected_action.get("action") == "OPEN_DISCARD":
                self.open_view(VIEW_DISCARD)
                return None
            return selected_action.get("action")

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
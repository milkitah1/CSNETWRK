"""UI layout constants, border utilities, key normalization, and screen dimension helpers for Curses.

Provides global constants for UI layout sizing, border character sets, minimum screen
dimension verification, and centering utilities.
"""
import curses

# ============================================================
# CONSTANTS
# ============================================================

MENU_BORDER_CHARS = (
    '"', '"',
    '=', '=',
    '/', '\\',
    '\\', '/'
)

CARD_BORDER_CHARS = (
    '|', '|',
    '-', '-',
    '/', '\\',
    '\\', '/'
)

ARROW_KEYS = (
    curses.KEY_UP,
    curses.KEY_DOWN,
    curses.KEY_LEFT,
    curses.KEY_RIGHT,
)

# Card list / Selection dimensions
LONGEST_CARD_NAME = 25
PAGE_WIDTH = LONGEST_CARD_NAME + 8 
PAGE_SIZE = 16     # 16 cards displayed at a time
PADDING = 2

ESCAPE = 27
ENTER_KEYS = (curses.KEY_ENTER, 10, 13)


# ------------------------------------------------------------
# Global menu shortcuts
# ------------------------------------------------------------

def normalize_key(key):
    """ Convert into ord and lowercase if it is a letter"""
    if 0 <= key < 256:
        key = ord(chr(key).lower())
        return key
    else:
        return key

# ============================================================
# GLOBAL SCREEN HELPERS
# ============================================================

WIDTH = 0
HEIGHT = 0

def center_something_global(len: int):
    return (WIDTH - len) // 2

def update_screen_size(stdscr):
    global HEIGHT, WIDTH
    HEIGHT, WIDTH = stdscr.getmaxyx()

def initialize_screen(stdscr):
    update_screen_size(stdscr)

def check_minimum_size(stdscr, min_height: int, min_width: int) -> bool:
    update_screen_size(stdscr)
    if HEIGHT < min_height or WIDTH < min_width:
        stdscr.erase()
        msg1 = "Terminal too small!"
        msg2 = f"Current: {WIDTH}x{HEIGHT} | Minimum required: {min_width}x{min_height}"
        msg3 = "Please resize / expand your terminal window."
        
        try:
            stdscr.addstr(max(0, HEIGHT // 2 - 1), max(0, center_something_global(len(msg1))), msg1)
            stdscr.addstr(max(0, HEIGHT // 2), max(0, center_something_global(len(msg2))), msg2)
            stdscr.addstr(max(0, HEIGHT // 2 + 1), max(0, center_something_global(len(msg3))), msg3)
        except Exception:
            pass
        stdscr.refresh()
        return False
    return True

def center_something_local(dimension: int, length: int):
    return (dimension - length) // 2
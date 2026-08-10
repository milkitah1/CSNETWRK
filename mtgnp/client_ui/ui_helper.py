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

def initialize_screen(stdscr):
    global WIDTH
    _, WIDTH = stdscr.getmaxyx()

def center_something_local(dimension: int, length: int):
    return (dimension - length) // 2
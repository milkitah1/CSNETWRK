import curses

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

INPUT_KEYS = (
    ord("+"),
    ord("-")
)

LONGEST_CARD_NAME = 25
PAGE_WIDTH = LONGEST_CARD_NAME + 8 
PAGE_SIZE = 16     # 16 cards displayed at a time
PADDING = 2

def center_something_global(len: int):
    return (WIDTH - len) // 2

def initialize_screen(stdscr):
    global WIDTH
    _, WIDTH = stdscr.getmaxyx()

def center_something_local(dimension: int, length: int):
    return (dimension - length) // 2
""" Handles the client rendering. Does not handle PDUs for now.
Scroll down to main function below for high-level overview.

Test using `python -m mtgnp.screen`
"""

import curses
from mtgnp.client_ui.ui_lobby import *
from mtgnp.client_ui.ui_mulligan import MulliganState

def lobby_get_name(stdscr):
    # Clear whole screen
    stdscr.clear()
    stdscr.refresh()

    # Ask for name and let user see their input
    stdscr.addstr("What is your name?\n")
    curses.echo()
    playername = stdscr.getstr(13)
    curses.noecho()

    stdscr.clear()
    stdscr.refresh()
    return playername


def main(stdscr):
    """ Main function, might get refactored to not be dependent on main
    when this file starts to handle PDU rendering."""
    initialize_screen(stdscr)

    name = lobby_get_name(stdscr)

    ###################################################
    # This is a whole block.
    stdscr.clear()
    stdscr.refresh()
    lobby = LobbyCardSelectionState(stdscr)
    cards = lobby.get_cards()
    # TODO: send a PDU
    # Insert code below
    ###################################################

    #-- just for testing --
    print(f"cards: {cards}")


    ###################################################
    # This is a whole block.
    stdscr.clear()
    stdscr.refresh()
    mulligan = MulliganState()

    keeps = False
    while not keeps:
        keeps = mulligan.keep_or_mulligan()
        # TODO: send a PDU
        # Insert code below

    if mulligan.mulligan_count > 0:
        bottomed_cards = mulligan.bottom_cards()
        # TODO: send a PDU
        # Insert code below
    ###################################################

curses.wrapper(main)
"""CLI entrypoint for mtgnp package.

Usage:
    python -m mtgnp server --port 4444 --verbose --log
    python -m mtgnp client --host 127.0.0.1 --port 4444 --ping --log client1.log
"""
from __future__ import annotations

import argparse
import curses

# from mtgnp.states.mulliganState import MulliganState

from .server import Server
from .client import Client
from .common import pdu as PDUs
from .client_ui.ui_main_game import *


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    srun = sub.add_parser("server")
    srun.add_argument("--host", default="127.0.0.1")
    srun.add_argument("--port", type=int, default=4444)
    srun.add_argument("--verbose", action="store_true")
    srun.add_argument("--log", action="store_true")

    crun = sub.add_parser("client")
    crun.add_argument("--host", default="127.0.0.1")
    crun.add_argument("--port", type=int, default=4444)
    crun.add_argument("--ping", action="store_true")
    crun.add_argument("--connect", action="store_true")
    crun.add_argument("--name", default="player")
    crun.add_argument("--verbose", action="store_true")
    crun.add_argument("--log", choices=["client1.log", "player1.log","server.log","client2.log"] ,default="")

    args = p.parse_args()
    if args.cmd == "server":
        srv = Server(host=args.host, port=args.port, verbose=args.verbose, log=args.log)
        print(f"Starting server on {args.host}:{srv.port}")
        srv.start()
        try:
            while True:
                pass
        except KeyboardInterrupt:
            srv.stop()
    elif args.cmd == "client":
        curses.wrapper(run_client, args)
    else:
        p.print_help()

def run_client(stdscr, args):
    c = Client(host=args.host, port=args.port, verbose=args.verbose, log_filename=args.log)
    c.connect()

    if args.ping:
        print(c.ping())

    if args.connect:
        initialize_screen(stdscr)
        curses.curs_set(0)
        name = lobby_get_name(stdscr)
        started = c.run_lobby(stdscr, name)

        if started and c._start_game:
            stdscr.clear()
            stdscr.refresh()
            c.run_mulligan(stdscr)
    c.close()

if __name__ == "__main__":
    main()

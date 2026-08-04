"""CLI entrypoint for mtgnp package.

Usage:
    python -m mtgnp server --port 4444
    python -m mtgnp client --host 127.0.0.1 --port 4444 --ping
"""
from __future__ import annotations

import argparse

from .server import Server
from .client import Client
from .client import Client


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    srun = sub.add_parser("server")
    srun.add_argument("--host", default="127.0.0.1")
    srun.add_argument("--port", type=int, default=4444)
    srun.add_argument("--verbose", action="store_true")

    crun = sub.add_parser("client")
    crun.add_argument("--host", default="127.0.0.1")
    crun.add_argument("--port", type=int, default=4444)
    crun.add_argument("--ping", action="store_true")
    crun.add_argument("--connect", action="store_true")
    crun.add_argument("--name", default="player")
    crun.add_argument("--verbose", action="store_true")

    args = p.parse_args()
    if args.cmd == "server":
        srv = Server(host=args.host, port=args.port, verbose=args.verbose)
        print(f"Starting server on {args.host}:{srv.port}")
        srv.start()
        try:
            while True:
                pass
        except KeyboardInterrupt:
            srv.stop()
    elif args.cmd == "client":
        c = Client(host=args.host, port=args.port, verbose=args.verbose)
        c.connect()
        if args.ping:
            print(c.ping())
        if args.connect:
            c.interactive_lobby(args.name)
        c.close()
    else:
        p.print_help()


if __name__ == "__main__":
    main()

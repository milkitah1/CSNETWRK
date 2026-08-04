""" This file is used to monitor PDU logs in one terminal.
Adds an optional --log argument to server and client. 
Note: Written with assistance from AI.

Run this file first, then add `--log` to run server command, 
or add `--log client1.log` or `--log client2.log` to run clients.

Sample Usage:
    1. Run `python log_viewer.py`
    2. Run server with `python -m mtgnp server --verbose --log`
    3. Run first client with `python -m mtgnp client --connect --log client1.log`
    3. Run other client with `python -m mtgnp client --connect --log client2.log`
"""

from pathlib import Path
import time

LOG_DIR = Path("mtgnp/logs")

LOG_FILES = [
    LOG_DIR / "server.log",
    LOG_DIR / "client1.log",
    LOG_DIR / "client2.log",
]

POLL_INTERVAL = 0.1  # seconds


def main():
    # Make sure the log files exist
    for file in LOG_FILES:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch(exist_ok=True)

    # Open all files and seek to the end
    handles = {}
    for file in LOG_FILES:
        f = open(file, "r", encoding="utf-8")
        f.seek(0, 2)  # Go to end of file
        handles[file] = f

    print("Watching logs...\nPress Ctrl+C to stop.\n")

    try:
        while True:
            for file, f in handles.items():
                while True:
                    line = f.readline()
                    if not line:
                        break

                    print(f"[{file.stem.upper()}] {line}", end="")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nStopping log viewer.")

    finally:
        for f in handles.values():
            f.close()


if __name__ == "__main__":
    main()
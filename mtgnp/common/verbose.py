"""Simple verbose logging utilities for development.

Usage:
    from mtgnp.common.verbose import set_verbose, log_send, log_recv

    Get-Content .\\logs\\server.log, .\\logs\\client1.log, .\\logs\\client2.log -Wait
"""
from __future__ import annotations

import json
import datetime
from typing import Any, Dict
from pathlib import Path
import threading

LOG_LOCK = threading.Lock()

VERBOSE = False
LOG_FILENAME = ""

# Is not verbose by default
# log parameter is used by server, logs to server.log if true
# filename parameter is used by client, can be either client1.log or client2.log
def set_verbose(flag: bool, filename: str = "", log: bool = False) -> None:
    global VERBOSE
    VERBOSE = bool(flag)

    global LOG_FILENAME

    if log:
        LOG_FILENAME = "server.log"
    elif filename:
        LOG_FILENAME = filename
    else:
        LOG_FILENAME = ""

    # Clear old log on startup
    if LOG_FILENAME:
        file_path = Path(f"mtgnp/logs/{LOG_FILENAME}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("")

def _timestamp() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _pretty(obj: Dict[str, Any]) -> str:
    try:
        return json.dumps(obj, indent=2, sort_keys=True)
    except Exception:
        return str(obj)

def log_to_file(obj: str):
    file_path = Path(f"mtgnp/logs/{LOG_FILENAME}")

    with LOG_LOCK:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(obj)
            f.flush()


def log_send(label: str, pdu: Dict[str, Any]) -> None:
    if not VERBOSE and not LOG_FILENAME:
        return    
    log = f"[{_timestamp()}] {LOG_FILENAME} {label}: {pdu.get('type', '<no-type>')}\n{_pretty(pdu)}\n"

    if VERBOSE:
        print(log)
        
    if LOG_FILENAME:
        log_to_file(log)


def log_recv(label: str, pdu: Dict[str, Any]) -> None:
    if not VERBOSE and not LOG_FILENAME:
        return
    log = f"[{_timestamp()}] {LOG_FILENAME} {label}: {pdu.get('type', '<no-type>')}\n{_pretty(pdu)}\n"

    if VERBOSE:
        print(log)
        
    if LOG_FILENAME:
        log_to_file(log)
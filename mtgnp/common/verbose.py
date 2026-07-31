"""Simple verbose logging utilities for development.

Usage:
    from mtgnp.common.verbose import set_verbose, log_send, log_recv


"""
from __future__ import annotations

import json
import datetime
from typing import Any, Dict

VERBOSE = False


def set_verbose(flag: bool) -> None:
    global VERBOSE
    VERBOSE = bool(flag)


def _timestamp() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _pretty(obj: Dict[str, Any]) -> str:
    try:
        return json.dumps(obj, indent=2, sort_keys=True)
    except Exception:
        return str(obj)


def log_send(label: str, pdu: Dict[str, Any]) -> None:
    if not VERBOSE:
        return
    print(f"[{_timestamp()}] {label}: {pdu.get('type', '<no-type>')}")
    print(_pretty(pdu))


def log_recv(label: str, pdu: Dict[str, Any]) -> None:
    if not VERBOSE:
        return
    print(f"[{_timestamp()}] {label}: {pdu.get('type', '<no-type>')}")
    print(_pretty(pdu))

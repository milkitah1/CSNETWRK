"""Framing helpers for MTGNP PDUs.

PDUs are JSON objects encoded as UTF-8, prefixed by a 4-byte big-endian
unsigned length (uint32). The maximum payload enforced is 65535 bytes.
"""
from __future__ import annotations

import json
import struct
import socket
from typing import Any, Dict

from .verbose import log_send, log_recv

MAX_PDU_SIZE = 65535

# Ensures n amount of bytes is received, then returns data 
def recv_exactly(sock: socket.socket, n: int) -> bytes:
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("socket closed while reading")
        data.extend(chunk)
    return bytes(data)

# 
def recv_pdu(sock: socket.socket) -> Dict[str, Any]:
    # Read header first to check json length
    hdr = recv_exactly(sock, 4)
    (length,) = struct.unpack(
        ">I", hdr
    )

    if length > MAX_PDU_SIZE:
        raise ValueError(f"incoming PDU too large: {length}")

    # Read json by exact length
    payload = recv_exactly(sock, length)
    obj = json.loads(payload.decode("utf-8"))

    # Log then return pdu data
    log_recv("RECV", obj)
    return obj


def send_pdu(sock: socket.socket, obj: Dict[str, Any]) -> None:
    # Convert data into json and get length
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    length = len(payload)

    # Check first if valid pdu size
    if length > MAX_PDU_SIZE:
        print("ERROR: PDU too large to send:", length)
        raise ValueError(f"PDU too large to send: {length}")

    # Convert length into 4 byte uint
    hdr = struct.pack(">I", length)

    # Log and send json to socket
    log_send("SEND", obj)
    sock.sendall(hdr + payload)

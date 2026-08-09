import socket
import threading

from mtgnp.common.framing import send_pdu, recv_pdu
from mtgnp.common.verbose import set_verbose


def _make_pair():
    a, b = socket.socketpair()
    return a, b


def test_send_recv_roundtrip():
    set_verbose(False)
    a, b = _make_pair()
    pdu = {"type": "PING", "payload": {"nonce": 123}}
    threading.Thread(target=send_pdu, args=(a, pdu), daemon=True).start()
    got = recv_pdu(b)
    assert got["type"] == "PING"
    assert got["payload"]["nonce"] == 123
    a.close(); b.close()


def test_large_payload_rejected():
    """PDUs over MAX_PDU_SIZE must raise ValueError on send."""
    import pytest
    a, b = _make_pair()
    big = {"type": "X", "data": "x" * 70000}
    with pytest.raises(ValueError):
        send_pdu(a, big)
    a.close(); b.close()


def test_closed_socket_raises_on_recv():
    """recv_pdu on a closed socket must raise ConnectionError."""
    import pytest
    a, b = _make_pair()
    a.close()
    with pytest.raises((ConnectionError, OSError)):
        recv_pdu(b)
    b.close()


def test_multiple_pdus_in_sequence():
    """Multiple PDUs sent back-to-back are all received correctly."""
    a, b = _make_pair()
    pdus = [{"type": "MSG", "n": i} for i in range(5)]

    def writer():
        for p in pdus:
            send_pdu(a, p)

    threading.Thread(target=writer, daemon=True).start()
    received = [recv_pdu(b) for _ in range(5)]
    assert [r["n"] for r in received] == list(range(5))
    a.close(); b.close()

import socket
import threading
import time

from mtgnp.common.framing import send_pdu, recv_pdu
from mtgnp.common.verbose import set_verbose


def test_send_recv_roundtrip():
    set_verbose(False)
    a, b = socket.socketpair()

    pdu = {"type": "PING", "payload": {"nonce": 123}}

    def writer():
        send_pdu(a, pdu)

    t = threading.Thread(target=writer)
    t.start()
    got = recv_pdu(b)
    t.join(timeout=1.0)
    assert got["type"] == "PING"
    assert got["payload"]["nonce"] == 123
    a.close()
    b.close()

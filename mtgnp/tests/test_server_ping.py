import time
import threading
import socket

from mtgnp.server import Server
from mtgnp.client import Client


def test_server_responds_to_ping():
    srv = Server(host="127.0.0.1", port=0, verbose=False)
    srv.start()
    try:
        # give server a moment to bind
        time.sleep(0.05)
        c = Client(host="127.0.0.1", port=srv.port, verbose=False)
        c.connect()
        resp = c.ping()
        assert resp.get("type") == "PONG"
        c.close()
    finally:
        srv.stop()

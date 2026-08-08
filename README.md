# MTGNP v1.0 — Execution & Verbose Logging Guide

This repository contains the Magic: The Gathering Multiplayer Network Protocol (MTGNP v1.0) engine, server, and client implementations.

---

## 1. Running the System

Make sure to run all commands from the repository root directory (`CSNETWRK`).

### Server
To start the TCP server with verbose console output and logging enabled:
```bash
python -m mtgnp server --verbose --log
```
*Note: The `--log` flag writes server logs to `mtgnp/logs/server.log`.*

### Clients
Run each client in a separate terminal window:

**Client 1:**
```bash
python -m mtgnp client --connect --name [username] --log client1.log
```

**Client 2:**
```bash
python -m mtgnp client --connect --name [username] --log client2.log
```

---

## 2. Real-Time Log Viewer

You can watch all incoming and outgoing PDUs from the server and both clients live in a single unified terminal window:

1. Open a new terminal in the project root.
2. Run the log viewer script:
   ```bash
   python log_viewer.py
   ```
3. Start the server and clients with the `--log` flags shown above.
4. The viewer will stream formatted PDU traffic from `mtgnp/logs/server.log`, `mtgnp/logs/client1.log`, and `mtgnp/logs/client2.log`.


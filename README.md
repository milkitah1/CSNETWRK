# MTGNP v1.0 — Execution & Game UI Guide

This repository contains the Magic: The Gathering Multiplayer Network Protocol (MTGNP v1.0) engine, server, client, and full curses-based Terminal UI implementation.

---

## 1. Running the System

Make sure to run all commands from the repository root directory (`CSNETWRK`).

**1. Server:**
```bash
python -m mtgnp server --port 4444 --verbose --log
```
*Note: The `--log` is an optional flag used to write server logs to `mtgnp/logs/server.log`.*

**2. Client 1 (Alice):**
```bash
python -m mtgnp client --host 127.0.0.1 --port 4444 --connect --log client1.log
```

**3. Client 2 (Bob):**
```bash
python -m mtgnp client --host 127.0.0.1 --port 4444 --connect --log client2.log
```

## 2. Terminal Game UI Controls & Views

The Game UI automatically resizes to terminal windows and transitions seamlessly across game phases:

| Key Shortcut | Action / Description |
|---|---|
| **`[H]`** | **Hand View**: Browse cards in your hand. Highlight a card and press `ENTER` to play a land, cast a spell, or open targeting mode. |
| **`[B]`** | **Battlefield View**: Browse your permanents. Highlight a creature/land and press `ENTER` to activate an ability. |
| **`[G]`** | **Graveyard View**: View cards in your graveyard. |
| **`[S]`** | **Stack View**: View spells and abilities currently on the stack. |
| **`[A]`** | **Actions Menu**: Open the contextual actions menu (Pass Priority, Combat, Triggers, Discard, Concede). |
| **`[P]`** | **Pass Priority**: Transmit `PRIORITY_PASS` directly to the server. |
| **`[C]`** | **Concede Game**: Transmit `CONCEDE` to immediately forfeit. |
| **`[?]`** | **Help Menu**: Displays control shortcuts. |
| **`[Q]`** | **Quit**: Exit the game UI. |

## 3. Running Automated Tests

To run the full test suite:
```bash
python -m pytest
```

---

## 4. Real-Time Log Viewer

You can watch all incoming and outgoing PDUs from both clients live in a single unified terminal window:

1. Open a new terminal in the project root.
2. Run the log viewer script:
   ```bash
   python log_viewer.py
   ```
3. Start the server and clients with the `--log` flags shown above.
4. The viewer will stream formatted PDU traffic from `mtgnp/logs/client1.log`, and `mtgnp/logs/client2.log`.

Note: Server logs can still be viewed, albeit manually. They were excluded in the live viewer, due to complications with simultaneous activity with the clients.

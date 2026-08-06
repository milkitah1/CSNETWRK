"""Lobby manager: track players and wait until all are ready.

This module provides a simple thread-safe Lobby class suitable for the
MTGNP server. The lobby accepts up to `max_players` (default 2) and
offers a blocking `wait_for_all_ready` method that returns when all
joined players have indicated they're ready.
"""
#not used in the current code
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional


class Lobby:
    def __init__(self, max_players: int = 2):
        self.max_players = int(max_players)
        self._lock = threading.Condition()
        # players: id -> {"ready": bool, "meta": Any}
        self._players: Dict[str, Dict[str, Any]] = {}

    def add_player(self, player_id: str, meta: Optional[Any] = None) -> None:
        """Add a player to the lobby. If already present, updates meta."""
        with self._lock:
            if player_id not in self._players and len(self._players) >= self.max_players:
                raise RuntimeError("lobby is full")
            self._players[player_id] = {"ready": False, "meta": meta}
            self._lock.notify_all()

    def remove_player(self, player_id: str) -> None:
        with self._lock:
            if player_id in self._players:
                del self._players[player_id]
                self._lock.notify_all()

    def set_ready(self, player_id: str, ready: bool = True) -> None:
        """Mark a player as ready/unready and notify waiters."""
        with self._lock:
            if player_id not in self._players:
                raise KeyError(player_id)
            self._players[player_id]["ready"] = bool(ready)
            self._lock.notify_all()

    def is_ready(self, player_id: str) -> bool:
        return bool(self._players.get(player_id, {}).get("ready", False))

    def players(self) -> List[str]:
        return list(self._players.keys())

    def ready_count(self) -> int:
        return sum(1 for p in self._players.values() if p.get("ready"))

    def all_ready(self) -> bool:
        if len(self._players) < self.max_players:
            return False
        return all(p.get("ready") for p in self._players.values())

    def wait_for_all_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until the lobby has `max_players` joined and all are ready.

        Returns True if the condition was reached, False if the timeout
        expired first.
        """
        with self._lock:
            if self.all_ready():
                return True
            waited = self._lock.wait_for(self.all_ready, timeout=timeout)
            return bool(waited)


__all__ = ["Lobby"]

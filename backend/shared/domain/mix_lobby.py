"""How many lobbies one pickup mix may run at once, and what they are called.

Shared because the same ceiling is a database CHECK
(``balancer.custom_game.lobby_count``), a request contract (balancer-service)
and a Discord label (``lobby_a``..``lobby_f``) at the same time.
"""

from __future__ import annotations

from typing import Final

__all__ = ("LOBBY_LETTERS", "MAX_LOBBIES")

#: Hard ceiling on ``custom_game.lobby_count``; lobby indexes are ``0..MAX_LOBBIES - 1``.
MAX_LOBBIES: Final[int] = 6

#: Board-facing name of a lobby by index; the wire and the database speak indexes.
LOBBY_LETTERS: Final[str] = "ABCDEF"

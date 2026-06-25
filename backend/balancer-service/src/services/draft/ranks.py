"""Single source of truth for "what rank does a player have on a given role".

Rank is a function of ``(player, role)``: the per-role catalogue
(``DraftPlayer.role_ranks``) is authoritative, with ``rank_value`` (the
primary-role default) as the fallback when a role has no specific entry.
"""

from __future__ import annotations

from shared.core.enums import DraftRole
from shared.models.draft import DraftPlayer


def role_rank(player: DraftPlayer, role: DraftRole | str | None) -> int | None:
    """Return the player's rank for ``role``, falling back to ``rank_value``."""
    if role is None:
        return player.rank_value
    key = role.value if isinstance(role, DraftRole) else str(role)
    value = (player.role_ranks or {}).get(key)
    return value if value is not None else player.rank_value

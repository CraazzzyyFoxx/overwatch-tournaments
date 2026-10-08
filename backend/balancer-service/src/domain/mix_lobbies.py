"""Who is actually seated in a lobby right now.

Membership in a lobby is not stored: it is the seats of that lobby's selected
balance option. One pure function answers it for every caller -- the balance
candidate filter, the pager's conflict check, the busy rows a recorded match
freezes, the ``current_lobby`` badge on the board, and the voice mover.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.domain.balancer.result_serializer import as_lobby_document

__all__ = ("seated_member_ids", "seated_teams")


def seated_teams(balance_result_json: Mapping[str, Any] | None, variant_index: int) -> tuple[tuple[int, ...], ...]:
    """Member ids per team of ``variant_index``, team 1 first; ``()`` when nobody is seated.

    Same reading rules as :func:`seated_member_ids`, which is the union of these.
    """
    document = as_lobby_document(balance_result_json)
    variants = document.get("variants") if isinstance(document, Mapping) else None
    if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
        return ()
    variant = variants[variant_index]
    teams = variant.get("teams") if isinstance(variant, Mapping) else None
    if not isinstance(teams, list):
        return ()
    out: list[tuple[int, ...]] = []
    for team in teams:
        roster = team.get("roster") if isinstance(team, Mapping) else None
        seats: list[int] = []
        for bucket in roster.values() if isinstance(roster, Mapping) else ():
            for uuid in bucket if isinstance(bucket, list) else ():
                try:
                    seats.append(int(uuid))
                except (TypeError, ValueError):
                    continue
        out.append(tuple(seats))
    return tuple(out)


def seated_member_ids(balance_result_json: Mapping[str, Any] | None, variant_index: int) -> frozenset[int]:
    """Workspace member ids seated in ``variant_index`` of one lobby's document.

    Empty for a lobby that was never balanced and for an index past the stored
    options: both mean "nobody is playing this lobby", which is what every
    caller wants to hear. A seat uuid IS the member id -- the same mapping
    ``record_outcome`` freezes into ``casual.player`` -- and a uuid that is not
    one is skipped rather than failing the read.
    """
    return frozenset(member for team in seated_teams(balance_result_json, variant_index) for member in team)

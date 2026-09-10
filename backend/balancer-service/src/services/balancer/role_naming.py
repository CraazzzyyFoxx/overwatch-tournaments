"""Normalize tournament_balancer/dual-write roster role names to the canonical wire code.

``tournament_balancer`` (the native balancer engine) and the legacy dual-write path key
team rosters by the ``HeroClass`` display spelling (``Tank``/``Damage``/
``Support``/``Flex``), but callers have historically tolerated any case. This
is the single place that bridges those roster keys to the canonical
``tank``/``dps``/``support``/``flex`` slot code -- do not re-derive the
mapping locally.
"""

from __future__ import annotations

from shared.core.enums import HeroClass

__all__ = ("role_slot_code",)


def role_slot_code(role_name: str) -> str:
    """Best-effort HeroClass parse of a roster role name to its slot code.

    Falls back to a plain lowercase of the input for anything HeroClass does
    not recognize, mirroring the defensive behavior of the dict lookups this
    replaces -- never raises.
    """
    parsed = HeroClass.parse(role_name)
    return parsed.slot_code if parsed else role_name.lower()

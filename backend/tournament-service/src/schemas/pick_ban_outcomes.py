"""What a tournament's pick-ban rooms settled, for the public tournament pages: every hero ban a spectator may see
and every map picked or banned. The rooms themselves are still read through ``get_pick_ban_state``."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ("PickBanHeroBan", "PickBanMapOutcome", "TournamentPickBanOutcomes")


class PickBanHeroBan(BaseModel):
    """One banned hero of one ban submission."""

    encounter_id: int
    hero_id: int
    #: The ban step plays round 1 -- the series' first map (a flat sequence has only that one).
    first_map: bool
    #: The opponent roster player a per-player ban is spent on; null for a plain ban.
    target_player_id: int | None


class PickBanMapOutcome(BaseModel):
    """One map the map room picked or banned."""

    encounter_id: int
    map_id: int
    picked: bool


class TournamentPickBanOutcomes(BaseModel):
    hero_bans: list[PickBanHeroBan]
    map_outcomes: list[PickBanMapOutcome]

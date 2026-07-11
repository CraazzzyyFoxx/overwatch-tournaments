"""Kill-feed / event timeline read schemas for a single match.

Backed by the ``matches.kill_feed`` and ``matches.assists`` tables. Player
display names are intentionally NOT included — the client already has the full
roster (``user_id`` → name) from the match read and resolves them there, which
keeps this payload lean and the names consistent with the stats tables. Only the
hero *at the moment of the event* is joined (it can differ from the aggregate
roster hero), so the timeline shows the correct hero per kill.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.schemas.hero import HeroRead

__all__ = (
    "KillFeedEntry",
    "MatchTimelineEvent",
    "MatchKillFeedRead",
)


class KillFeedEntry(BaseModel):
    time: float
    round: int
    fight: int
    ability: str | None
    damage: float
    is_critical_hit: bool
    is_environmental: bool
    killer_user_id: int
    killer_team_id: int
    killer_hero: HeroRead
    victim_user_id: int
    victim_team_id: int
    victim_hero: HeroRead


class MatchTimelineEvent(BaseModel):
    """A non-kill timeline event (ultimate cast, resurrect) worth surfacing."""

    time: float
    round: int
    name: str
    user_id: int
    team_id: int
    hero: HeroRead | None
    related_user_id: int | None
    related_team_id: int | None


class MatchKillFeedRead(BaseModel):
    match_id: int
    kills: list[KillFeedEntry]
    events: list[MatchTimelineEvent]

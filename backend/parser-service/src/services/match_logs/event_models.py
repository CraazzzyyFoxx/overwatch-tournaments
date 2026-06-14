"""Typed Pydantic models for each match log event row.

Each model validates and coerces raw `data` list fields so the rest of
the pipeline works with attributes instead of positional magic indices.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core import enums


class _StrictBase(BaseModel):
    model_config = {"arbitrary_types_allowed": True, "extra": "ignore"}


class KillEvent(_StrictBase):
    """Parsed row for a `kill` log event.

    Raw field positions (cols 3+):
      0: attacker_team, 1: attacker, 2: attacker_hero,
      3: victim_team,   4: victim,   5: victim_hero,
      6: ability ("0" = none),
      7: damage,
      8: is_critical ("True"/"False"/"0"),
      9: is_environmental ("True"/"False"/"0")
    """

    attacker_team: str
    attacker: str
    attacker_hero: str
    victim_team: str
    victim: str
    victim_hero: str
    ability: enums.AbilityEvent | None
    damage: float
    is_critical_hit: bool
    is_environmental: bool

    @classmethod
    def from_data(cls, data: list[str]) -> "KillEvent":
        if len(data) < 10:
            raise ValueError(f"KillEvent: expected ≥10 fields, got {len(data)}: {data}")
        ability_raw = data[6]
        return cls(
            attacker_team=data[0],
            attacker=data[1],
            attacker_hero=data[2],
            victim_team=data[3],
            victim=data[4],
            victim_hero=data[5],
            ability=_parse_ability(ability_raw),
            damage=_parse_float(data[7], "damage"),
            is_critical_hit=data[8] == "True",
            is_environmental=data[9] == "True",
        )


class MatchEventRow(_StrictBase):
    """Parsed row for assist / ultimate / hero-swap events.

    Raw field positions (cols 3+):
      0: team, 1: player, 2: hero,
      3: related_hero (HeroSwap / EchoDuplicateStart only),
      4: related_player (MercyRez only),
      5: related_hero (MercyRez only)
    """

    team: str
    player: str
    hero: str
    related_hero: str | None = None
    related_player: str | None = None

    @classmethod
    def from_data(cls, data: list[str], event_type: enums.MatchEvent) -> "MatchEventRow":
        if len(data) < 3:
            raise ValueError(f"MatchEventRow: expected ≥3 fields for {event_type}, got {len(data)}: {data}")

        related_hero: str | None = None
        related_player: str | None = None

        if event_type in (enums.MatchEvent.HeroSwap, enums.MatchEvent.EchoDuplicateStart):
            related_hero = data[3] if len(data) > 3 and data[3] else None
        elif event_type == enums.MatchEvent.MercyRez:
            related_player = data[4] if len(data) > 4 and data[4] else None
            related_hero = data[5] if len(data) > 5 and data[5] else None

        return cls(
            team=data[0],
            player=data[1],
            hero=data[2] if len(data) > 2 and data[2] else "",
            related_hero=related_hero,
            related_player=related_player,
        )


class PlayerStatRow(_StrictBase):
    """Parsed row for a `player_stat` log event.

    Raw field positions (cols 3+):
      0: round_idx, 1: team, 2: player, 3: hero,
      4..N: stat values in order of `enums.log_stats_index_map`
    """

    round_idx: int
    team: str
    player: str
    hero: str
    stat_values: dict[enums.LogStatsName, float]

    @classmethod
    def from_data(cls, data: list[str]) -> "PlayerStatRow":
        if len(data) < 4:
            raise ValueError(f"PlayerStatRow: expected ≥4 fields, got {len(data)}: {data}")

        stat_values: dict[enums.LogStatsName, float] = {}
        for stat_name, col_idx in enums.log_stats_index_map.items():
            if col_idx >= len(data):
                stat_values[stat_name] = 0.0
                continue
            raw = data[col_idx]
            if "****" in raw:
                raw = "0"
            try:
                stat_values[stat_name] = float(raw)
            except ValueError:
                stat_values[stat_name] = 0.0

        return cls(
            round_idx=_parse_int(data[0], "round_idx"),
            team=data[1],
            player=data[2],
            hero=data[3],
            stat_values=stat_values,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_float(raw: str, field: str) -> float:
    try:
        return float(raw)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot parse float for '{field}': {raw!r}")


def _parse_int(raw: str, field: str) -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot parse int for '{field}': {raw!r}")


def _parse_ability(raw: str) -> enums.AbilityEvent | None:
    if not raw or raw == "0":
        return None
    try:
        return enums.AbilityEvent(raw)
    except ValueError:
        return None

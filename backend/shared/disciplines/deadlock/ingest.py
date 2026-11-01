"""deadlock-api ``/v1/matches/{id}/metadata`` -> ``owt.match/1``. Pure: the bytes and the catalog context only.

Teams ``team0`` (Hidden King) and ``team1`` (Archmother), placed by ``winning_team``; the map is always ``midtown``, the
mode is ``match_info.game_mode`` (1 ``normal``, 4 ``street_brawl``; any other ``n`` is handed on as ``mode-<n>`` so the
semantic validator rejects it; Street Brawl rounds are not kept). A participant is keyed ``p<player_slot>`` (1..12, what
``killer_player_slot`` names) and identified by its Steam account id. A player with ``account_id == 0`` (anonymous) is
dropped with its facts and every event naming it. A ``hero_id`` no catalog hero carries as ``attrs.deadlock_id`` is
handed on verbatim so the semantic validator reports it.

Facts, per player on the played hero: the top-level counters, the counters of the last ``stats[]`` sample and its souls
by ``gold_sources`` (gold plus orbs; ``souls_lost`` is ``gold_death_loss``).

Events (``stats.EVENT_TYPES`` says what each one is):

* ``kill`` per ``death_details`` entry, the dead player as target.
* ``purchase`` per ``items`` entry, ``data`` = ``item_id`` plus ``sold_t``/``imbued_ability_id`` when set. Abilities share
  the list with shop items; the asset's ``type`` tells them apart, so the reader does.
* ``snapshot`` per ``stats[]`` sample, ``data`` = ``SNAPSHOT_STATS``; ``lane`` per player with an ``assigned_lane``.
* ``objective`` per destroyed ``objectives`` entry (``destroyed_time_s`` 0 is "standing"), ``mid_boss`` per ``mid_boss``.
* From ``damage_matrix``, only its ``Damage`` stat type and only damage to players (slot 0 is everything else):
  ``damage`` per dealer and enemy from the ``Bullet``/``Ability``/``Melee``/``UnknownAbility`` buckets, and
  ``damage_source`` per dealer and named source. The two never add up to each other (the matrix files a hit under both),
  so each is read on its own.

A ``t`` past ``duration_s`` (a sample taken on the last tick) is pinned to it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from shared.core.social import SocialProvider
from shared.disciplines.deadlock.stats import GOLD_SOURCE_STATS, SNAPSHOT_STATS
from shared.disciplines.ingest import DecodeContext, DecodeError
from shared.schemas.match_doc import PROTOCOL, IngestIssue, MatchDoc, MatchDocError

__all__ = ("decode",)

MAP = "midtown"
#: deadlock ``ECitadelGameMode``; proto3 omits the default (0, invalid).
MODES = {1: "normal", 4: "street_brawl"}
TEAMS = ("team0", "team1")
_TOP_LEVEL = ("kills", "deaths", "assists", "net_worth", "last_hits", "denies", "level")
_LAST_SNAPSHOT = (
    "player_damage",
    "boss_damage",
    "player_healing",
    "player_damage_taken",
    "shots_hit",
    "shots_missed",
    "hero_bullets_hit",
    "hero_bullets_hit_crit",
    "self_healing",
    "teammate_healing",
    "player_barriering",
    "damage_absorbed",
    "damage_mitigated",
    "heal_prevented",
    "creep_kills",
    "neutral_kills",
)
#: ``CMsgMatchPlayerDamageMatrix.EStatType.k_eType_Damage``.
_DAMAGE = 0
#: The matrix's per-kind buckets: every hit is filed under one of them and, again, under its named source.
_BUCKETS = frozenset({"Bullet", "Ability", "Melee", "UnknownAbility"})


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _souls(last: dict[str, Any]) -> dict[str, float]:
    souls: dict[str, float] = defaultdict(float)
    for source in last.get("gold_sources") or []:
        code = GOLD_SOURCE_STATS.get(source.get("source"))
        if code is not None:
            souls[code] += (source.get("gold") or 0) + (source.get("gold_orbs") or 0)
    if _number(last.get("gold_death_loss")):
        souls["souls_lost"] = float(last["gold_death_loss"])
    return souls


def _damage(
    info: dict[str, Any], team_of: dict[str, str]
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    """Whole-match damage to enemy heroes: ``(dealer, enemy) -> amount`` from the buckets, ``(dealer, source)`` from names."""
    matrix = info.get("damage_matrix") or {}
    details = matrix.get("source_details") or {}
    names, kinds = details.get("source_name") or [], details.get("stat_type") or []
    to_enemy: dict[tuple[str, str], int] = defaultdict(int)
    by_source: dict[tuple[str, str], int] = defaultdict(int)
    for dealer in matrix.get("damage_dealers") or []:
        key = f"p{dealer.get('dealer_player_slot')}"
        if key not in team_of:
            continue
        for source in dealer.get("damage_sources") or []:
            index = source.get("source_details_index")
            if not isinstance(index, int) or index >= len(names) or index >= len(kinds) or kinds[index] != _DAMAGE:
                continue
            for hit in source.get("damage_to_players") or []:
                target = f"p{hit.get('target_player_slot')}"
                amount = (hit.get("damage") or [0])[-1]  # cumulative per sample: the last is the match total
                if target not in team_of or team_of[target] == team_of[key] or not amount:
                    continue
                if names[index] in _BUCKETS:
                    to_enemy[key, target] += amount
                else:
                    by_source[key, names[index]] += amount
    return to_enemy, by_source


def _document(info: dict[str, Any], ctx: DecodeContext) -> dict[str, Any]:
    heroes = {attrs["deadlock_id"]: code for code, attrs in ctx.attrs.items() if _number(attrs.get("deadlock_id"))}
    players = {f"p{int(player['player_slot'])}": player for player in info["players"] if int(player["account_id"]) > 0}
    team_of = {key: TEAMS[int(player["team"])] for key, player in players.items()}
    hero_of = {key: heroes.get(player["hero_id"], str(player["hero_id"])) for key, player in players.items()}
    duration = float(info["duration_s"])
    facts: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def by(key: str, t: float, kind: str, **fields: Any) -> None:
        events.append(
            {"t": min(t, duration), "type": kind, "actor": key, "actor_team": team_of[key], "entity": hero_of[key]}
            | fields
        )

    for key, player in players.items():
        samples = player.get("stats") or [{}]
        last = samples[-1]
        values = (
            {code: player.get(code) for code in _TOP_LEVEL}
            | {code: last.get(code) for code in _LAST_SNAPSHOT}
            | _souls(last)
        )
        facts.extend(
            {"participant": key, "entity": hero_of[key], "stat": code, "value": float(value)}
            for code, value in values.items()
            if _number(value)
        )
        for death in player.get("death_details") or []:
            killer = f"p{death.get('killer_player_slot')}"
            if killer not in players:  # an anonymous or non-player killer
                continue
            by(
                killer,
                float(death["game_time_s"]),
                "kill",
                target=key,
                target_team=team_of[key],
                related_entity=hero_of[key],
            )
        for item in player.get("items") or []:
            data = {"item_id": int(item["item_id"])}
            if item.get("sold_time_s"):
                data["sold_t"] = int(item["sold_time_s"])
            if item.get("imbued_ability_id"):
                data["imbued_ability_id"] = int(item["imbued_ability_id"])
            by(key, float(item["game_time_s"]), "purchase", data=data)
        for sample in samples:
            if _number(sample.get("time_stamp_s")):
                data = {code: sample[code] for code in SNAPSHOT_STATS if _number(sample.get(code))}
                by(key, float(sample["time_stamp_s"]), "snapshot", data=data)
        if player.get("assigned_lane"):
            by(key, 0.0, "lane", data={"lane": int(player["assigned_lane"])})

    to_enemy, by_source = _damage(info, team_of)
    for (dealer, target), amount in to_enemy.items():
        by(
            dealer,
            duration,
            "damage",
            target=target,
            target_team=team_of[target],
            related_entity=hero_of[target],
            data={"amount": amount},
        )
    for (dealer, source), amount in by_source.items():
        by(dealer, duration, "damage_source", data={"source": source, "amount": amount})

    for objective in info.get("objectives") or []:
        if not objective.get("destroyed_time_s"):
            continue
        owner = int(objective.get("team", 0))
        events.append(
            {
                "t": min(float(objective["destroyed_time_s"]), duration),
                "type": "objective",
                "actor_team": TEAMS[1 - owner],
                "target_team": TEAMS[owner],
                "data": {"objective": int(objective.get("team_objective_id", 0))},
            }
        )
    for boss in info.get("mid_boss") or []:
        events.append(
            {
                "t": min(float(boss["destroyed_time_s"]), duration),
                "type": "mid_boss",
                "actor_team": TEAMS[int(boss.get("team_killed", 0))],
                "target_team": TEAMS[int(boss.get("team_claimed", 0))],
            }
        )

    winner = info.get("winning_team")
    mode = int(info.get("game_mode", 0))
    return {
        "protocol": PROTOCOL,
        "discipline": ctx.discipline,
        "source": ctx.source,
        "hint": ctx.hint,
        "played_at": datetime.fromtimestamp(int(info["start_time"]), UTC),
        "duration_s": duration,
        "map": MAP,
        "mode": MODES.get(mode, f"mode-{mode}"),
        "teams": [
            {"key": team, "placement": None if winner not in (0, 1) else (1 if index == winner else 2)}
            for index, team in enumerate(TEAMS)
        ],
        "participants": [
            {
                "key": key,
                "team": team_of[key],
                "identity": {"provider": str(SocialProvider.STEAM), "id": str(int(player["account_id"]))},
            }
            for key, player in players.items()
        ],
        "facts": facts,
        "events": sorted(events, key=lambda event: event["t"]),
    }


def decode(raw: bytes, ctx: DecodeContext) -> MatchDoc:
    try:
        document = _document(json.loads(raw)["match_info"], ctx)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError) as exc:
        raise DecodeError("invalid_metadata", "The bytes are not deadlock-api match metadata") from exc
    try:
        return MatchDoc.model_validate(document)
    except ValidationError as exc:
        raise MatchDocError(
            [IngestIssue(list(error["loc"]), error["type"], error["msg"]) for error in exc.errors()]
        ) from None

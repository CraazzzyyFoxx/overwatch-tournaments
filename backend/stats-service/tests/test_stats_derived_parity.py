"""Backfill and baseline persistence with real database mutations (``impact_v2``).

The frozen-P3 golden (``fixtures/stats_derived_parity.json``) proves equality with the LEGACY implementation, which
cannot produce ``impact_v2`` values. What it still pins -- and what is compared here, exactly -- is everything the
impact formula never touches: the raw and character facts, the kill-feed event counts, the fight assignments, the
audit evidence and the score resolution. The MVP outputs (``performance*``, ``impact_*``, ``overperformance_*``,
``contrib_*``) are filtered out of both sides; their numbers are covered by ``test_overwatch_impact_scoring.py`` and by
the derive/backfill agreement test ``test_ow_derive_parity.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared import models
from shared.core import enums
from shared.core.impact import CONTRIBUTION_STATS, FORMULA_VERSION, IMPACT_FEATURES, RANK_QUINTILES
from shared.disciplines import discipline
from shared.disciplines.overwatch import baselines as baseline_module
from shared.disciplines.overwatch import impact_weights, rank_quintiles
from shared.disciplines.overwatch.backfill import BackfillService
from shared.models import AuditLog
from shared.repository.baselines import StatBaselineRepository
from shared.repository.stats import StatDefRepository
from shared.repository.stats_queries import player_facts, team_scores
from shared.services.stats_evidence import owner_scopes
from src.services.match_logs.objectiveless import resolve_encounter_maps

GOLDEN = Path(__file__).parent / "fixtures" / "stats_derived_parity.json"
EVENT_CODES = frozenset({"first_picks", "first_deaths", "ultimate_kills", "support_kills"})
IMPACT_CODES = frozenset(
    {
        "impact_points",
        "impact_rank",
        "overperformance_score",
        "overperformance_badge",
        *(stat.value for stat in CONTRIBUTION_STATS.values()),
    }
)
#: Codes the backfill rewrites at every non-character segment.
DERIVED_CODES = EVENT_CODES | IMPACT_CODES
#: Never compared with the legacy golden: the v1 numbers cannot be reproduced, the removed MVP is gone.
MVP_CODES = IMPACT_CODES | {"performance", "performance_points"}
#: What the frozen golden still pins of a match outcome.
RETAINED = ("kills_before", "kills_first", "kills_second", "first_result", "second_result")


def _json(value):
    """Representation only: preserve numbers, order, duplicates and nullness."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        assert value.tzinfo is not None
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {_json(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, "item"):
        return _json(value.item())
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _fact_key(row: dict) -> tuple:
    return (
        row["match_id"],
        row["user_id"],
        row["team_id"],
        row["round"],
        row["hero_id"] is not None,
        row["hero_id"] or 0,
        row["stat_code"],
    )


async def _facts(session: AsyncSession, match_ids: list[int]) -> list[dict]:
    stat = player_facts(discipline="overwatch").c
    rows = (
        (
            await session.execute(
                sa.select(
                    stat.match_id,
                    stat.player_id.label("user_id"),
                    stat.tournament_team_id.label("team_id"),
                    stat.segment.label("round"),
                    stat.entity_id.label("hero_id"),
                    stat.stat_code,
                    stat.value,
                ).where(stat.match_id.in_(match_ids))
            )
        )
        .mappings()
        .all()
    )
    return sorted((_json(dict(row)) for row in rows), key=_fact_key)


def _kills(rows, players) -> list[dict]:
    members = {row.workspace_member_id: row.user_id for row in players}
    teams = {row.encounter_team_id: row.team_id for row in players}
    records = [
        _json(
            {
                "match_id": row.match_id,
                "round": row.segment,
                "time": row.t,
                "fight": (row.data or {}).get("fight"),
                "killer_id": members.get(row.actor_member_id),
                "victim_id": members.get(row.target_member_id),
                "killer_hero_id": row.entity_id,
                "victim_hero_id": row.related_entity_id,
                "killer_team_id": teams.get(row.actor_team_id),
                "victim_team_id": teams.get(row.target_team_id),
                "ability": (row.data or {}).get("ability"),
                "damage": (row.data or {}).get("damage"),
                "is_critical_hit": (row.data or {}).get("is_critical_hit"),
                "is_environmental": (row.data or {}).get("is_environmental"),
            }
        )
        for row in rows
    ]
    return sorted(
        records, key=lambda row: (row["match_id"], row["time"], row["round"], json.dumps(row, sort_keys=True))
    )


async def _assert_match_audit(session, match_id, operation, *, unchanged):
    row = await session.scalar(
        sa.select(AuditLog)
        .where(
            AuditLog.entity_id == match_id,
            AuditLog.action == operation,
        )
        .order_by(AuditLog.id.desc())
    )
    assert row is not None
    before = row.before_json["stats_evidence"]
    after = row.after_json["stats_evidence"]
    expected = set(owner_scopes("match", (match_id,)))
    for envelope in (before, after):
        assert envelope["operation"] == operation
        assert {
            (state["owner_kind"], tuple(state["owner_key"]), state["subset"]) for state in envelope["states"]
        } == expected
    old = {state["subset"]: state for state in before["states"]}
    new = {state["subset"]: state for state in after["states"]}
    for subset in unchanged:
        assert old[subset] == new[subset]
    return row.id


async def _load_players(session: AsyncSession, match_id: int):
    """Every observed player of a match with the owning encounter team and its source team."""
    player, member, team = models.StatsMatchPlayer, models.WorkspaceMember, models.EncounterTeam
    return (
        await session.execute(
            sa.select(
                member.player_id.label("user_id"),
                player.workspace_member_id,
                player.encounter_team_id,
                team.team_id,
            )
            .select_from(player)
            .join(member, member.id == player.workspace_member_id)
            .join(team, team.id == player.encounter_team_id)
            .where(player.match_id == match_id)
        )
    ).all()


def _event_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["hero_id"] is None and row["stat_code"] in EVENT_CODES]


def _comparable(rows: list[dict]) -> list[dict]:
    """The facts the frozen golden pins: everything but the MVP outputs."""
    return [row for row in rows if row["stat_code"] not in MVP_CODES]


def _raw(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["stat_code"] not in DERIVED_CODES and row["stat_code"] not in MVP_CODES]


def _preserved_facts(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["hero_id"] is not None or row["stat_code"] not in DERIVED_CODES]


def _assert_derived_coverage(before: list[dict], after: list[dict]) -> None:
    """Every hero-less player/segment group receives exactly the four event counts, and the impact facts are
    internally consistent: a rank for every point, contributions and badge at segment 0 only, no duplicate."""
    groups = {
        (row["match_id"], row["user_id"], row["team_id"], row["round"])
        for row in _raw(before)
        if row["hero_id"] is None
    }
    derived = [row for row in after if row["hero_id"] is None and row["stat_code"] in DERIVED_CODES]
    keys = [(row["match_id"], row["user_id"], row["team_id"], row["round"], row["stat_code"]) for row in derived]
    assert len(keys) == len(set(keys)), "backfill duplicated a derived player/segment fact"
    events: dict[tuple, set[str]] = {}
    impact: dict[tuple, set[str]] = {}
    for row in derived:
        key = (row["match_id"], row["user_id"], row["team_id"], row["round"])
        (events if row["stat_code"] in EVENT_CODES else impact).setdefault(key, set()).add(row["stat_code"])
    assert events == dict.fromkeys(groups, EVENT_CODES), "backfill omitted a player/segment or event count"
    assert set(impact) <= groups
    for key, codes in impact.items():
        assert {"impact_points", "impact_rank"} <= codes, key
        if key[3] > 0:
            assert codes <= {"impact_points", "impact_rank", "overperformance_score"}, key
        else:
            assert {stat.value for stat in CONTRIBUTION_STATS.values()} <= codes, key


async def _baselines(session: AsyncSession) -> list[dict]:
    baseline, role, dimension, stat = models.StatsBaseline, models.CatalogRole, models.RoleDimension, models.StatDef
    rows = (
        (
            await session.execute(
                sa.select(
                    baseline.formula_version,
                    role.code.label("role"),
                    baseline.rank_bucket,
                    baseline.entity_id,
                    stat.code.label("stat"),
                    baseline.mean,
                    baseline.std,
                    baseline.meta,
                )
                .join(role, role.id == baseline.role_id)
                .join(dimension, dimension.id == role.dimension_id)
                .join(stat, stat.id == baseline.stat_id)
                .where(
                    dimension.discipline == "overwatch",
                    dimension.rated.is_(True),
                    stat.discipline == "overwatch",
                )
            )
        )
        .mappings()
        .all()
    )
    return sorted(
        (_json({**dict(row), "role": enums.HeroClass[row["role"]]}) for row in rows),
        key=lambda row: (row["formula_version"], row["role"], row["rank_bucket"], row["entity_id"] or 0, row["stat"]),
    )


def synthetic_inputs(hero_id: int) -> baseline_module.BaselineInputs:
    """Hand-built baseline inputs: 40 one-stint maps per role, thirty of the damage ones on ``hero_id``."""
    rng = np.random.default_rng(7)
    rows = []
    for role_index, role in enumerate(("tank", "damage", "support")):
        for i in range(40):
            match_id = role_index * 40 + i
            row = {
                "match_id": match_id,
                "player_id": match_id,
                "team_id": 1,
                "segment": 0,
                "hero": hero_id if role == "damage" and i < 30 else -match_id,
                "role": role,
                "seconds": 900.0,
                "killfeed": True,
                "played_at": datetime(2026, 10, 1, tzinfo=UTC),
            }
            row.update({feature: max(float(rng.normal(10.0, 3.0)), 0.0) * 1.5 for feature in IMPACT_FEATURES})
            rows.append(row)
    stints = pd.DataFrame(rows)
    return baseline_module.BaselineInputs(
        stints, {(int(m), int(m)): int(m) % RANK_QUINTILES for m in stints["match_id"]}
    )


async def seed_synthetic_baselines(session: AsyncSession, ids: dict[str, int]) -> int:
    """The production recompute (persistence, evidence, validation) over hand-built inputs; no data is scanned."""
    # The stat_defs of the current vocabulary (the contribution and badge codes) are projected at service start.
    await StatDefRepository().project_module(session, discipline("overwatch"))
    inputs = synthetic_inputs(ids["hero"])
    with (
        patch.object(impact_weights, "FITTED", True),
        patch.object(baseline_module, "load_baseline_inputs", AsyncMock(return_value=inputs)),
    ):
        count = await baseline_module.baseline_service.recompute(session, discipline="overwatch")
    return count


async def _backfill_case(session: AsyncSession, match_id: int, service: BackfillService) -> dict:
    before = await _facts(session, [match_id])
    players = await _load_players(session, match_id)
    kills_before = _kills(await service._load_kills(session, match_id), players)
    session.expire_all()

    first_result = await service.backfill_match(session, match_id)
    await session.commit()
    session.expire_all()
    after_first = await _facts(session, [match_id])
    first_kills = _kills(await service._load_kills(session, match_id), players)
    first_audit = await _assert_match_audit(
        session,
        match_id,
        "stats.derived_backfill",
        unchanged=("raw_facts", "event_body", "players", "team_scores"),
    )
    second_result = await service.backfill_match(session, match_id)
    await session.commit()
    session.expire_all()
    after_second = await _facts(session, [match_id])
    second_kills = _kills(await service._load_kills(session, match_id), players)
    assert (
        await _assert_match_audit(
            session,
            match_id,
            "stats.derived_backfill",
            unchanged=("raw_facts", "event_body", "players", "team_scores"),
        )
        == first_audit
    ), "an idempotent backfill must not append a false transition"
    assert first_result is True and second_result is True
    assert after_first == after_second, "backfill accumulates or changes semantic rows on rerun"
    assert first_kills == second_kills, "fight assignments did not persist idempotently"
    assert _raw(before) == _raw(after_first), "backfill changed a non-derived fact"
    assert _preserved_facts(before) == _preserved_facts(after_first), "backfill changed a character fact"
    _assert_derived_coverage(before, after_first)
    return _json(
        {
            "kills_before": kills_before,
            "kills_first": first_kills,
            "kills_second": second_kills,
            "first_result": first_result,
            "second_result": second_result,
            "facts_before": before,
            "facts_first": after_first,
            "facts_second": after_second,
        }
    )


async def _fight_boundaries(session: AsyncSession, ids: dict[str, int], service: BackfillService) -> dict:
    output = {}
    for name, rounds, self_kill in (
        ("gap_exactly_15_then_greater", (1, 1, 1), False),
        ("round_boundary", (1, 2, 2), False),
        ("self_kill", (1, 1, 1), True),
    ):
        transaction = await session.begin_nested()
        try:
            players = await _load_players(session, ids["match"])
            kills = sorted(await service._load_kills(session, ids["match"]), key=lambda row: row.t)
            assert len(kills) >= 3, "fight parity requires the shared three-kill fixture"
            for row, time, round_ in zip(kills[:3], (10.0, 25.0, 40.001), rounds, strict=True):
                row.t = time
                row.segment = round_
            if self_kill:
                kills[0].actor_member_id = kills[0].target_member_id
                kills[0].actor_team_id = kills[0].target_team_id
                kills[0].entity_id = kills[0].related_entity_id
            await session.flush()
            assert await service.backfill_match(session, ids["match"])
            await session.flush()
            session.expire_all()
            persisted = await service._load_kills(session, ids["match"])
            output[name] = {
                "kills": _kills(persisted, players),
                "derived": _event_rows(await _facts(session, [ids["match"]])),
            }
        finally:
            await transaction.rollback()
            session.expire_all()
    return output


async def _missing_roster(session: AsyncSession, ids: dict[str, int], service: BackfillService) -> dict:
    transaction = await session.begin_nested()
    try:
        await session.execute(
            sa.delete(models.Player).where(
                models.Player.team_id == ids["team_home"],
                models.Player.workspace_member_id == ids["member_removed"],
            )
        )
        before = await _facts(session, [ids["match"]])
        assert await service.backfill_match(session, ids["match"])
        await session.flush()
        session.expire_all()
        after = await _facts(session, [ids["match"]])
        # A historical participant is derived whatever the current roster says.
        _assert_derived_coverage(before, after)
        return _json({"derived": _event_rows(after)})
    finally:
        await transaction.rollback()
        session.expire_all()


async def _score_state(session: AsyncSession, encounter_id: int) -> dict:
    seats = (
        await session.scalars(sa.select(models.EncounterTeam).where(models.EncounterTeam.encounter_id == encounter_id))
    ).all()
    scores = team_scores(discipline="overwatch", stat_code="score")
    observed_rows = (
        await session.execute(
            sa.select(scores)
            .join(
                models.StatsMatch,
                models.StatsMatch.id == scores.c.match_id,
            )
            .join(models.EncounterGame, models.EncounterGame.id == models.StatsMatch.encounter_game_id)
            .where(models.EncounterGame.encounter_id == encounter_id)
            .order_by(scores.c.match_id, scores.c.encounter_team_id)
        )
    ).all()
    observed = []
    for row in observed_rows:
        if not observed or observed[-1]["match_id"] != row.match_id:
            observed.append({"match_id": row.match_id, "scores": []})
        # Native facts store FLOAT8; OW scores retain their integer semantic type.
        assert row.value.is_integer(), "fractional native OW score"
        observed[-1]["scores"].append({"encounter_team_id": row.encounter_team_id, "value": int(row.value)})
    encounter = await session.get(models.Encounter, encounter_id)
    assert encounter is not None
    games = (
        (
            await session.execute(
                sa.select(
                    models.EncounterGame.id,
                    models.EncounterGame.position,
                    models.EncounterGame.map_id,
                    models.EncounterGame.state,
                    models.EncounterGame.result_source,
                    models.EncounterGame.result_version,
                    models.EncounterGame.confirmed_at,
                )
                .where(models.EncounterGame.encounter_id == encounter_id)
                .order_by(models.EncounterGame.position)
            )
        )
        .mappings()
        .all()
    )
    game_scores = (
        (
            await session.execute(
                sa.select(
                    models.EncounterGameTeam.game_id,
                    models.EncounterGameTeam.encounter_team_id,
                    models.EncounterGameTeam.score,
                    models.EncounterGameTeam.placement,
                )
                .where(models.EncounterGameTeam.encounter_id == encounter_id)
                .order_by(models.EncounterGameTeam.game_id, models.EncounterGameTeam.encounter_team_id)
            )
        )
        .mappings()
        .all()
    )
    return _json(
        {
            "observed": observed,
            "official": {
                "encounter": {
                    key: getattr(encounter, key)
                    for key in ("id", "status", "result_status", "result_source", "result_version", "confirmed_at")
                },
                "seats": [
                    {
                        "id": seat.id,
                        "team_id": seat.team_id,
                        "slot": seat.slot,
                        "score": seat.score,
                        "placement": seat.placement,
                    }
                    for seat in sorted(seats, key=lambda row: row.id)
                ],
                "games": [dict(row) for row in games],
                "game_scores": [dict(row) for row in game_scores],
            },
        }
    )


async def _scores(session: AsyncSession, ids: dict[str, int]) -> dict:
    output = {}
    for name in ("ordinary", "accepted_reversed", "unknown"):
        transaction = await session.begin_nested()
        try:
            if name != "ordinary":
                push = await session.scalar(
                    sa.select(models.CatalogEntity).where(
                        models.CatalogEntity.discipline == "overwatch",
                        models.CatalogEntity.kind == "mode",
                        models.CatalogEntity.slug == "push",
                    )
                )
                map_ = await session.get(models.CatalogEntity, ids["map_other"])
                assert map_ is not None
                if push is not None:
                    map_.parent_id = push.id
                    # The resolver reads a match's own mode: move the map's observations along with it.
                    await session.execute(
                        sa.update(models.StatsMatch)
                        .where(models.StatsMatch.map_entity_id == map_.id)
                        .values(mode_entity_id=push.id)
                    )
                else:
                    # No duplicate seeder: change the existing fixture mode.
                    mode = await session.get(models.CatalogEntity, map_.parent_id)
                    assert mode is not None
                    mode.slug = "push"
            if name == "unknown":
                await session.execute(
                    sa.update(models.EncounterGameTeam)
                    .where(
                        models.EncounterGameTeam.game_id == ids["game_reversed"],
                    )
                    .values(score=None)
                )
            await session.flush()
            before = await _score_state(session, ids["encounter"])
            # P4's fixtures are raw Workshop observations: every job behind them is decoded input.
            producers = dict.fromkeys(await session.scalars(sa.select(models.IngestJob.id)), "decoded")
            changed = await resolve_encounter_maps(session, ids["encounter"], producers=producers)
            await session.flush()
            session.expire_all()
            after = await _score_state(session, ids["encounter"])
            if changed:
                await _assert_match_audit(
                    session,
                    ids["match_reversed"],
                    "stats.score_edit",
                    unchanged=("raw_facts", "event_body", "event_fight", "players"),
                )
            repeated = await resolve_encounter_maps(session, ids["encounter"], producers=producers)
            await session.flush()
            session.expire_all()
            after_repeat = await _score_state(session, ids["encounter"])
            assert before["official"] == after["official"] == after_repeat["official"], (
                "resolver mutated accepted results"
            )
            assert after == after_repeat and repeated is False
            if name == "accepted_reversed":
                assert changed, "objectiveless fixture did not exercise a real score write"
            output[name] = {
                "before": before,
                "changed": changed,
                "after": after,
                "changed_again": repeated,
                "after_repeat": after_repeat,
            }
        finally:
            await transaction.rollback()
            session.expire_all()
    return output


async def collect_outputs(session: AsyncSession, ids: dict[str, int]) -> dict:
    """Seed hand-built ``impact_v2`` baselines through the production recompute, then backfill the fixture matches."""
    await baseline_module.baseline_service.invalidate_cache(discipline="overwatch")
    recomputed = await seed_synthetic_baselines(session, ids)
    assert await baseline_module.baseline_service.get_active(session, discipline="overwatch") is not None
    output = {"baseline": {"recomputed": recomputed, "after": await _baselines(session)}, "matches": {}}
    unrelated_before = await _facts(session, [ids["match_other"], ids["match_hidden"]])
    service = BackfillService()
    for name in ("match", "match_reversed"):
        output["matches"][name] = await _backfill_case(session, ids[name], service)
    empty_before = await _facts(session, [ids["match_no_raw"]])
    output["no_facts"] = {
        "before": empty_before,
        "result": await service.backfill_match(session, ids["match_no_raw"]),
        "after": await _facts(session, [ids["match_no_raw"]]),
    }
    assert output["no_facts"]["result"] is False
    output["fight_boundaries"] = await _fight_boundaries(session, ids, service)
    output["missing_roster"] = await _missing_roster(session, ids, service)
    assert unrelated_before == await _facts(session, [ids["match_other"], ids["match_hidden"]]), (
        "targeted backfill touched another match"
    )
    output["scores"] = await _scores(session, ids)
    # The active set is cached process-wide; this database's hand-built set must not leak into the next test.
    await baseline_module.baseline_service.invalidate_cache(discipline="overwatch")
    return _json(output)


def _parity_view(output: dict) -> dict:
    """What the frozen legacy golden still pins; the MVP outputs and the legacy baselines are not compared."""
    return {
        "matches": {
            name: {
                key: _event_rows(value) if key.startswith("facts_") else value
                for key, value in result.items()
                if key.startswith("facts_") or key in RETAINED
            }
            for name, result in output["matches"].items()
        },
        "no_facts": {
            **output["no_facts"],
            "before": _comparable(output["no_facts"]["before"]),
            "after": _comparable(output["no_facts"]["after"]),
        },
        "fight_boundaries": {
            name: {"kills": result["kills"], "derived": _event_rows(result["derived"])}
            for name, result in output["fight_boundaries"].items()
        },
        "missing_roster": {"derived": _event_rows(output["missing_roster"]["derived"])},
        "scores": output["scores"],
    }


def _assert_exact(actual, expected, path=()) -> None:
    assert type(actual) is type(expected), f"{path}: {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), f"{path}: changed keys"
        for key in expected:
            _assert_exact(actual[key], expected[key], (*path, key))
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: changed length"
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            _assert_exact(left, right, (*path, index))
    elif isinstance(expected, float):
        assert actual.hex() == expected.hex(), f"{path}: {actual!r} != {expected!r}"
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def _canonical_expected() -> dict:
    """Apply only independently frozen, exact canonical-order witness cells."""
    original = GOLDEN.read_bytes()
    witness = json.loads(GOLDEN.with_name("stats_derived_canonical_order.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(original).hexdigest() == witness["provenance"]["golden_sha256"]
    assert witness["original_reproduced"] is True
    assert witness["input_multisets_equal"] is True
    assert witness["provenance"]["order"] == [
        "impact_baseline_totals.match_id ASC",
        "impact_baseline_totals.user_id ASC",
    ]
    expected = json.loads(original)
    seen = set()
    for path, old, canonical in witness["differences"]:
        assert tuple(path) not in seen
        seen.add(tuple(path))
        parent = expected
        for key in path[:-1]:
            parent = parent[key]
        _assert_exact(parent[path[-1]], old, tuple(path))
        assert type(old) is float and type(canonical) is float
        assert math.isfinite(old) and math.isfinite(canonical)
        assert old.hex() != canonical.hex()
        if path[0] == "baseline":
            assert path[-1] in {"mean", "std"} and (
                len(path) == 4
                and path[1] in {"built_rows", "after"}
                or len(path) == 5
                and path[1:3] == ["active", "values"]
            )
        elif path[0] == "matches" and path[2] in {"scored", "minimum_time"}:
            assert len(path) == 7 and path[4] == "records"
            assert path[-1] in {"impact_points", "overperformance_score"}
        else:
            assert (
                path[0] == "matches"
                and len(path) == 5
                and path[2] in {"objects", "facts_first", "facts_second"}
                or path[0] == "fight_boundaries"
                and len(path) == 5
                and path[2] == "derived"
                or path[0] == "missing_roster"
                and len(path) == 4
                and path[1] == "derived"
            )
            assert path[-1] == "value" and parent["hero_id"] is None
            assert parent["stat_code"] in {"impact_points", "overperformance_score"}
        parent[path[-1]] = canonical
    return expected


def assert_derived_parity(actual: dict) -> None:
    """Compare every retained field exactly; ordering policy is not a tolerance."""
    _assert_exact(_parity_view(actual), _parity_view(_canonical_expected()))


@pytest.mark.parametrize(
    ("path", "change"),
    [
        pytest.param(("matches", "match", "kills_first", 0, "ability"), "nonnull", id="event-nullness"),
        pytest.param(
            ("scores", "ordinary", "after", "observed", 0, "scores", 0, "value"), "increment", id="observed-score"
        ),
        pytest.param(
            ("scores", "ordinary", "after", "observed", 0, "scores", 0, "encounter_team_id"),
            "increment",
            id="participant-identity",
        ),
        pytest.param(("matches", "match", "kills_first"), "append", id="duplicate-event"),
        pytest.param(("matches", "match", "first_result"), "delete", id="missing-key"),
        pytest.param(("no_facts", "extra"), "add", id="extra-key"),
    ],
)
def test_derived_canonical_reference_rejects_unapproved_differences(path, change):
    actual = _canonical_expected()
    parent = actual
    for key in path[:-1]:
        parent = parent[key]
    key = path[-1]
    if change == "ulp":
        parent[key] = math.nextafter(parent[key], math.inf)
    elif change == "increment":
        parent[key] += 1
    elif change == "nonnull":
        assert parent[key] is None
        parent[key] = ""
    elif change == "append":
        parent[key].append(parent[key][0])
    elif change == "delete":
        del parent[key]
    else:
        assert change == "add"
        parent[key] = None
    with pytest.raises(AssertionError):
        assert_derived_parity(actual)


def test_derived_canonical_reference_rejects_a_changed_event_count_by_one_ulp():
    actual = _canonical_expected()
    row = next(row for row in actual["matches"]["match"]["facts_first"] if row["stat_code"] in EVENT_CODES)
    row["value"] = math.nextafter(row["value"], math.inf)
    with pytest.raises(AssertionError):
        assert_derived_parity(actual)


def test_the_mvp_outputs_are_not_part_of_the_comparison():
    actual = _canonical_expected()
    for result in actual["matches"].values():
        for row in result["facts_first"]:
            if row["stat_code"] in {"impact_points", "overperformance_score"}:
                row["value"] += 1.0
    assert_derived_parity(actual)


async def _lol_state(session: AsyncSession, ids: dict[str, int]) -> dict:
    # Native-only import: kept local so the module stays importable on the legacy clone.
    from shared.models.stats.match import StatsBaseline, StatsEvent, StatsFact

    output = {}
    for name, table, predicate in (
        ("facts", StatsFact.__table__, StatsFact.match_id == ids["match_lol"]),
        ("events", StatsEvent.__table__, StatsEvent.match_id == ids["match_lol"]),
        ("baseline", StatsBaseline.__table__, StatsBaseline.id == ids["baseline_lol"]),
    ):
        rows = (await session.execute(sa.select(table).where(predicate))).mappings().all()
        assert rows, f"missing shared native LoL sentinel: {name}"
        output[name] = sorted((_json(dict(row)) for row in rows), key=lambda row: json.dumps(row, sort_keys=True))
    return output


@pytest.mark.parametrize(
    ("actual", "expected"),
    [(0.0, -0.0), (1.0, 1), (True, 1), (False, None)],
    ids=["signed-zero", "float-integer", "boolean-integer", "boolean-null"],
)
def test_derived_exact_comparison_preserves_numeric_types_and_signed_zero(actual, expected):
    with pytest.raises(AssertionError):
        _assert_exact(actual, expected)


async def _assert_native_slots(session: AsyncSession, ids: dict[str, int]) -> None:
    from shared.models.stats.match import StatsMatchTeam

    rows = (
        await session.execute(
            sa.select(
                StatsMatchTeam.match_id,
                StatsMatchTeam.encounter_team_id,
                StatsMatchTeam.source_position,
                models.EncounterTeam.slot,
            )
            .join(models.EncounterTeam, models.EncounterTeam.id == StatsMatchTeam.encounter_team_id)
            .where(StatsMatchTeam.match_id.in_([ids["match"], ids["match_reversed"]]))
        )
    ).all()
    assert {tuple(row) for row in rows} == {
        (ids["match"], ids["encounter_team_home"], 1, 1),
        (ids["match"], ids["encounter_team_away"], 2, 2),
        (ids["match_reversed"], ids["encounter_team_home"], 2, 1),
        (ids["match_reversed"], ids["encounter_team_away"], 1, 2),
    }


def test_native_backfill_preserves_the_frozen_outputs_without_overwriting_characters_or_raw_facts(
    stats_parity_database,
):
    url, ids = stats_parity_database

    async def compare() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                actual = await collect_outputs(session, ids)
                assert_derived_parity(actual)
                for result in actual["matches"].values():
                    assert _preserved_facts(result["facts_before"]) == _preserved_facts(result["facts_first"])
                    assert result["facts_first"] == result["facts_second"]
                await _assert_native_slots(session, ids)
        finally:
            await engine.dispose()

    asyncio.run(compare())


def test_baseline_inputs_load_a_bounded_window_with_the_documented_shape(stats_parity_database):
    url, ids = stats_parity_database

    async def load() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                inputs = await baseline_module.load_baseline_inputs(
                    session, discipline="overwatch", since=None, max_matches=5
                )
                stints = inputs.stints
                assert not stints.empty
                assert {"match_id", "team_id", "player_id", "segment", "hero", "role", "seconds", "killfeed"} <= set(
                    stints.columns
                )
                assert set(IMPACT_FEATURES) <= set(stints.columns)
                assert set(stints["segment"]) == {0} and (stints["seconds"] > 0).all()
                assert stints["match_id"].nunique() <= 5
                assert set(inputs.quintiles) <= set(zip(stints["match_id"], stints["player_id"], strict=True))
                assert all(0 <= quintile < RANK_QUINTILES for quintile in inputs.quintiles.values())
                # Both rank loaders run their SQL: the tournament owner of the fixture has ranked rosters, no mix exists.
                values: dict = {}
                population: dict = defaultdict(list)
                await rank_quintiles._tournament_values(session, {ids["tournament"]}, values, population)
                assert values and {owner for owner, _, _ in values} == {("tournament", ids["tournament"])}
                assert {role for _, _, role in values} <= {"tank", "damage", "support"}
                # A role's pool holds only the members rostered in that role, never another role's fallback rank.
                rostered = Counter(
                    (
                        await session.execute(
                            sa.select(models.Player.role)
                            .where(models.Player.tournament_id == ids["tournament"], models.Player.rank.is_not(None))
                            .distinct(models.Player.workspace_member_id)
                            .order_by(
                                models.Player.workspace_member_id,
                                models.Player.is_substitution.asc(),
                                models.Player.id.desc(),
                            )
                        )
                    ).scalars()
                )
                owner = ("tournament", ids["tournament"])
                assert {role: len(population[(owner, role)]) for role in rostered} == dict(rostered)
                await rank_quintiles._mix_values(session, {ids["tournament"]}, values, population)
                assert await rank_quintiles.match_quintiles(session, []) == {}
                none = await baseline_module.load_baseline_inputs(
                    session, discipline="lol", since=datetime(2100, 1, 1, tzinfo=UTC)
                )
                assert none.stints.empty and none.quintiles == {}
        finally:
            await engine.dispose()

    asyncio.run(load())


def test_recompute_is_refused_until_the_weights_are_fitted_and_never_wipes_on_zero_rows(stats_parity_database):
    url, ids = stats_parity_database

    async def run() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        service = baseline_module.baseline_service
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with (
                    patch.object(impact_weights, "FITTED", False),
                    pytest.raises(RuntimeError, match="not fitted"),
                ):
                    await service.recompute(session, discipline="overwatch")
                await seed_synthetic_baselines(session, ids)
                before = await _baselines(session)
                assert before
                empty = baseline_module.BaselineInputs(synthetic_inputs(ids["hero"]).stints.iloc[0:0], {})
                with (
                    patch.object(impact_weights, "FITTED", True),
                    patch.object(baseline_module, "load_baseline_inputs", AsyncMock(return_value=empty)),
                    pytest.raises(RuntimeError, match="refusing to wipe"),
                ):
                    await service.recompute(session, discipline="overwatch")
                assert await _baselines(session) == before
                current = [row for row in before if row["formula_version"] == FORMULA_VERSION]
                assert {row["entity_id"] for row in current if row["entity_id"] is not None} == {ids["hero"]}
                assert {(row["meta"]["window_days"], row["meta"]["max_matches"]) for row in current} == {(365, 5000)}
                await service.invalidate_cache(discipline="overwatch")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_overwatch_baselines_and_backfill_preserve_native_lol_sentinel(stats_parity_database):
    from shared.testing.stats_parity import seed_native_sentinel

    url, ids = stats_parity_database

    async def compare() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                service = baseline_module.baseline_service
                await service.invalidate_cache(discipline="overwatch")
                before_count = await seed_synthetic_baselines(session, ids)
                before_active = await service.get_active(session, discipline="overwatch")
                assert before_active is not None and before_active.badge_threshold is not None
                assert any(hero == ids["hero"] for _, hero, _ in before_active.stats if hero is not None)
                await session.run_sync(lambda sync: seed_native_sentinel(sync.connection(), ids))
                await session.commit()
                lol_before = await _lol_state(session, ids)
                ow_before = await _baselines(session)
                active_row = await session.scalar(
                    sa.select(models.StatsBaseline)
                    .join(
                        models.StatDef,
                        models.StatDef.id == models.StatsBaseline.stat_id,
                    )
                    .where(
                        models.StatDef.discipline == "overwatch",
                        models.StatsBaseline.formula_version == FORMULA_VERSION,
                    )
                )
                assert active_row is not None
                for role_id, stat_id, entity_id in (
                    (ids["role_lol"], active_row.stat_id, None),
                    (active_row.role_id, ids["stat_lol_hero_damage_dealt"], None),
                    (active_row.role_id, active_row.stat_id, ids["hero_lol"]),
                    (active_row.role_id, active_row.stat_id, ids["map_other"]),
                ):
                    with pytest.raises(ValueError):
                        await StatBaselineRepository().replace_for_version(
                            session,
                            FORMULA_VERSION,
                            [
                                models.StatsBaseline(
                                    formula_version=FORMULA_VERSION,
                                    role_id=role_id,
                                    stat_id=stat_id,
                                    entity_id=entity_id,
                                    rank_bucket=-1,
                                    mean=1.0,
                                    std=1.0,
                                )
                            ],
                            discipline="overwatch",
                        )
                assert await _baselines(session) == ow_before
                assert await _lol_state(session, ids) == lol_before
                assert await BackfillService().backfill_match(session, ids["match_lol"]) is False
                await service.invalidate_cache(discipline="overwatch")
                assert await seed_synthetic_baselines(session, ids) == before_count
                assert await service.get_active(session, discipline="overwatch") == before_active
                backfill = BackfillService()
                for name in ("match", "match_reversed"):
                    assert await backfill.backfill_match(session, ids[name])
                    await session.commit()
                assert await _lol_state(session, ids) == lol_before
                # The sentinel has only an inactive formula. An OW cache entry
                # must not masquerade as LoL's active baseline set.
                assert await service.get_active(session, discipline="lol") is None
                assert await service.get_active(session, discipline="overwatch") == before_active
                await service.invalidate_cache(discipline="overwatch")
        finally:
            await engine.dispose()

    asyncio.run(compare())

"""Frozen P4 Overwatch parser reference for P5 decoder parity.

`fixtures/ow_decoder_reference/` holds the original Workshop bytes (`workshop.csv`), the observations the
completed-P4 parser path (`flows.process_match_log` -> `MatchLogProcessor.start`, real PostgreSQL, the same
`environment`/`upload`/`process` harness as `test_stats_ingest_db.py`) wrote for them (`expected.json`), and a
`manifest.json` binding both to a SHA-256 and the source HEAD.

* `test_reference_is_intact` runs in the normal suite and needs no database.

The reference is frozen legacy output (``impact_v1`` + the legacy ``performance`` MVP): the capture harnesses below can
no longer be run against the repository (the P4 path they drive is gone) and are kept as the record of how the files
were made. The decoder parity test compares everything but the MVP facts.
* `test_capture_p4_reference` is a recapture harness and is skipped unless `P5_CAPTURE_OW_REFERENCE=1`. It must
  only be run against the P4 parser (the P5 decoder replaces it); never regenerate expected output with a decoder
  under test. Task 3's parity test reads `expected.json`; it never calls this module.

Observations are keyed by participant handle and team `source_position` (home=1, away=2), never by database ids.
Every float is stored as its IEEE-754 big-endian hex plus the decimal value, so signed zero and the last ulp
are comparable exactly. Events are a canonically sorted multiset (duplicates kept); P4's insertion order
(kills first, then other events) is not part of the contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa

from shared import models
from shared.core.enums import LogStatsName
from shared.core.impact import IMPACT_FEATURES
from shared.repository.baselines import StatBaselineRepository
from shared.repository.roles import CatalogRoleRepository
from shared.repository.stats import StatDefRepository
from tests.test_stats_ingest_db import STATUS, environment, process, upload

DIRECTORY = Path(__file__).parent / "fixtures" / "ow_decoder_reference"
RAW, EXPECTED, MANIFEST = DIRECTORY / "workshop.csv", DIRECTORY / "expected.json", DIRECTORY / "manifest.json"
CAPTURE_COMMAND = (
    "cd backend/stats-service && export POSTGRES_DB=anak_test POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 "
    "POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres && P5_CAPTURE_OW_REFERENCE=1 "
    "uv run pytest tests/test_ow_decoder_reference_capture.py -k capture -s"
)
SECOND_HERO = {"slug": "ingest-reaper", "name": "Ingest Reaper", "attrs": {"class": "damage"}}
BASELINES = DIRECTORY / "baselines.json"
EXTRA_COMMAND = CAPTURE_COMMAND.replace("P5_CAPTURE_OW_REFERENCE=1", "P5_CAPTURE_OW_REFERENCE=extra").replace(
    "-k capture", "-k extra"
)
#: Captures beyond the base log, all through the same unchanged P4 path with baselines seeded. ``users`` are added to
#: the capture database before upload (``team`` index into the home/away teams = roster row, ``None`` = a workspace
#: member with no roster row); ``ranks`` overrides the roster rank the P4 formulas read.
EXTRA_CASES = {
    "echo_substitution": {
        "raw": "cases/echo_substitution.csv",
        "users": [{"name": "IngestH3", "team": 0, "rank": 800}, {"name": "IngestSub", "team": None}],
        "ranks": {"IngestA0": 1200, "IngestA1": 1200, "IngestA2": 1200, "IngestH0": 500},
    },
    "impact": {"raw": "workshop.csv", "users": [], "ranks": {"IngestA0": 1200, "IngestH0": 500, "IngestH1": 950}},
    "no_killfeed": {"raw": "cases/no_killfeed.csv", "users": [], "ranks": {"IngestA1": 1200, "IngestH2": 600}},
    #: Home players join in reverse account-creation order and tie on every stat (P4 broke the tie by user id); an
    #: event is recorded after the match_end time.
    "performance_ties": {"raw": "cases/performance_ties.csv", "users": [], "ranks": {}},
}
#: Per-10-minute (mean, std) of the capture cohort per impact stat; roles/buckets scale them so no cell is constant.
_BASELINE_SCALE = {
    "Eliminations": (20.0, 10.0),
    "FinalBlows": (5.0, 3.0),
    "Deaths": (12.0, 6.0),
    "HeroDamageDealt": (6000.0, 3000.0),
    "HealingDealt": (2000.0, 2500.0),
    "DamageBlocked": (1500.0, 1000.0),
    "OffensiveAssists": (10.0, 5.0),
    "DefensiveAssists": (10.0, 5.0),
    "UltimatesUsed": (1.0, 1.0),
    "Multikills": (0.5, 1.0),
    "SoloKills": (3.0, 2.0),
    "ObjectiveKills": (0.2, 0.5),
    "EnvironmentalKills": (0.2, 0.5),
    "FirstPicks": (3.0, 2.0),
    "FirstDeaths": (3.0, 2.0),
    "UltimateKills": (1.0, 1.0),
    "SupportKills": (2.0, 2.0),
}


def baseline_spec() -> dict:
    """Deterministic non-trivial baseline cells (including std == 0) for every OW role, bucket and impact stat."""
    rows = []
    for role_index, role in enumerate(("tank", "damage", "support")):
        for bucket in (-1, 0, 1, 2):
            for stat_index, (name, (mean, std)) in enumerate(_BASELINE_SCALE.items()):
                zero = role == "support" and bucket == 0 and stat_index % 7 == 0
                rows.append(
                    {
                        "role": role,
                        "rank_bucket": bucket,
                        "stat": LogStatsName[name].value,
                        "mean": mean * (1 + 0.1 * bucket) * (1.1 - 0.1 * role_index),
                        "std": 0.0 if zero else std * (1 + 0.05 * (bucket + 2)) * (1 + 0.03 * role_index),
                    }
                )
    assert set(_BASELINE_SCALE) <= set(IMPACT_FEATURES)
    # The frozen legacy reference: ``impact_v1`` seeded through the P4 path, never the current formula version.
    return {"formula_version": "impact_v1", "bucket_bounds": [700.0, 900.0], "rows": rows}


async def seed_baselines(session, spec: dict) -> None:
    roles = await CatalogRoleRepository().rated_rows(session, discipline="overwatch", workspace_id=None)
    stat_ids = await StatDefRepository().ids(session, discipline="overwatch")
    meta = {"bucket_bounds": spec["bucket_bounds"], "n": 1000}
    await StatBaselineRepository().replace_for_version(
        session,
        spec["formula_version"],
        [
            models.StatsBaseline(
                formula_version=spec["formula_version"],
                role_id=roles[row["role"]].id,
                rank_bucket=row["rank_bucket"],
                stat_id=stat_ids[row["stat"]],
                mean=row["mean"],
                std=row["std"],
                meta=meta,
            )
            for row in spec["rows"]
        ],
        discipline="overwatch",
    )


async def prepare_case(env, session, case: dict, spec: dict) -> None:
    """The scenario around an extra capture; only the capture database changes, never the P4 path."""
    session.add(models.CatalogEntity(discipline="overwatch", kind="character", **SECOND_HERO))
    for user in case["users"]:
        person = models.User(name=user["name"])
        session.add(person)
        await session.flush()
        member = models.WorkspaceMember(workspace_id=env.workspace, player_id=person.id)
        session.add(member)
        handle = user["name"] + "#1234"
        session.add(
            models.SocialAccount(
                user_id=person.id,
                provider="battlenet",
                username=handle,
                username_normalized=handle.lower(),
                is_primary=True,
            )
        )
        await session.flush()
        if user["team"] is not None:
            roster = models.Player(
                tournament_id=env.tournament,
                workspace_member_id=member.id,
                team_id=env.teams[user["team"]],
                name=user["name"],
                rank=user["rank"],
            )
            session.add(roster)
            await session.flush()
            session.add(
                models.PlayerRole(
                    player_id=roster.id,
                    role_id=env.fixture_ids["role_support"],
                    dimension_id=env.fixture_ids["role_dimension"],
                )
            )
    await session.flush()
    for name, rank in case["ranks"].items():
        await session.execute(
            sa.update(models.Player)
            .where(models.Player.tournament_id == env.tournament, models.Player.name == name)
            .values(rank=rank)
        )
    await seed_baselines(session, spec)
    await session.commit()


def bits(value: float) -> dict:
    assert math.isfinite(value), value
    return {"value": value, "bits": struct.pack(">d", value).hex()}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.rstrip("\n")


async def observe(env) -> dict:
    async with env.sf() as session:
        match = await session.scalar(
            sa.select(models.StatsMatch).where(models.StatsMatch.encounter_game_id == env.game)
        )
        entity = dict((await session.execute(sa.select(models.CatalogEntity.id, models.CatalogEntity.slug))).all())
        stat = dict((await session.execute(sa.select(models.StatDef.id, models.StatDef.code))).all())
        kind = dict((await session.execute(sa.select(models.EventType.id, models.EventType.code))).all())
        role = dict((await session.execute(sa.select(models.CatalogRole.id, models.CatalogRole.code))).all())
        scoped = {"match_id": match.id}
        position = dict(
            (
                await session.execute(
                    sa.select(models.StatsMatchTeam.encounter_team_id, models.StatsMatchTeam.source_position).where(
                        models.StatsMatchTeam.match_id == match.id
                    )
                )
            ).all()
        )
        players = (
            await session.scalars(
                sa.select(models.StatsMatchPlayer).where(models.StatsMatchPlayer.match_id == match.id)
            )
        ).all()
        handle = {player.workspace_member_id: player.handle_snapshot for player in players}
        facts = (await session.scalars(sa.select(models.StatsFact).filter_by(**scoped))).all()
        events = (await session.scalars(sa.select(models.StatsEvent).filter_by(**scoped))).all()
        segments = (await session.scalars(sa.select(models.StatsSegment).filter_by(**scoped))).all()

    def who(member, team):
        return {"team_position": position.get(team), "handle": handle.get(member)}

    fact_rows = sorted(
        (
            {
                "segment": fact.segment,
                "team_position": position[fact.encounter_team_id],
                "handle": handle.get(fact.workspace_member_id),
                "hero": entity.get(fact.entity_id),
                "stat": stat[fact.stat_id],
                **bits(fact.value),
            }
            for fact in facts
        ),
        key=lambda row: (row["segment"], row["team_position"], row["handle"] or "", row["hero"] or "", row["stat"]),
    )
    event_rows = sorted(
        (
            {
                "segment": event.segment,
                "t": bits(event.t),
                "type": kind[event.type_id],
                "actor": who(event.actor_member_id, event.actor_team_id),
                "target": who(event.target_member_id, event.target_team_id),
                "hero": entity.get(event.entity_id),
                "related_hero": entity.get(event.related_entity_id),
                "data": event.data,
            }
            for event in events
        ),
        key=lambda row: json.dumps(row, sort_keys=True),
    )
    return {
        "match": {
            "map": entity[match.map_entity_id],
            "revision": match.revision,
            "duration_s": bits(match.duration_s),
        },
        "segments": sorted(({"segment": s.segment, "kind": s.kind} for s in segments), key=lambda s: s["segment"]),
        "team_scores": {
            str(row["team_position"]): {"value": row["value"], "bits": row["bits"]}
            for row in fact_rows
            if row["stat"] == "score" and row["segment"] == 0 and row["handle"] is None
        },
        "players": {
            player.handle_snapshot: {
                "team_position": position[player.encounter_team_id],
                "observed_role": role.get(player.observed_role_id),
            }
            for player in sorted(players, key=lambda p: p.handle_snapshot)
        },
        "facts": fact_rows,
        "events": event_rows,
    }


@pytest.mark.skipif(
    os.environ.get("P5_CAPTURE_OW_REFERENCE") != "1", reason="recapture harness: set P5_CAPTURE_OW_REFERENCE=1"
)
def test_capture_p4_reference(stats_parity_database, monkeypatch):
    import asyncio

    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            async with env.sf() as session:
                session.add(models.CatalogEntity(discipline="overwatch", kind="character", **SECOND_HERO))
                await session.commit()
            raw = RAW.read_bytes()
            job = await upload(env, raw, filename="workshop.csv")
            assert await process(env, job.id) == STATUS.DONE
            return await observe(env)

    expected = asyncio.run(run())
    raw = RAW.read_bytes()
    EXPECTED.write_bytes((json.dumps(expected, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode())
    root = _git("rev-parse", "--show-toplevel")
    MANIFEST.write_bytes(
        (
            json.dumps(
                {
                    "cases": json.loads(MANIFEST.read_bytes()).get("cases", {}) if MANIFEST.exists() else {},
                    "source_head": _git("rev-parse", "HEAD"),
                    "uncommitted_paths_at_capture": _git(
                        "-C", root, "status", "--porcelain", "--", "backend/stats-service/src", "backend/shared"
                    ).splitlines(),
                    "capture_command": CAPTURE_COMMAND,
                    "parser_path": "src.services.match_logs.flows.process_match_log -> MatchLogProcessor.start",
                    "raw": {"file": RAW.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
                    "expected": {"file": EXPECTED.name, "sha256": hashlib.sha256(EXPECTED.read_bytes()).hexdigest()},
                    "second_catalog_hero": SECOND_HERO,
                    "counts": {
                        "facts": len(expected["facts"]),
                        "events": len(expected["events"]),
                        "players": len(expected["players"]),
                    },
                },
                indent=1,
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )
    print(
        f"captured {len(expected['facts'])} facts, {len(expected['events'])} events, {len(expected['players'])} players"
    )


@pytest.mark.skipif(
    os.environ.get("P5_CAPTURE_OW_REFERENCE") != "extra", reason="recapture harness: set P5_CAPTURE_OW_REFERENCE=extra"
)
@pytest.mark.parametrize("name", list(EXTRA_CASES))
def test_capture_p4_extra_references(stats_parity_database, monkeypatch, name):
    """Echo/objective/substitution rows and impact metrics, captured through the unchanged P4 path (before P5 moved
    the decoder). The base case's files are never touched here."""
    import asyncio

    spec, case = baseline_spec(), EXTRA_CASES[name]

    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            async with env.sf() as session:
                await prepare_case(env, session, case, spec)
            job = await upload(env, (DIRECTORY / case["raw"]).read_bytes(), filename=Path(case["raw"]).name)
            assert await process(env, job.id) == STATUS.DONE
            return await observe(env)

    expected = asyncio.run(run())
    target = DIRECTORY / "cases" / f"{name}.expected.json"
    target.write_bytes((json.dumps(expected, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode())
    raw = (DIRECTORY / case["raw"]).read_bytes()
    BASELINES.write_bytes((json.dumps(spec, indent=1, sort_keys=True) + "\n").encode())
    manifest = json.loads(MANIFEST.read_bytes())
    shared = manifest.setdefault("cases", {})
    shared.update(
        {
            "baselines": {"file": BASELINES.name, "sha256": hashlib.sha256(BASELINES.read_bytes()).hexdigest()},
            "capture_command": EXTRA_COMMAND,
            "source_head": _git("rev-parse", "HEAD"),
            "uncommitted_paths_at_capture": _git(
                "-C",
                _git("rev-parse", "--show-toplevel"),
                "status",
                "--porcelain",
                "--",
                "backend/stats-service/src",
                "backend/shared",
            ).splitlines(),
            "second_catalog_hero": SECOND_HERO,
        }
    )
    shared.setdefault("items", {})[name] = {
        "raw": {"file": case["raw"], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
        "expected": {"file": f"cases/{target.name}", "sha256": hashlib.sha256(target.read_bytes()).hexdigest()},
        "users": case["users"],
        "ranks": case["ranks"],
        "counts": {key: len(expected[key]) for key in ("facts", "events", "players")},
    }
    MANIFEST.write_bytes((json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode())
    print(name, shared["items"][name]["counts"])


def test_reference_is_intact():
    manifest = json.loads(MANIFEST.read_bytes())
    assert hashlib.sha256(RAW.read_bytes()).hexdigest() == manifest["raw"]["sha256"]
    assert hashlib.sha256(EXPECTED.read_bytes()).hexdigest() == manifest["expected"]["sha256"]
    expected = json.loads(EXPECTED.read_bytes())
    assert sorted(expected["team_scores"]) == ["1", "2"]
    assert expected["segments"] == [{"segment": n, "kind": "round"} for n in (1, 2)]

    def check(node):
        if isinstance(node, dict):
            if "bits" in node:
                assert struct.pack(">d", node["value"]).hex() == node["bits"]
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)

    check(expected)


def test_extra_references_are_intact():
    cases = json.loads(MANIFEST.read_bytes())["cases"]
    assert hashlib.sha256(BASELINES.read_bytes()).hexdigest() == cases["baselines"]["sha256"]
    assert json.loads(BASELINES.read_bytes()) == baseline_spec()
    assert set(cases["items"]) == set(EXTRA_CASES)
    for name, item in cases["items"].items():
        assert hashlib.sha256((DIRECTORY / item["raw"]["file"]).read_bytes()).hexdigest() == item["raw"]["sha256"]
        expected = DIRECTORY / item["expected"]["file"]
        assert hashlib.sha256(expected.read_bytes()).hexdigest() == item["expected"]["sha256"], name
        facts = json.loads(expected.read_bytes())["facts"]
        assert {"impact_points", "overperformance_score", "impact_rank"} <= {fact["stat"] for fact in facts}, name

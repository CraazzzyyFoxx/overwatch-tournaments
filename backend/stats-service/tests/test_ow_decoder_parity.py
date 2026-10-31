"""The module decoder (+ ``derive_match``) reproduces what the P4 parser wrote, bit for bit -- but for the MVP.

``fixtures/ow_decoder_reference`` holds raw Workshop bytes and the observations the unchanged P4 path
(``flows.process_match_log``) persisted for them, keyed by handle and team ``source_position`` and stored as IEEE-754
hex (signed zero and the last ulp are compared). The decoder's document is projected into the same shape and compared
exactly: no tolerance. Events are a multiset; an empty ``data`` object is the same observation as no data.

The reference is frozen legacy output, so the MVP facts (``performance*``, ``impact_*``, ``overperformance_*``) are
filtered out of both sides: ``impact_v2`` replaced the legacy MVP and its numbers are pinned by
``test_overwatch_impact_scoring.py``. What is asserted about them here is their *shape* (``MVP_SHAPE`` tests): which
facts exist for whom at which segment.

Case inputs the P4 path read from the database are rebuilt here: the catalog names, the roster of each seat
(``manifest.cases.items.*.ranks``) and, for the derive cases, hand-built ``impact_v2`` baselines scaled from
``baselines.json``.
"""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.core.enums import HeroClass, LogStatsName
from shared.core.impact import CONTRIBUTION_STATS, FORMULA_VERSION
from shared.disciplines.ingest import BoundMatch, BoundParticipant, DecodeContext
from shared.disciplines.overwatch import baselines, impact, ingest
from shared.schemas.match_doc import MatchDoc, MatchSource

DIRECTORY = Path(__file__).parent / "fixtures" / "ow_decoder_reference"
MANIFEST = json.loads((DIRECTORY / "manifest.json").read_bytes())
CASES = MANIFEST["cases"]["items"]
#: What ``_seed`` + the second capture hero put in the catalog, in catalog id order.
CTX = DecodeContext(
    discipline="overwatch",
    source=MatchSource(kind="upload"),
    hint=None,
    received_at=datetime(2026, 10, 18, tzinfo=UTC),
    characters={"Ingest Ana": "ingest-ana", "Ана-инжест": "ingest-ana", "Ingest Reaper": "ingest-reaper"},
    maps={("Ingest Control", "Ingest Ilios"): "ingest-ilios", ("Ingest Control", "Илиос-инжест"): "ingest-ilios"},
    attrs={"ingest-ana": {"class": "support"}, "ingest-reaper": {"class": "damage"}},
)
#: Users in creation order (P4 broke rank ties by user id): the seed, then each case's added users.
SEEDED_USERS = ["IngestH0", "IngestH1", "IngestH2", "IngestA0", "IngestA1", "IngestA2", "IngestEventOnly"]
ROSTER_RANK = 800
CONTRIBUTIONS = {stat.value for stat in CONTRIBUTION_STATS.values()}
#: The facts the frozen legacy reference holds of the MVP and ``impact_v2`` replaced, plus the new ones: never compared.
MVP_STATS = {
    "performance",
    "performance_points",
    "impact_points",
    "impact_rank",
    "overperformance_score",
    "overperformance_badge",
    *CONTRIBUTIONS,
}
CATALOG = {"ingest-ana": (1, HeroClass.support), "ingest-reaper": (2, HeroClass.damage)}


def bits(value: float) -> dict:
    return {"value": value, "bits": struct.pack(">d", value).hex()}


def observation(doc: MatchDoc) -> dict:
    position = {team.key: index for index, team in enumerate(doc.teams, 1)}
    team_of = {person.key: person.team for person in doc.participants}

    def who(key: str | None) -> dict:
        return {"team_position": None if key is None else position[team_of[key]], "handle": key}

    facts = sorted(
        (
            {
                "segment": f.segment,
                "team_position": position[f.team if f.participant is None else team_of[f.participant]],
                "handle": f.participant,
                "hero": f.entity,
                "stat": f.stat,
                **bits(f.value),
            }
            for f in doc.facts
            if f.stat not in MVP_STATS
        ),
        key=lambda r: (r["segment"], r["team_position"], r["handle"] or "", r["hero"] or "", r["stat"]),
    )
    events = sorted(
        (
            {
                "segment": e.segment,
                "t": bits(e.t),
                "type": e.type,
                "actor": who(e.actor),
                "target": who(e.target),
                "hero": e.entity,
                "related_hero": e.related_entity,
                "data": e.data or None,
            }
            for e in doc.events
        ),
        key=lambda r: json.dumps(r, sort_keys=True),
    )
    return {
        "map": doc.map,
        "duration_s": bits(doc.duration_s),
        "segments": [{"segment": s.index, "kind": s.kind} for s in sorted(doc.segments, key=lambda s: s.index)],
        "team_scores": {
            str(r["team_position"]): {"value": r["value"], "bits": r["bits"]}
            for r in facts
            if r["stat"] == "score" and r["segment"] == 0 and r["handle"] is None
        },
        "players": {
            person.key: {
                "team_position": position[person.team],
                "observed_role": None if person.role is None else person.role.role,
            }
            for person in sorted(doc.participants, key=lambda p: p.key)
        },
        "facts": facts,
        "events": events,
    }


def assert_matches(doc: MatchDoc, expected: dict) -> None:
    actual = observation(doc)
    match = expected["match"]  # map and duration; its revision is a writer's counter, not an observation
    assert actual.pop("map") == match["map"]
    assert actual.pop("duration_s") == match["duration_s"]
    for section in ("segments", "team_scores", "players", "events"):
        assert actual[section] == expected[section], section
    wanted = [fact for fact in expected["facts"] if fact["stat"] not in MVP_STATS]
    assert len(actual["facts"]) == len(wanted)
    for got, want in zip(actual["facts"], wanted, strict=True):
        assert got == want, (got, want)


def baseline_set() -> impact.BaselineSet:
    """``impact_v2`` baselines at the capture cohort's scale: per-role rates from the all-rank cells, an identity role
    scale and a unit expectation."""
    spec = json.loads((DIRECTORY / "baselines.json").read_bytes())
    stats = {
        (row["role"], None, LogStatsName(row["stat"]).name): (row["mean"], row["std"])
        for row in spec["rows"]
        if row["rank_bucket"] == -1
    }
    roles = {role for role, _, _ in stats}
    return impact.BaselineSet(
        FORMULA_VERSION,
        stats,
        dict.fromkeys(roles, (0.0, 1.0)),
        {(role, -1): (0.0, 1.0) for role in roles},
        badge_threshold=0.0,
    )


def derive(decoded: MatchDoc, item: dict, monkeypatch, *, baselines_value) -> MatchDoc:
    """``derive_match`` with the baselines, hero catalog and rank quintiles (all of them 2) substituted."""

    async def quintiles(session, wanted):
        return {(encounter, member): 2 for encounter, member, _ in wanted}

    monkeypatch.setattr(baselines, "get_active", AsyncMock(return_value=baselines_value))
    monkeypatch.setattr(baselines, "hero_catalog", AsyncMock(return_value=CATALOG))
    monkeypatch.setattr(ingest, "match_quintiles", quintiles)
    return asyncio.run(ingest.derive_match(SimpleNamespace(), decoded, bind(decoded, item)))


def bind(doc: MatchDoc, item: dict) -> BoundMatch:
    """The P4 roster view of each seat: who played, whether a roster row gave them a role, and creation-order user ids."""
    users = SEEDED_USERS + [user["name"] for user in item["users"]]
    rosters = {user["name"]: user.get("rank", ROSTER_RANK) for user in item["users"] if user["team"] is not None}
    ranks = {**dict.fromkeys(SEEDED_USERS[:-1], ROSTER_RANK), **rosters, **item["ranks"]}
    seats = {}
    for person in doc.participants:
        handle = person.key
        # IngestSub is seated as a substitute for IngestH3 and takes the replaced starter's roster role.
        rostered = handle in ranks or handle == "IngestSub"
        seats[handle] = BoundParticipant(
            member_id=users.index(handle) + 1000,
            user_id=users.index(handle) + 1,
            encounter_team_id=100 if person.team == "home" else 200,
            role="support" if rostered else None,
        )
    return BoundMatch(workspace_id=1, encounter_id=2, encounter_game_id=3, participants=seats)


def test_base_case_decodes_without_any_mvp_fact_and_derives_nothing_without_baselines(monkeypatch):
    decoded = ingest.decode((DIRECTORY / "workshop.csv").read_bytes(), CTX)
    assert not [f for f in decoded.facts if f.stat in MVP_STATS], "the decoder emits no performance/MVP fact"
    doc = derive(decoded, {"users": [], "ranks": {}}, monkeypatch, baselines_value=None)
    assert doc.facts == decoded.facts
    assert_matches(doc, json.loads((DIRECTORY / "expected.json").read_bytes()))


@pytest.mark.parametrize("name", sorted(CASES))
def test_extra_cases_decode_and_derive_to_the_frozen_p4_observations(name, monkeypatch):
    item = CASES[name]
    decoded = ingest.decode((DIRECTORY / item["raw"]["file"]).read_bytes(), CTX)
    doc = derive(decoded, item, monkeypatch, baselines_value=baseline_set())

    assert_matches(doc, json.loads((DIRECTORY / item["expected"]["file"]).read_bytes()))
    # The decoder alone never carries the baseline dependent facts; derivation adds exactly the v2 ones.
    assert not [f for f in decoded.facts if f.stat in MVP_STATS]
    added = {f.stat for f in doc.facts} - {f.stat for f in decoded.facts}
    assert added == {"impact_points", "impact_rank", "overperformance_score", "overperformance_badge", *CONTRIBUTIONS}
    assert [f for f in doc.facts if f.stat not in MVP_STATS] == [f for f in decoded.facts if f.stat not in MVP_STATS]


@pytest.mark.parametrize("name", sorted(CASES))
def test_mvp_shape_scored_players_per_segment_and_the_map_only_breakdown(name, monkeypatch):
    item = CASES[name]
    decoded = ingest.decode((DIRECTORY / item["raw"]["file"]).read_bytes(), CTX)
    doc = derive(decoded, item, monkeypatch, baselines_value=baseline_set())

    def players(stat: str, segment: int) -> set[str]:
        return {f.participant for f in doc.facts if f.stat == stat and f.segment == segment}

    segments = {f.segment for f in doc.facts if f.stat == "impact_points"}
    assert segments == {0, *(s.index for s in doc.segments)}
    for segment in segments:
        scored = players("impact_points", segment)
        assert scored and players("impact_rank", segment) == scored
        ranks = [f.value for f in doc.facts if f.stat == "impact_rank" and f.segment == segment]
        assert min(ranks) == 1.0 and all(rank == int(rank) for rank in ranks)  # competition ranks, 1 = best
        # Every player has a quintile here, so every scored player has an overperformance.
        assert players("overperformance_score", segment) == scored
    map_scored = players("impact_points", 0)
    for stat in ("overperformance_badge", *sorted(CONTRIBUTIONS)):
        assert players(stat, 0) == map_scored, stat
        assert not [f for f in doc.facts if f.stat == stat and f.segment != 0], stat
    assert {f.value for f in doc.facts if f.stat == "overperformance_badge"} <= {0.0, 1.0}


def test_tied_players_share_an_impact_rank(monkeypatch):
    """Home players join as H2, H1, H0 yet tie on every stat: a competition rank gives them the same place."""
    item = CASES["performance_ties"]
    decoded = ingest.decode((DIRECTORY / item["raw"]["file"]).read_bytes(), CTX)
    assert [p.key for p in decoded.participants][:3] == ["IngestH2", "IngestH1", "IngestH0"]
    doc = derive(decoded, item, monkeypatch, baselines_value=baseline_set())
    ranks = {f.participant: f.value for f in doc.facts if f.stat == "impact_rank" and f.segment == 1}
    assert ranks["IngestH0"] == ranks["IngestH1"] == ranks["IngestH2"]
    # A decoded event after the recorded match end is kept, as P4 kept it.
    assert any(e.t > decoded.duration_s for e in decoded.events)


def test_the_comparison_distinguishes_signed_zero_and_the_last_ulp(monkeypatch):
    decoded = ingest.decode((DIRECTORY / "workshop.csv").read_bytes(), CTX)
    doc = derive(decoded, {"users": [], "ranks": {}}, monkeypatch, baselines_value=None)
    expected = json.loads((DIRECTORY / "expected.json").read_bytes())
    expected["facts"][0]["bits"] = "8000000000000000"  # -0.0 where 0.0/3.0 was captured
    with pytest.raises(AssertionError):
        assert_matches(doc, expected)

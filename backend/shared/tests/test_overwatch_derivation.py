"""``derive_match``: the baseline/rank-dependent ``impact_v2`` facts, DB-free (the baselines, hero catalog and rank
quintile reads are substituted).

The scoring maths is pinned in ``test_overwatch_impact_scoring.py``; here: which facts exist, for whom and at which
segment.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.core.enums import HeroClass
from shared.core.impact import CONTRIBUTION_STATS, FORMULA_VERSION, IMPACT_ROLES, PRIOR_WEIGHTS
from shared.disciplines.ingest import BoundMatch, BoundParticipant
from shared.disciplines.overwatch import baselines, impact, impact_weights, ingest
from shared.schemas.match_doc import MatchDoc

CONTRIBUTIONS = {stat.value for stat in CONTRIBUTION_STATS.values()}
DERIVED = {"impact_points", "impact_rank", "overperformance_score", "overperformance_badge", *CONTRIBUTIONS}
CATALOG = {"reaper": (7, HeroClass.damage), "mystery": (9, None)}


def baseline_set() -> impact.BaselineSet:
    return impact.BaselineSet(
        formula_version=FORMULA_VERSION,
        stats={
            ("damage", None, "Eliminations"): (10.0, 5.0),
            ("damage", None, "Deaths"): (5.0, 5.0),
            ("damage", None, "FirstPicks"): (0.0, 1.0),
        },
        role_scale={"damage": (0.0, 1.0)},
        expectation={("damage", 2): (0.0, 1.0)},
        badge_threshold=0.0,
    )


def fact(participant: str, stat: str, value: float, segment: int = 1, entity: str | None = "reaper") -> dict:
    return {"participant": participant, "stat": stat, "value": value, "segment": segment, "entity": entity}


def player_facts(participant: str, eliminations: float, deaths: float, seconds: float, hero: str = "reaper") -> list:
    return [
        fact(participant, stat, value, segment, hero)
        for segment in (1, 0)
        for stat, value in (("eliminations", eliminations), ("deaths", deaths), ("hero_time_played", seconds))
    ]


def document(*extra: dict, kill: bool = True, b_hero: str = "reaper", b_seconds: float = 600.0) -> MatchDoc:
    return MatchDoc.model_validate(
        {
            "protocol": "owt.match/1",
            "discipline": "overwatch",
            "source": {"kind": "upload"},
            "played_at": "2026-10-18T12:00:00Z",
            "duration_s": 700.0,
            "map": "ilios",
            "teams": [{"key": "home"}, {"key": "away"}],
            "participants": [
                {"key": key, "team": team, "identity": {"provider": "battlenet", "id": key.upper()}}
                for key, team in (("a", "home"), ("b", "away"))
            ],
            "segments": [{"index": 1, "kind": "round"}, {"index": 2, "kind": "round"}],
            "facts": [
                *player_facts("a", 20.0, 5.0, 600.0),
                *player_facts("b", 5.0, 10.0, b_seconds, b_hero),
                *extra,
            ],
            "events": [
                {
                    "t": 5.0,
                    "type": "kill",
                    "actor": "a",
                    "target": "b",
                    "entity": "reaper",
                    "related_entity": b_hero,
                    "segment": 1,
                    "data": {"fight": 1},
                }
            ]
            if kill
            else [],
        }
    )


def binding(**overrides: BoundParticipant) -> BoundMatch:
    seat = {
        "a": BoundParticipant(member_id=1, user_id=101, encounter_team_id=10, role="damage"),
        "b": BoundParticipant(member_id=2, user_id=102, encounter_team_id=20, role="damage"),
    }
    return BoundMatch(workspace_id=1, encounter_id=2, encounter_game_id=3, participants={**seat, **overrides})


def derive(
    doc: MatchDoc, monkeypatch, *, baselines_value=None, bound: BoundMatch | None = None, quintiles=None
) -> MatchDoc:
    # The expectations below use the v1 weights (1.3 / -1.3 / 0.55), never the fitted ones a refit may change.
    monkeypatch.setattr(impact_weights, "IMPACT_WEIGHTS", {role: dict(PRIOR_WEIGHTS) for role in IMPACT_ROLES})
    monkeypatch.setattr(baselines, "get_active", AsyncMock(return_value=baselines_value))
    monkeypatch.setattr(baselines, "hero_catalog", AsyncMock(return_value=CATALOG))
    monkeypatch.setattr(
        ingest, "match_quintiles", AsyncMock(return_value={(2, 1): 2, (2, 2): 2} if quintiles is None else quintiles)
    )
    return asyncio.run(ingest.derive_match(SimpleNamespace(), doc, bound or binding()))


def derived(doc: MatchDoc, stat: str, segment: int = 1) -> dict[str, float]:
    return {f.participant: f.value for f in doc.facts if f.stat == stat and f.segment == segment}


def test_points_and_rank_are_emitted_per_segment_and_the_rest_only_for_the_map(monkeypatch):
    out = derive(document(), monkeypatch, baselines_value=baseline_set())

    # Eliminations z = +2 / -1, deaths z = 0 / +1 (weights 1.3 / -1.3), first pick on a: z = +1 (0.55); the role scale is
    # the identity and 10 minutes shrink by 10/13 with full time share.
    expected = {"a": (1.3 * 2.0 + 0.55) * 10 / 13, "b": (-1.3 - 1.3) * 10 / 13}
    for segment in (1, 0):
        assert derived(out, "impact_points", segment) == pytest.approx(expected)
        assert derived(out, "impact_rank", segment) == {"a": 1.0, "b": 2.0}
        assert derived(out, "overperformance_score", segment) == pytest.approx(expected)
    assert derived(out, "contrib_eliminations", segment=0) == pytest.approx(
        {"a": 1.3 * 2.0 * 10 / 13, "b": -1.3 * 10 / 13}
    )
    assert derived(out, "overperformance_badge", segment=0) == {"a": 1.0, "b": 0.0}
    for code in (*CONTRIBUTIONS, "overperformance_badge"):
        assert derived(out, code, segment=1) == {}, code
        assert set(derived(out, code, segment=0)) == {"a", "b"}, code


def test_without_a_rank_quintile_there_is_no_overperformance_and_no_badge(monkeypatch):
    out = derive(document(), monkeypatch, baselines_value=baseline_set(), quintiles={})
    assert derived(out, "overperformance_score", segment=0) == {}
    assert derived(out, "overperformance_badge", segment=0) == {}
    assert set(derived(out, "impact_points", segment=0)) == {"a", "b"}
    assert set(derived(out, "contrib_deaths", segment=0)) == {"a", "b"}


def test_the_quintile_is_read_for_the_dominant_role_of_each_bound_member(monkeypatch):
    quintiles = AsyncMock(return_value={})
    monkeypatch.setattr(ingest, "match_quintiles", quintiles)
    monkeypatch.setattr(baselines, "get_active", AsyncMock(return_value=baseline_set()))
    monkeypatch.setattr(baselines, "hero_catalog", AsyncMock(return_value=CATALOG))
    asyncio.run(ingest.derive_match(SimpleNamespace(), document(), binding()))
    assert sorted(quintiles.await_args.args[1]) == [(2, 1, "damage"), (2, 2, "damage")]


def test_without_baselines_nothing_is_derived_and_the_rest_is_untouched(monkeypatch):
    doc = document()
    assert derive(doc, monkeypatch, baselines_value=None) == doc


def test_deriving_twice_replaces_rather_than_appends(monkeypatch):
    once = derive(document(), monkeypatch, baselines_value=baseline_set())
    twice = derive(once, monkeypatch, baselines_value=baseline_set())
    assert sorted(twice.facts, key=repr) == sorted(once.facts, key=repr)
    assert sum(f.stat in DERIVED for f in twice.facts) == sum(f.stat in DERIVED for f in once.facts)


def test_a_player_without_a_hero_class_or_enough_playtime_gets_no_impact_facts(monkeypatch):
    classless = derive(document(b_hero="mystery"), monkeypatch, baselines_value=baseline_set())
    short = derive(document(b_seconds=30.0), monkeypatch, baselines_value=baseline_set())
    for out in (classless, short):
        assert not [f for f in out.facts if f.participant == "b" and f.stat in DERIVED]
        assert derived(out, "impact_rank") == {"a": 1.0}


def test_kill_feed_counts_enter_the_score_only_with_a_kill_feed(monkeypatch):
    with_feed = derive(document(), monkeypatch, baselines_value=baseline_set())
    without = derive(document(kill=False), monkeypatch, baselines_value=baseline_set())
    assert derived(without, "impact_points")["a"] == pytest.approx(1.3 * 2.0 * 10 / 13)
    assert derived(with_feed, "impact_points")["a"] > derived(without, "impact_points")["a"]


def test_hero_less_facts_alone_never_open_a_player_row(monkeypatch):
    out = derive(
        document(fact("b", "first_deaths", 1.0, segment=2, entity=None)), monkeypatch, baselines_value=baseline_set()
    )
    assert derived(out, "impact_points", segment=2) == {}


def test_a_participant_the_core_did_not_bind_is_refused(monkeypatch):
    partial = BoundMatch(workspace_id=1, encounter_id=2, encounter_game_id=3, participants={})
    with pytest.raises(ValueError, match="not bound"):
        derive(document(), monkeypatch, baselines_value=baseline_set(), bound=partial)

"""The deadlock-api metadata decoder: purchases, the damage matrix, objectives and souls of the kept players."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from shared.disciplines.deadlock.ingest import decode
from shared.disciplines.ingest import DecodeContext
from shared.schemas.match_doc import MatchSource

CTX = DecodeContext(
    discipline="deadlock",
    source=MatchSource(kind="deadlock_api", external_id="1"),
    hint=None,
    received_at=datetime(2026, 11, 1, tzinfo=UTC),
    characters={},
    maps={},
    attrs={"wraith": {"deadlock_id": 7}, "inferno": {"deadlock_id": 1}},
)


def _item(t: int, item_id: int, sold: int = 0, imbued: int = 0) -> dict:
    return {"game_time_s": t, "item_id": item_id, "upgrade_id": 1, "sold_time_s": sold, "flags": 0,
            "imbued_ability_id": imbued, "upgrade_info": 65536}  # fmt: skip


def _player(slot: int, account: int, team: int, hero: int, items: list[dict] | None = None, **extra: object) -> dict:
    return {"player_slot": slot, "account_id": account, "team": team, "hero_id": hero, "items": items or [], "kills": 1,
            **extra}  # fmt: skip


def _raw(players: list[dict], **info: object) -> bytes:
    match_info = {"start_time": 1793497893, "duration_s": 600, "game_mode": 1, "winning_team": 0, "players": players}
    return json.dumps({"match_info": match_info | info}).encode()


def test_the_winner_scores_one_and_an_undecided_match_records_no_score() -> None:
    players = [_player(1, 11, 0, 7), _player(2, 12, 1, 1)]

    def scores(winner: object) -> dict[str | None, float]:
        doc = decode(_raw(players, winning_team=winner), CTX)
        return {fact.team: fact.value for fact in doc.facts if fact.stat == "score"}

    assert scores(1) == {"team0": 0.0, "team1": 1.0}
    assert scores(0) == {"team0": 1.0, "team1": 0.0}
    assert scores(None) == {}


def test_purchases_keep_sold_and_imbued_only_when_set_and_drop_anonymous_buyers() -> None:
    raw = json.dumps(
        {
            "match_info": {
                "start_time": 1793497893,
                "duration_s": 600,
                "game_mode": 1,
                "winning_team": 0,
                "players": [
                    _player(1, 11, 0, 7, [_item(300, 84321454, sold=500, imbued=1999680326), _item(12, 1009965641)]),
                    _player(2, 0, 1, 1, [_item(20, 668299740)]),
                ],
            }
        }
    ).encode()

    doc = decode(raw, CTX)

    purchases = [
        (event.t, event.actor, event.actor_team, event.entity, event.data)
        for event in doc.events
        if event.type == "purchase"
    ]
    assert purchases == [
        (12.0, "p1", "team0", "wraith", {"item_id": 1009965641}),
        (300.0, "p1", "team0", "wraith", {"item_id": 84321454, "sold_t": 500, "imbued_ability_id": 1999680326}),
    ]


def test_damage_matrix_splits_buckets_from_named_sources_and_keeps_enemy_heroes_only() -> None:
    def hits(*pairs: tuple[int, list[int]]) -> list[dict]:
        return [{"target_player_slot": slot, "damage": damage} for slot, damage in pairs]

    matrix = {
        "sample_time_s": [300, 600],
        "source_details": {
            "source_name": ["Bullet", "citadel_weapon_wraith_set", "Ability", "citadel_ability_card_toss", "Bullet"],
            "stat_type": [0, 0, 0, 0, 3],  # the last is mitigation, not damage
        },
        "damage_dealers": [
            {
                "dealer_player_slot": 1,
                "damage_sources": [
                    # Cumulative per sample; slot 0 is non-hero damage, slot 3 a teammate, slot 4 anonymous.
                    {
                        "source_details_index": 0,
                        "damage_to_players": hits((2, [10, 40]), (0, [900]), (3, [5]), (4, [7])),
                    },
                    {"source_details_index": 1, "damage_to_players": hits((2, [10, 40]))},
                    {"source_details_index": 2, "damage_to_players": hits((2, [25]))},
                    {"source_details_index": 3, "damage_to_players": hits((2, [0, 25]), (0, [50]))},
                    {"source_details_index": 4, "damage_to_players": hits((2, [99]))},
                ],
            }
        ],
    }
    raw = _raw(
        [_player(1, 11, 0, 7), _player(2, 22, 1, 1), _player(3, 33, 0, 7), _player(4, 0, 1, 1)],
        damage_matrix=matrix,
    )

    doc = decode(raw, CTX)

    damage = [(e.actor, e.target, e.target_team, e.related_entity, e.data) for e in doc.events if e.type == "damage"]
    assert damage == [("p1", "p2", "team1", "inferno", {"amount": 65})]
    sources = {e.data["source"]: e.data["amount"] for e in doc.events if e.type == "damage_source"}
    assert sources == {"citadel_weapon_wraith_set": 40, "citadel_ability_card_toss": 25}
    assert all(e.t == 600.0 for e in doc.events if e.type in {"damage", "damage_source"})


def test_objectives_mid_boss_snapshots_lanes_and_souls() -> None:
    gold = [{"source": 2, "gold": 100, "gold_orbs": 40}, {"source": 9, "gold": 5}, {"source": 13, "gold": 7}]
    samples = [
        {"time_stamp_s": 180, "net_worth": 900, "kills": 0, "player_damage": 50, "gold_sources": []},
        # Sampled on the last tick, past ``duration_s``: pinned to the end.
        {"time_stamp_s": 601, "net_worth": 5000, "kills": 1, "shots_hit": 30, "gold_sources": gold,
         "gold_death_loss": 120},
    ]  # fmt: skip
    raw = _raw(
        [_player(1, 11, 0, 7, stats=samples, assigned_lane=4), _player(2, 22, 1, 1)],
        objectives=[
            {"team": 1, "team_objective_id": 3, "destroyed_time_s": 443},
            {"team": 0, "team_objective_id": 0, "destroyed_time_s": 0},  # still standing
        ],
        mid_boss=[{"team_killed": 0, "team_claimed": 1, "destroyed_time_s": 520}],
    )

    doc = decode(raw, CTX)

    by_type = {
        kind: [e for e in doc.events if e.type == kind] for kind in ("objective", "mid_boss", "snapshot", "lane")
    }
    assert [(e.t, e.actor_team, e.target_team, e.data) for e in by_type["objective"]] == [
        (443.0, "team0", "team1", {"objective": 3})
    ]
    assert [(e.t, e.actor_team, e.target_team) for e in by_type["mid_boss"]] == [(520.0, "team0", "team1")]
    assert [(e.t, e.data) for e in by_type["snapshot"]] == [
        (180.0, {"net_worth": 900, "kills": 0, "player_damage": 50}),
        (600.0, {"net_worth": 5000, "kills": 1}),
    ]
    assert [(e.actor, e.t, e.data) for e in by_type["lane"]] == [("p1", 0.0, {"lane": 4})]
    facts = {fact.stat: fact.value for fact in doc.facts if fact.participant == "p1"}
    assert (facts["shots_hit"], facts["souls_lane_creeps"], facts["souls_items"], facts["souls_lost"]) == (
        30.0,
        140.0,
        12.0,
        120.0,
    )

"""Frozen pre-cutover stats rows and isolated PostgreSQL databases for the stats parity tests.

The legacy seed is raw SQL, independent of the current ORM models.
Callers own its transaction. Normal tests only read golden files; capture is an
explicit, separate operation against the frozen old service source.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import URL, Connection, make_url

from shared.division_grid import DEFAULT_GRID
from shared.testing.db import ensure_test_postgres, is_ephemeral_test_dsn, postgres_env

BASE = 910_000
STAMP = datetime(2026, 1, 2, 12, tzinfo=UTC)
_BACKEND = Path(__file__).resolve().parents[2]
_PREFIX = "p4_stats01_"
_DATES = {"created_at": STAMP, "updated_at": STAMP + timedelta(seconds=1)}
_JSON_COLUMNS = frozenset(
    {"attrs", "aliases", "columns", "condition_tree", "depends_on", "evidence_json", "meta", "payload_json"}
)

# PostgreSQL's legacy enum labels, not values inferred from current module code.
LEGACY_STATS = (
    "Eliminations",
    "FinalBlows",
    "Deaths",
    "AllDamageDealt",
    "BarrierDamageDealt",
    "HeroDamageDealt",
    "HealingDealt",
    "HealingReceived",
    "SelfHealing",
    "DamageTaken",
    "DamageBlocked",
    "DefensiveAssists",
    "OffensiveAssists",
    "UltimatesEarned",
    "UltimatesUsed",
    "MultikillBest",
    "Multikills",
    "SoloKills",
    "ObjectiveKills",
    "EnvironmentalKills",
    "EnvironmentalDeaths",
    "CriticalHits",
    "CriticalHitAccuracy",
    "ScopedAccuracy",
    "ScopedCriticalHitAccuracy",
    "ScopedCriticalHitKills",
    "ShotsFired",
    "ShotsHit",
    "ShotsMissed",
    "ScopedShotsFired",
    "ScopedShotsHit",
    "WeaponAccuracy",
    "HeroTimePlayed",
    "FirstPicks",
    "FirstDeaths",
    "UltimateKills",
    "SupportKills",
    "Performance",
    "PerformancePoints",
    "KD",
    "KDA",
    "DamageDelta",
    "FBE",
    "DamageFB",
    "Assists",
    "ImpactPoints",
    "ImpactRank",
    "OverperformanceScore",
)
LEGACY_EVENTS = (
    "OffensiveAssist",
    "DefensiveAssist",
    "UltimateCharged",
    "UltimateStart",
    "UltimateEnd",
    "HeroSwap",
    "MercyRez",
    "EchoDuplicateStart",
    "EchoDuplicateEnd",
)
_AVERAGES = frozenset(
    {
        "CriticalHitAccuracy",
        "ScopedAccuracy",
        "ScopedCriticalHitAccuracy",
        "WeaponAccuracy",
        "Performance",
        "PerformancePoints",
        "KD",
        "KDA",
        "FBE",
        "DamageFB",
        "ImpactPoints",
        "ImpactRank",
        "OverperformanceScore",
    }
)
_VALUES = dict.fromkeys(LEGACY_STATS, 8.0)
_VALUES.update(
    Eliminations=24.0,
    FinalBlows=16.0,
    Deaths=8.0,
    AllDamageDealt=24_000.0,
    BarrierDamageDealt=6_000.0,
    HeroDamageDealt=18_000.0,
    HealingDealt=12_000.0,
    HealingReceived=8_000.0,
    SelfHealing=1_600.0,
    DamageTaken=24_000.0,
    DamageBlocked=8_000.0,
    CriticalHits=160.0,
    CriticalHitAccuracy=0.25,
    ScopedAccuracy=0.5,
    ScopedCriticalHitAccuracy=0.25,
    ShotsFired=800.0,
    ShotsHit=400.0,
    ShotsMissed=400.0,
    ScopedShotsFired=400.0,
    ScopedShotsHit=200.0,
    WeaponAccuracy=0.5,
    HeroTimePlayed=7_200.0,
    Performance=0.5,
    PerformancePoints=50.0,
    KD=3.0,
    KDA=4.0,
    DamageDelta=6_000.0,
    FBE=0.625,
    DamageFB=1_125.0,
    ImpactPoints=24.0,
    ImpactRank=1.0,
    OverperformanceScore=8.0,
)
# Actual, nonempty UTF-8 objects; the seed hashes these bytes, never row ids.
_RAW_BYTES = {
    "main.csv": b"event,time,team,player\nmatch_start,0,Alpha,P4Alpha#1234\nmatch_end,7200,Alpha,P4Alpha#1234\n",
    "reverse.csv": b"event,time,team,player\nmatch_start,0,Bravo,P4Bravo#1234\nmatch_end,5400,Bravo,P4Bravo#1234\n",
    "other.csv": b"event,time,team,player\nmatch_start,0,Foreign,P4Alpha#1234\nmatch_end,3600,Foreign,P4Alpha#1234\n",
    "hidden.csv": b"event,time,team,player\nmatch_start,0,Hidden,P4Alpha#1234\nmatch_end,1800,Hidden,P4Alpha#1234\n",
    "pending.csv": b"event,time,team,player\nmatch_start,0,Unlinked,P4Alpha#1234\n",
}


def raw_objects(ids: dict[str, int]) -> dict[str, bytes]:
    """Independent object-store contents for the seed's exact accessor keys."""
    return {
        f"logs/{ids['tournament_other'] if name == 'other.csv' else ids['tournament_hidden'] if name == 'hidden.csv' else ids['tournament']}/{name}": data
        for name, data in _RAW_BYTES.items()
    }


def _insert(conn: Connection, table_name: str, **values: Any) -> None:
    schema, _, name = table_name.rpartition(".")
    table = sa.table(
        name,
        *(sa.column(key, JSONB(none_as_null=True) if key in _JSON_COLUMNS else None) for key in values),
        schema=schema or None,
    )
    conn.execute(sa.insert(table), values)


def seed_legacy(conn: Connection) -> dict[str, int]:
    """Populate a clean discipline01c scratch database; do not commit."""
    ids: dict[str, int] = {}
    groups = (
        ("workspace", "workspace_other"),
        ("auth_user", "auth_user_no_member"),
        ("tournament", "tournament_other", "tournament_hidden"),
        ("encounter", "encounter_other", "encounter_hidden"),
        ("team_home", "team_away", "team_other_home", "team_other_away", "team_hidden_home", "team_hidden_away"),
        (
            "encounter_team_home",
            "encounter_team_away",
            "encounter_team_other_home",
            "encounter_team_other_away",
            "encounter_team_hidden_home",
            "encounter_team_hidden_away",
        ),
        ("game", "game_reversed", "game_no_raw", "game_other", "game_hidden"),
        ("match", "match_reversed", "match_no_raw", "match_other", "match_hidden"),
        ("player", "player_away", "player_event_only", "player_other", "player_removed", "player_no_member"),
        ("member", "member_away", "member_event_only", "member_other", "member_other_away", "member_removed"),
        ("map", "map_other", "hero", "hero_other", "mode"),
        ("record", "record_reversed", "record_other", "record_hidden", "record_unlinked"),
    )
    for group in groups:
        ids.update((key, BASE + offset) for offset, key in enumerate(group))
    ids.update(
        (key, BASE) for key in ("baseline", "channel", "alias_miss", "rule", "evaluation_result", "override", "outbox")
    )
    for i in range(1, 5):
        ids[f"game_otp_{i}"] = ids[f"match_otp_{i}"] = BASE + 9 + i
    for i in range(1, 4):
        for kind in ("tournament", "encounter", "game", "match"):
            ids[f"{kind}_career_{i}"] = BASE - 30 + i
        for side, offset in (("home", 0), ("away", 1)):
            ids[f"team_career_{i}_{side}"] = BASE + 30 + i * 2 + offset
            ids[f"encounter_team_career_{i}_{side}"] = BASE + 30 + i * 2 + offset
    ids.update(team_report=BASE, game_claim=BASE, readiness=BASE, roster_player=BASE, roster_away=BASE + 1)
    ids.update(grid=BASE, grid_version=BASE)

    _insert(
        conn,
        "division_grid",
        id=ids["grid"],
        workspace_id=None,
        discipline="overwatch",
        slug="p4-overwatch",
        name="P4 Overwatch ladder",
        **_DATES,
    )
    _insert(
        conn,
        "division_grid_version",
        id=ids["grid_version"],
        grid_id=ids["grid"],
        version=1,
        label="P4 frozen ladder",
        status="published",
        published_at=STAMP,
        **_DATES,
    )
    for index, tier in enumerate(DEFAULT_GRID.tiers):
        _insert(
            conn,
            "division_grid_tier",
            id=BASE + index,
            version_id=ids["grid_version"],
            slug=tier.slug,
            number=tier.number,
            name=tier.name,
            sort_order=index,
            rank_min=tier.rank_min,
            rank_max=tier.rank_max,
            icon_url=tier.icon_url,
            **_DATES,
        )

    for key in ("workspace", "workspace_other"):
        _insert(
            conn,
            "workspace",
            id=ids[key],
            slug=f"p4-{key}",
            name=f"P4 {key}",
            disciplines_enabled=["overwatch", "lol"],
            **_DATES,
        )
        _insert(
            conn,
            "workspace_division_grid_default",
            workspace_id=ids[key],
            discipline="overwatch",
            version_id=ids["grid_version"],
        )
    for key in ("auth_user", "auth_user_no_member"):
        _insert(
            conn,
            "auth.user",
            id=ids[key],
            email=f"p4-{key}@example.test",
            username=f"p4-{key}",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            **_DATES,
        )
    people = (
        ("player", "P4 Alpha", "P4Alpha#1234", "auth_user"),
        ("player_away", "P4 Bravo", "P4Bravo#1234", None),
        ("player_event_only", "P4 Substitute", "P4Substitute#1234", None),
        ("player_other", "P4 Foreign", "P4Foreign#1234", None),
        ("player_removed", "P4 Historical", "P4Historical#1234", None),
        ("player_no_member", "P4 Unattached", "P4Unattached#1234", "auth_user_no_member"),
    )
    for offset, (key, name, handle, auth) in enumerate(people):
        _insert(conn, "players.user", id=ids[key], name=name, auth_user_id=ids[auth] if auth else None, **_DATES)
        _insert(
            conn,
            "players.social_account",
            id=BASE + offset,
            user_id=ids[key],
            provider="battlenet",
            username=handle,
            username_normalized=handle.casefold(),
            is_primary=True,
            **_DATES,
        )
    # A wrong provider and a secondary OW account must not win the frozen handle selection.
    _insert(
        conn,
        "players.social_account",
        id=BASE + 20,
        user_id=ids["player"],
        provider="riot",
        username="P4 Alpha#EUW",
        username_normalized="p4 alpha#euw",
        is_primary=True,
        **_DATES,
    )
    _insert(
        conn,
        "players.social_account",
        id=BASE + 21,
        user_id=ids["player"],
        provider="battlenet",
        username="P4Secondary#5678",
        username_normalized="p4secondary#5678",
        is_primary=False,
        **_DATES,
    )
    members = (
        ("member", "workspace", "player"),
        ("member_away", "workspace", "player_away"),
        ("member_event_only", "workspace", "player_event_only"),
        ("member_other", "workspace_other", "player"),
        ("member_other_away", "workspace_other", "player_other"),
        ("member_removed", "workspace", "player_removed"),
    )
    for key, workspace, player in members:
        _insert(
            conn,
            "workspace_member",
            id=ids[key],
            workspace_id=ids[workspace],
            player_id=ids[player],
            removed_at=STAMP + timedelta(days=30) if key == "member_removed" else None,
            **_DATES,
        )

    for key, kind, slug, name, attrs in (
        ("mode", "mode", "p4-escort", "P4 Escort", {}),
        ("map", "map", "p4-map-a", "P4 Map A", {}),
        ("map_other", "map", "p4-map-b", "P4 Map B", {}),
        ("hero", "character", "p4-tracer", "P4 Tracer", {"class": "damage"}),
        ("hero_other", "character", "p4-ana", "P4 Ana", {"class": "support"}),
    ):
        _insert(
            conn,
            "catalog.entity",
            id=ids[key],
            discipline="overwatch",
            kind=kind,
            slug=slug,
            name=name,
            parent_id=ids["mode"] if kind == "map" else None,
            attrs=attrs,
            image_path=f"/p4/{slug}.png",
            **_DATES,
        )
    roles = {
        row.code: (row.id, row.dimension_id)
        for row in conn.execute(
            sa.text(
                "SELECT r.code,r.id,r.dimension_id FROM catalog.role r "
                "JOIN catalog.role_dimension d ON d.id=r.dimension_id "
                "WHERE d.discipline='overwatch' AND d.code='player_role' AND r.workspace_id IS NULL"
            )
        )
    }
    if not {"tank", "damage", "support"}.issubset(roles):
        raise RuntimeError("legacy stats fixture requires the complete P3 OW role ontology")
    ids["role_dimension"] = roles["damage"][1]
    ids.update((f"role_{code}", role_id) for code, (role_id, _) in roles.items())

    owners = (
        (
            "tournament",
            "workspace",
            "encounter",
            "team_home",
            "team_away",
            "encounter_team_home",
            "encounter_team_away",
        ),
        (
            "tournament_other",
            "workspace_other",
            "encounter_other",
            "team_other_home",
            "team_other_away",
            "encounter_team_other_home",
            "encounter_team_other_away",
        ),
        (
            "tournament_hidden",
            "workspace",
            "encounter_hidden",
            "team_hidden_home",
            "team_hidden_away",
            "encounter_team_hidden_home",
            "encounter_team_hidden_away",
        ),
    )
    owners += tuple(
        (
            f"tournament_career_{i}",
            "workspace",
            f"encounter_career_{i}",
            f"team_career_{i}_home",
            f"team_career_{i}_away",
            f"encounter_team_career_{i}_home",
            f"encounter_team_career_{i}_away",
        )
        for i in range(1, 4)
    )
    for offset, (tournament, workspace, encounter, home, away, home_seat, away_seat) in enumerate(owners):
        starts = STAMP + timedelta(days=(offset - 6) * 5) if offset >= 3 else STAMP
        _insert(
            conn,
            "tournament.tournament",
            id=ids[tournament],
            workspace_id=ids[workspace],
            discipline="overwatch",
            name=f"P4 {tournament}",
            slug=f"p4-{tournament}",
            status="completed",
            is_finished=True,
            is_hidden=tournament == "tournament_hidden",
            start_date=starts,
            end_date=starts + timedelta(days=1),
            auto_transitions_enabled=False,
            division_grid_version_id=ids["grid_version"],
            **_DATES,
        )
        _insert(
            conn,
            "roster.team_format",
            id=BASE + offset,
            workspace_id=ids[workspace],
            discipline="overwatch",
            tournament_id=ids[tournament],
            name="P4 flexible historical roster",
            starter_min=1,
            starter_max=2,
            substitute_min=0,
            substitute_max=2,
            **_DATES,
        )
        _insert(
            conn,
            "roster.team_format_dimension",
            team_format_id=BASE + offset,
            discipline="overwatch",
            dimension_id=ids["role_dimension"],
            mode="informational",
            player_min_assignments=1,
            player_max_assignments=1,
        )
        _insert(
            conn,
            "encounter.scoring_rule",
            id=BASE + offset,
            workspace_id=ids[workspace],
            preset="wins",
            game_formula="win",
            end_formula="games >= best_of or max_wins * 2 > best_of",
            **_DATES,
        )
        _insert(
            conn,
            "encounter.encounter",
            id=ids[encounter],
            workspace_id=ids[workspace],
            discipline="overwatch",
            tournament_id=ids[tournament],
            scoring_rule_id=BASE + offset,
            name=f"P4 {encounter}",
            slot_count=2,
            best_of=7 if offset == 0 else 3,
            status="COMPLETED",
            result_status="confirmed",
            result_source="admin",
            result_version=4,
            closeness=0.5,
            confirmed_at=STAMP + timedelta(hours=4),
            current_game_position=7 if offset == 0 else 1,
            **_DATES,
        )
        for slot, team, seat in ((1, home, home_seat), (2, away, away_seat)):
            _insert(
                conn,
                "tournament.team",
                id=ids[team],
                tournament_id=ids[tournament],
                balancer_name=f"p4-{team}",
                name=f"P4 {team}",
                **_DATES,
            )
            _insert(
                conn,
                "encounter.team",
                id=ids[seat],
                encounter_id=ids[encounter],
                tournament_id=ids[tournament],
                slot=slot,
                team_id=ids[team],
                name=f"P4 {team}",
                score=float(3 - slot if offset >= 3 else slot),
                placement=slot if offset >= 3 else 3 - slot,
                **_DATES,
            )
            place = slot if offset >= 3 else 3 - slot
            _insert(
                conn,
                "tournament.standing",
                id=BASE + offset * 2 + slot,
                tournament_id=ids[tournament],
                team_id=ids[team],
                position=place,
                overall_position=place,
                matches=1,
                win=int(place == 1),
                draw=0,
                lose=int(place != 1),
                points=float(place == 1),
                **_DATES,
            )

    games = (
        ("game", "encounter", 1, "map", "encounter_team_home", "encounter_team_away"),
        ("game_reversed", "encounter", 2, "map_other", "encounter_team_home", "encounter_team_away"),
        ("game_no_raw", "encounter", 3, "map", "encounter_team_home", "encounter_team_away"),
        ("game_other", "encounter_other", 1, "map", "encounter_team_other_home", "encounter_team_other_away"),
        ("game_hidden", "encounter_hidden", 1, "map_other", "encounter_team_hidden_home", "encounter_team_hidden_away"),
    )
    games += tuple(
        (f"game_otp_{i}", "encounter", i + 3, "map", "encounter_team_home", "encounter_team_away") for i in range(1, 5)
    ) + tuple(
        (
            f"game_career_{i}",
            f"encounter_career_{i}",
            1,
            "map",
            f"encounter_team_career_{i}_home",
            f"encounter_team_career_{i}_away",
        )
        for i in range(1, 4)
    )
    for key, encounter, position, map_key, home, away in games:
        _insert(
            conn,
            "encounter.game",
            id=ids[key],
            encounter_id=ids[encounter],
            position=position,
            map_id=ids[map_key],
            state="confirmed",
            result_source="admin",
            result_version=2,
            confirmed_at=STAMP + timedelta(hours=4),
            **_DATES,
        )
        # Official outcomes deliberately differ from observed log scores.
        for score, seat in ((9, home), (7, away)):
            _insert(
                conn,
                "encounter.game_team",
                game_id=ids[key],
                encounter_id=ids[encounter],
                encounter_team_id=ids[seat],
                score=score,
                placement=1 if score == 9 else 2,
            )
    _insert(
        conn,
        "encounter.team_report",
        id=ids["team_report"],
        encounter_id=ids["encounter"],
        encounter_team_id=ids["encounter_team_home"],
        reporter_user_id=ids["player"],
        games_played=7,
        basis_version=4,
        closeness=5,
        **_DATES,
    )
    _insert(
        conn,
        "encounter.game_claim",
        id=ids["game_claim"],
        encounter_id=ids["encounter"],
        game_id=ids["game"],
        claimant_team_id=ids["encounter_team_home"],
        reporter_user_id=ids["player"],
        basis_version=2,
        **_DATES,
    )
    _insert(
        conn,
        "encounter.readiness",
        id=ids["readiness"],
        encounter_id=ids["encounter"],
        encounter_team_id=ids["encounter_team_home"],
        ready_user_id=ids["player"],
        **_DATES,
    )
    conn.execute(
        sa.text("UPDATE encounter.game_team SET replay_code='P4CODE' WHERE game_id=:game AND encounter_team_id=:team"),
        {"game": ids["game"], "team": ids["encounter_team_home"]},
    )

    roster = (
        ("tournament", "encounter", "team_home", "encounter_team_home", "member", "damage", False),
        ("tournament", "encounter", "team_away", "encounter_team_away", "member_away", "support", False),
        ("tournament", "encounter", "team_home", "encounter_team_home", "member_event_only", "damage", True),
        ("tournament", "encounter", "team_home", "encounter_team_home", "member_removed", "damage", False),
        (
            "tournament_other",
            "encounter_other",
            "team_other_home",
            "encounter_team_other_home",
            "member_other",
            "damage",
            False,
        ),
        (
            "tournament_other",
            "encounter_other",
            "team_other_away",
            "encounter_team_other_away",
            "member_other_away",
            "support",
            False,
        ),
        (
            "tournament_hidden",
            "encounter_hidden",
            "team_hidden_home",
            "encounter_team_hidden_home",
            "member",
            "damage",
            False,
        ),
        (
            "tournament_hidden",
            "encounter_hidden",
            "team_hidden_away",
            "encounter_team_hidden_away",
            "member_away",
            "support",
            False,
        ),
    )
    roster += tuple(
        (
            f"tournament_career_{i}",
            f"encounter_career_{i}",
            f"team_career_{i}_{side}",
            f"encounter_team_career_{i}_{side}",
            member,
            role,
            False,
        )
        for i in range(1, 4)
        for side, member, role in (
            ("home", "member", "damage"),
            ("away", "member_away" if i < 3 else "member_removed", "support"),
        )
    )
    algorithm = conn.scalar(sa.text("SELECT id FROM analytics.algorithms WHERE name='Performance ML v2'"))
    if algorithm is None:
        algorithm = BASE
        _insert(conn, "analytics.algorithms", id=algorithm, name="Performance ML v2", produces_shifts=False, **_DATES)
    ids["algorithm"] = int(algorithm)
    for offset, (tournament, encounter, team, seat, member, role, substitute) in enumerate(roster):
        _insert(
            conn,
            "tournament.player",
            id=BASE + offset,
            name=f"P4 roster {offset}",
            rank=2500 + offset * 100,
            tournament_id=ids[tournament],
            team_id=ids[team],
            workspace_member_id=ids[member],
            is_substitution=substitute,
            **_DATES,
        )
        _insert(
            conn, "tournament.player_role", player_id=BASE + offset, dimension_id=roles[role][1], role_id=roles[role][0]
        )
        _insert(
            conn,
            "encounter.team_member",
            id=BASE + offset,
            encounter_id=ids[encounter],
            encounter_team_id=ids[seat],
            workspace_member_id=ids[member],
            active=True,
            display_name_snapshot=f"P4 observed {offset}",
            rank=2500 + offset * 100,
            is_substitute=substitute,
            **_DATES,
        )
        _insert(
            conn,
            "encounter.team_member_role",
            team_member_id=BASE + offset,
            dimension_id=roles[role][1],
            role_id=roles[role][0],
        )
        ids[f"roster_{tournament}_{member}"] = BASE + offset
        _insert(
            conn,
            "analytics.performance",
            id=BASE + offset,
            tournament_id=ids[tournament],
            player_id=BASE + offset,
            algorithm_id=ids["algorithm"],
            impact_score=40.0 + offset,
            raw_value=0.05 + offset / 100,
            local_residual=0.025 + offset / 100,
            local_zscore=0.5 + offset / 10,
            local_reference_n=5,
            confidence=0.8,
            log_coverage=1.0,
            **_DATES,
        )
    # Current registration changed later; the historical encounter snapshot remains rank2500.
    conn.execute(sa.text("UPDATE tournament.player SET rank=3500 WHERE id=:id"), {"id": ids["roster_player"]})

    records = (
        ("record", "tournament", "encounter", "main.csv", "main.csv", "upload"),
        (
            "record_reversed",
            "tournament",
            "encounter",
            f"logs/{ids['tournament']}/reverse.csv",
            "reverse.csv",
            "discord",
        ),
        ("record_other", "tournament_other", "encounter_other", "logs/other.csv", "other.csv", "manual"),
        ("record_hidden", "tournament_hidden", "encounter_hidden", "hidden.csv", "hidden.csv", "manual"),
        ("record_unlinked", "tournament", None, "pending.csv", "pending.csv", "upload"),
    )
    for key, tournament, encounter, filename, raw_name, source in records:
        pending = encounter is None
        _insert(
            conn,
            "log_processing.record",
            id=ids[key],
            tournament_id=ids[tournament],
            filename=filename,
            status="pending" if pending else "done",
            source=source,
            uploader_id=ids["player"],
            attached_encounter_id=ids[encounter] if encounter else None,
            content_hash=hashlib.sha256(_RAW_BYTES[raw_name]).hexdigest(),
            attempts=0 if pending else 2,
            started_at=None if pending else STAMP + timedelta(seconds=5),
            finished_at=None if pending else STAMP + timedelta(seconds=10),
            **_DATES,
        )
    matches = (
        ("match", "encounter", "map", 1, "team_home", "team_away", "record", "main.csv", 7200.0, 2, 1),
        (
            "match_reversed",
            "encounter",
            "map_other",
            2,
            "team_away",
            "team_home",
            "record_reversed",
            f"logs/{ids['tournament']}/reverse.csv",
            5400.0,
            3,
            4,
        ),
        ("match_no_raw", "encounter", "map", 3, "team_home", "team_away", None, None, None, 1, 0),
        (
            "match_other",
            "encounter_other",
            "map",
            1,
            "team_other_home",
            "team_other_away",
            "record_other",
            "logs/other.csv",
            3600.0,
            5,
            2,
        ),
        (
            "match_hidden",
            "encounter_hidden",
            "map_other",
            1,
            "team_hidden_home",
            "team_hidden_away",
            "record_hidden",
            "hidden.csv",
            1800.0,
            6,
            1,
        ),
    )
    matches += tuple(
        (f"match_otp_{i}", "encounter", "map", i + 3, "team_home", "team_away", None, None, 600.0, 1, 2)
        for i in range(1, 5)
    ) + tuple(
        (
            f"match_career_{i}",
            f"encounter_career_{i}",
            "map",
            1,
            f"team_career_{i}_home",
            f"team_career_{i}_away",
            None,
            None,
            1200.0,
            3,
            1,
        )
        for i in range(1, 4)
    )
    for key, encounter, map_key, position, home, away, record, filename, duration, home_score, away_score in matches:
        _insert(
            conn,
            "matches.match",
            id=ids[key],
            encounter_id=ids[encounter],
            map_id=ids[map_key],
            map_index=position,
            home_team_id=ids[home],
            away_team_id=ids[away],
            home_score=home_score,
            away_score=away_score,
            time=duration,
            log_name=filename,
            log_record_id=ids[record] if record else None,
            source="log_parser",
            **_DATES,
        )

    observations = (
        ("match", "player", "team_home", 1.0, 7200.0),
        ("match", "player_away", "team_away", 2.0, 7200.0),
        ("match", "player_removed", "team_home", 0.5, 3600.0),
        ("match_reversed", "player", "team_home", 1.5, 5400.0),
        ("match_reversed", "player_away", "team_away", 2.5, 5400.0),
        ("match_reversed", "player_removed", "team_home", 0.75, 2700.0),
        ("match_other", "player", "team_other_home", 100.0, 3600.0),
        ("match_other", "player_other", "team_other_away", 101.0, 3600.0),
        ("match_hidden", "player", "team_hidden_home", 20.0, 1800.0),
        ("match_hidden", "player_away", "team_hidden_away", 21.0, 1800.0),
    )
    observations += tuple(
        (f"match_otp_{i}", player, team, 0.3 + i / 10 + side, 600.0)
        for i in range(1, 5)
        for side, player, team in ((0, "player", "team_home"), (1, "player_away", "team_away"))
    ) + tuple(
        (f"match_career_{i}", player, f"team_career_{i}_{side}", 0.5 + i / 10 + (side == "away"), 1200.0)
        for i in range(1, 4)
        for side, player in (("home", "player"), ("away", "player_away" if i < 3 else "player_removed"))
    )
    fact_id = BASE
    for match, player, team, strength, duration in observations:
        heroes = [(ids["hero_other"] if player in {"player_away", "player_other"} else ids["hero"], 1.0)]
        if match == "match" and player == "player":
            heroes = [(ids["hero"], 0.75), (ids["hero_other"], 0.25)]
        for segment, segment_share in ((0, 1.0), (1, 0.5), (2, 0.5)):
            for hero_id, hero_share in [(None, 1.0), *heroes]:
                for stat in LEGACY_STATS:
                    if stat == "HeroTimePlayed":
                        value = duration * segment_share * hero_share
                        if match == "match_reversed" and segment == 0 and hero_id is None:
                            if player == "player_removed":
                                continue
                            if player == "player":
                                value = 0.0
                    elif stat in {"Performance", "ImpactRank"}:
                        # These ranks cross an integer public DTO boundary.
                        value = 1.0 + sum(
                            other_match == match and other_strength < strength
                            for other_match, _, _, other_strength, _ in observations
                        )
                    elif stat in _AVERAGES:
                        value = _VALUES[stat] + strength / 1000.0
                    elif stat == "MultikillBest":
                        value = _VALUES[stat] + strength
                    else:
                        value = _VALUES[stat] * strength * segment_share * hero_share
                    _insert(
                        conn,
                        "matches.statistics",
                        id=fact_id,
                        match_id=ids[match],
                        round=segment,
                        team_id=ids[team],
                        user_id=ids[player],
                        hero_id=hero_id,
                        name=stat,
                        value=value,
                    )
                    fact_id += 1

    for offset, ability in enumerate((None, "PrimaryFire", "Ultimate")):
        _insert(
            conn,
            "matches.kill_feed",
            id=BASE + offset,
            match_id=ids["match"],
            time=10.0 + offset,
            round=1 if offset < 2 else 2,
            fight=4 + offset,
            ability=ability,
            killer_id=ids["player_event_only"] if offset == 0 else ids["player"],
            killer_hero_id=ids["hero"],
            killer_team_id=ids["team_home"],
            victim_id=ids["player_away"],
            victim_hero_id=ids["hero_other"],
            victim_team_id=ids["team_away"],
            damage=80.5 + offset,
            is_critical_hit=offset == 1,
            is_environmental=offset == 2,
        )
    for offset, event in enumerate(LEGACY_EVENTS):
        _insert(
            conn,
            "matches.event",
            id=BASE + offset,
            match_id=ids["match"],
            time=20.0 + offset,
            round=1,
            team_id=ids["team_home"],
            user_id=ids["player_event_only"],
            hero_id=None if offset % 2 == 0 else ids["hero"],
            related_team_id=ids["team_away"] if offset % 3 else None,
            related_user_id=ids["player_away"] if offset % 3 == 1 else None,
            related_hero_id=ids["hero_other"] if offset % 3 == 1 else None,
            name=event,
        )
    # Equal semantic events are a multiset, not one deduplicated row.
    for offset in (20, 21):
        _insert(
            conn,
            "matches.event",
            id=BASE + offset,
            match_id=ids["match"],
            time=42.0,
            round=2,
            team_id=ids["team_home"],
            user_id=ids["player"],
            hero_id=ids["hero"],
            related_team_id=ids["team_away"],
            related_user_id=ids["player_away"],
            related_hero_id=ids["hero_other"],
            name="OffensiveAssist",
        )
    for offset, name, key in (
        (30, "UltimateStart", "event_timeline_first"),
        (31, "UltimateStart", "event_timeline_second"),
        (32, "UltimateEnd", "event_timeline_third"),
    ):
        ids[key] = BASE + offset
        _insert(
            conn,
            "matches.event",
            id=ids[key],
            match_id=ids["match"],
            time=60.0,
            round=2,
            team_id=ids["team_home"],
            user_id=ids["player_event_only"],
            hero_id=None,
            related_team_id=None,
            related_user_id=None,
            related_hero_id=None,
            name=name,
        )
    _insert(
        conn,
        "matches.stat_baselines",
        id=ids["baseline"],
        formula_version="p4-frozen-formula",
        role="damage",
        rank_bucket=-1,
        stat="HeroDamageDealt",
        mean=18000.5,
        std=125.25,
        meta={"sample_count": 7, "fixture": "preserve"},
        computed_at=STAMP + timedelta(days=1),
        **_DATES,
    )
    _insert(
        conn,
        "log_processing.discord_channel",
        id=ids["channel"],
        tournament_id=ids["tournament"],
        channel_id=9_100_000_000_001,
        channel_name="P4 logs",
        is_active=True,
        **_DATES,
    )
    _insert(
        conn,
        "catalog.alias_miss",
        id=ids["alias_miss"],
        discipline="overwatch",
        kind="character",
        raw_name="P4 unknown hero",
        occurrences=3,
        first_seen_at=STAMP,
        last_seen_at=STAMP + timedelta(days=1),
        last_ingest_job_id=ids["record"],
        **_DATES,
    )
    dependencies = ["matches.statistics", "matches.event", "players.user", "matches.kill_feed", "matches.match"]
    _insert(
        conn,
        "achievements.rule",
        id=ids["rule"],
        workspace_id=ids["workspace"],
        slug="p4-fixture-rule",
        name="P4 Fixture",
        description_ru="P4 fixture",
        description_en="P4 fixture",
        discipline="overwatch",
        entity_id=ids["hero"],
        category="general",
        scope="match",
        grain="match",
        condition_tree={},
        depends_on=dependencies,
        **_DATES,
    )
    _insert(
        conn,
        "achievements.evaluation_result",
        id=ids["evaluation_result"],
        achievement_rule_id=ids["rule"],
        workspace_member_id=ids["member"],
        tournament_id=ids["tournament"],
        encounter_id=ids["encounter"],
        match_id=ids["match"],
        qualified_at=STAMP,
        evidence_json={"fixture": [3, 1, 2]},
        rule_version=1,
        **_DATES,
    )
    _insert(
        conn,
        "achievements.override",
        id=ids["override"],
        achievement_rule_id=ids["rule"],
        workspace_member_id=ids["member_away"],
        tournament_id=ids["tournament"],
        match_id=ids["match_reversed"],
        action="grant",
        reason="P4 carried reference",
        granted_by=ids["auth_user"],
        **_DATES,
    )
    event_id = "91000000-0000-4000-8000-000000000001"
    _insert(
        conn,
        "event_outbox",
        id=ids["outbox"],
        event_id=event_id,
        event_type="achievement_evaluate",
        routing_key="achievement_evaluate",
        status="pending",
        attempts=0,
        created_at=STAMP,
        next_attempt_at=STAMP,
        payload_json={
            "event_id": event_id,
            "event_type": "achievement_evaluate",
            "workspace_id": ids["workspace"],
            "tournament_id": ids["tournament"],
            "changed_tables": dependencies,
            "fixture_note": {"keep": [3, 1, 2]},
        },
    )
    conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(sa.text("REFRESH MATERIALIZED VIEW matches.mv_hero_global_stats"))
    conn.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    return ids


def original_stats01_shape(conn: Connection) -> None:
    """Reproduce the original bound-head DDL on the isolated, fully proven seed.

    The old three-table shapes/constraints are frozen; facts,
    observation IDs and the actual initial oracle are never regenerated.
    This is a test fixture, not an operational downgrade.
    """
    _owned_url(conn.engine.url)
    if conn.scalar(
        sa.text("""SELECT EXISTS(SELECT 1 FROM stats.match WHERE encounter_game_id IS NULL)
        OR EXISTS(SELECT 1 FROM stats.ingest_job WHERE content_hash IS NULL OR source_kind='historical_reference')""")
    ):
        raise ValueError("original bound-head fixture requires proven games and original real hashes")
    # Frozen defining query: ordered averages, but no member-id best tie-break.
    old_mv = """
WITH qualified AS (
 SELECT DISTINCT f.match_id,f.workspace_member_id,f.entity_id FROM stats.fact f
 JOIN stats.match m ON m.id=f.match_id
 JOIN stats.stat_def d ON d.id=f.stat_id AND d.discipline=m.discipline AND d.code='hero_time_played'
 WHERE f.segment=0 AND f.value>60
), eligible AS (
 SELECT f.match_id,f.workspace_member_id,f.entity_id,f.stat_id,f.value,m.discipline,d.code
 FROM stats.fact f JOIN qualified q ON q.match_id=f.match_id AND q.workspace_member_id=f.workspace_member_id
 AND q.entity_id=f.entity_id JOIN stats.match m ON m.id=f.match_id
 JOIN stats.stat_def d ON d.id=f.stat_id AND d.discipline=m.discipline
 JOIN catalog.entity ce ON ce.id=f.entity_id AND ce.kind='character' AND ce.discipline=m.discipline
 WHERE f.segment=0 AND f.entity_id IS NOT NULL
), agg AS (
 SELECT e.discipline,e.entity_id,e.stat_id,
 sum(e.value ORDER BY e.match_id,e.workspace_member_id) sum_value,
 sum(m.duration_s ORDER BY e.match_id,e.workspace_member_id) sum_time
 FROM eligible e JOIN stats.match m ON m.id=e.match_id GROUP BY e.discipline,e.entity_id,e.stat_id
), ranked AS (
 SELECT e.*,row_number() OVER (PARTITION BY e.discipline,e.entity_id,e.stat_id ORDER BY e.value *
 CASE WHEN e.code IN ('deaths','damage_taken','environmental_deaths','shots_missed','damage_fb','performance')
 THEN -1.0 ELSE 1.0 END DESC,e.match_id DESC) rn FROM eligible e
), best AS (
 SELECT r.discipline,r.entity_id,r.stat_id,r.value best_value,g.encounter_id,mp.name map_name,
 mp.image_path map_image_path,t.name tournament_name,u.name username
 FROM ranked r JOIN stats.match m ON m.id=r.match_id
 JOIN catalog.entity mp ON mp.id=m.map_entity_id AND mp.kind='map' AND mp.discipline=m.discipline
 JOIN encounter.game g ON g.id=m.encounter_game_id
 JOIN encounter.encounter enc ON enc.id=g.encounter_id AND enc.workspace_id=m.workspace_id AND enc.discipline=m.discipline
 JOIN tournament.tournament t ON t.id=enc.tournament_id
 JOIN workspace_member wm ON wm.id=r.workspace_member_id AND wm.workspace_id=m.workspace_id
 JOIN players."user" u ON u.id=wm.player_id WHERE r.rn=1
)
SELECT a.discipline,a.stat_id,a.entity_id,b.best_value,(a.sum_value/nullif(a.sum_time,0))*600 AS avg,
 jsonb_build_object('encounter_id',b.encounter_id,'map_name',b.map_name,'map_image_path',b.map_image_path,
 'tournament_name',b.tournament_name,'username',b.username) AS metadata
FROM agg a JOIN best b ON b.discipline=a.discipline AND b.entity_id=a.entity_id AND b.stat_id=a.stat_id
"""
    statements = (
        "SET CONSTRAINTS ALL IMMEDIATE",
        "DROP MATERIALIZED VIEW stats.mv_entity_global_stats",
        "ALTER TABLE stats.match_team ADD COLUMN encounter_game_id BIGINT",
        "UPDATE stats.match_team t SET encounter_game_id=m.encounter_game_id FROM stats.match m WHERE m.id=t.match_id",
        """ALTER TABLE stats.match_team DROP CONSTRAINT fk_match_team_match,
            DROP CONSTRAINT fk_match_team_encounter_team, DROP COLUMN encounter_id,
            ALTER COLUMN encounter_game_id SET NOT NULL,
            ADD CONSTRAINT match_team_match_id_fkey FOREIGN KEY(match_id) REFERENCES stats.match(id)
              ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
            ADD CONSTRAINT fk_match_team_game_team FOREIGN KEY(encounter_game_id,encounter_team_id)
              REFERENCES encounter.game_team(game_id,encounter_team_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED""",
        """ALTER TABLE stats.match DROP CONSTRAINT fk_stats_match_encounter, DROP CONSTRAINT uq_stats_match_owner,
            DROP CONSTRAINT fk_stats_match_game, DROP COLUMN encounter_id, DROP COLUMN source_map_index,
            ALTER COLUMN encounter_game_id SET NOT NULL,
            ADD CONSTRAINT match_encounter_game_id_fkey FOREIGN KEY(encounter_game_id)
              REFERENCES encounter.game(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED""",
        "ALTER TABLE stats.ingest_job DROP COLUMN raw_status, ALTER COLUMN content_hash SET NOT NULL",
        f"CREATE MATERIALIZED VIEW stats.mv_entity_global_stats AS {old_mv}",
        "CREATE UNIQUE INDEX uq_mv_entity_global_stats ON stats.mv_entity_global_stats(discipline,stat_id,entity_id)",
        "SET CONSTRAINTS ALL DEFERRED",
    )
    for statement in statements:
        conn.execute(sa.text(statement))


def _owned_url(url: str) -> URL:
    parsed = make_url(url)
    env = postgres_env()
    if (
        not is_ephemeral_test_dsn()
        or parsed.host != env["host"]
        or parsed.port != int(env["port"])
        or not (parsed.database or "").startswith(_PREFIX)
    ):
        raise ValueError("stats fixture only accepts its owned ephemeral PostgreSQL database")
    return parsed


def upgrade_database(url: str, target: str) -> subprocess.CompletedProcess[str]:
    """Return actual Alembic success/refusal output for an owned local database."""
    _owned_url(url)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=_BACKEND,
        env={**os.environ, "DATABASE_URL": url, "OWT_APPLY_ENCOUNTER_LAYER_DROP": "1", "OWT_APPLY_LEGACY_DROP": "1"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@contextmanager
def legacy_database(*, template_url: str | None = None) -> Iterator[str]:
    """One fresh database or cheap clone; never reset the shared anak_test DB."""
    if not is_ephemeral_test_dsn():
        pytest.skip("stats migration fixtures require the committed ephemeral test PostgreSQL")
    ensure_test_postgres()
    env = postgres_env()
    name = f"{_PREFIX}{uuid.uuid4().hex[:16]}"
    url = URL.create(
        "postgresql+psycopg",
        username=env["user"],
        password=env["password"],
        host=env["host"],
        port=int(env["port"]),
        database=name,
    ).render_as_string(hide_password=False)
    template = _owned_url(template_url).database if template_url else None
    with psycopg.connect(
        host=env["host"],
        port=int(env["port"]),
        user=env["user"],
        password=env["password"],
        dbname="postgres",
        autocommit=True,
    ) as admin:
        statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        if template:
            statement += sql.SQL(" TEMPLATE {}").format(sql.Identifier(template))
        admin.execute(statement)
        try:
            if not template:
                result = upgrade_database(url, "discipline01c")
                if result.returncode:
                    raise RuntimeError(f"legacy fixture migration failed:\n{result.stdout}\n{result.stderr}")
            yield url
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("golden timestamps must carry their timezone")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported golden value: {type(value).__name__}")


def _populated_template(target: str) -> Iterator[tuple[str, dict[str, int]]]:
    with legacy_database() as url:
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = seed_legacy(conn)
        finally:
            engine.dispose()
        result = upgrade_database(url, target)
        if result.returncode:
            raise RuntimeError(f"stats parity upgrade failed:\n{result.stdout}\n{result.stderr}")
        yield url, ids


@pytest.fixture(scope="module")
def stats_parity_template() -> Iterator[tuple[str, dict[str, int]]]:
    """One populated native template shared by a service's parity cases."""
    # Head, not ``stats01``: the ORM selects every current model column (``tournament.logs_official``
    # arrives with ``ingest01``), so a template frozen at ``stats01`` cannot serve a later model.
    yield from _populated_template("head")


@pytest.fixture
def stats_parity_database(stats_parity_template: tuple[str, dict[str, int]]) -> Iterator[tuple[str, dict[str, int]]]:
    template, ids = stats_parity_template
    with legacy_database(template_url=template) as url:
        yield url, ids.copy()


def seed_native_sentinel(conn: Connection, ids: dict[str, int]) -> None:
    """Foreign-discipline data added only AFTER the legacy transfer proof."""
    from shared.disciplines import discipline

    dimension = discipline("lol").rated_dimension
    dimension_id = conn.scalar(
        sa.text(
            "INSERT INTO catalog.role_dimension(discipline,code,name,selection_mode,rated) "
            "VALUES ('lol',:code,:name,:selection_mode,true) "
            "ON CONFLICT (discipline,code) DO UPDATE SET rated=true RETURNING id"
        ),
        {"code": dimension.code, "name": dimension.name, "selection_mode": dimension.selection_mode},
    )
    role = dimension.roles[0]
    conn.execute(
        sa.text(
            "INSERT INTO catalog.role(dimension_id,code,name) VALUES (:dimension,:code,:name) "
            "ON CONFLICT (dimension_id,code) WHERE workspace_id IS NULL DO NOTHING"
        ),
        {"dimension": dimension_id, "code": role.code, "name": role.name},
    )
    for kind in ("tournament", "encounter", "game", "match", "map", "role"):
        ids[f"{kind}_lol"] = BASE + 90
    ids.update(
        hero_lol=BASE + 91,
        team_lol_home=BASE + 90,
        team_lol_away=BASE + 91,
        encounter_team_lol_home=BASE + 90,
        encounter_team_lol_away=BASE + 91,
    )
    parent = conn.execute(
        sa.text(
            "SELECT r.id,r.dimension_id FROM catalog.role r JOIN catalog.role_dimension d ON d.id=r.dimension_id "
            "WHERE d.discipline='lol' AND d.rated AND r.workspace_id IS NULL AND r.parent_role_id IS NULL "
            "ORDER BY r.id LIMIT 1"
        )
    ).one()
    _insert(
        conn,
        "catalog.role",
        id=ids["role_lol"],
        dimension_id=parent.dimension_id,
        workspace_id=ids["workspace"],
        parent_role_id=parent.id,
        code="damage",
        name="P4 LoL damage",
        **_DATES,
    )
    for kind, key in (("map", "map_lol"), ("character", "hero_lol")):
        _insert(
            conn,
            "catalog.entity",
            id=ids[key],
            discipline="lol",
            kind=kind,
            slug=f"p4-lol-{kind}",
            name=f"P4 LoL {kind}",
            **_DATES,
        )
    for code in ("hero_damage_dealt", "hero_time_played", "score"):
        ids[f"stat_lol_{code}"] = conn.scalar(
            sa.text(
                "INSERT INTO stats.stat_def(discipline,code,name,value_format,aggregation) "
                "VALUES ('lol',:code,:code,'decimal','sum') RETURNING id"
            ),
            {"code": code},
        )
    ids["event_type_lol_kill"] = conn.scalar(
        sa.text("INSERT INTO stats.event_type(discipline,code,name) VALUES ('lol','kill','Kill') RETURNING id")
    )
    _insert(
        conn,
        "tournament.tournament",
        id=ids["tournament_lol"],
        workspace_id=ids["workspace"],
        discipline="lol",
        name="P4 LoL sentinel",
        slug="p4-lol-sentinel",
        status="completed",
        is_finished=True,
        start_date=STAMP,
        end_date=STAMP + timedelta(days=1),
        **_DATES,
    )
    _insert(
        conn,
        "encounter.scoring_rule",
        id=BASE + 90,
        workspace_id=ids["workspace"],
        preset="wins",
        game_formula="win",
        end_formula="games >= best_of or max_wins * 2 > best_of",
        **_DATES,
    )
    _insert(
        conn,
        "encounter.encounter",
        id=ids["encounter_lol"],
        workspace_id=ids["workspace"],
        discipline="lol",
        tournament_id=ids["tournament_lol"],
        scoring_rule_id=BASE + 90,
        name="P4 LoL sentinel",
        slot_count=2,
        status="COMPLETED",
        result_status="confirmed",
        result_source="admin",
        confirmed_at=STAMP,
        **_DATES,
    )
    _insert(
        conn,
        "encounter.game",
        id=ids["game_lol"],
        encounter_id=ids["encounter_lol"],
        position=1,
        map_id=ids["map_lol"],
        state="confirmed",
        result_source="admin",
        confirmed_at=STAMP,
        **_DATES,
    )
    for slot, side in ((1, "home"), (2, "away")):
        team, seat = ids[f"team_lol_{side}"], ids[f"encounter_team_lol_{side}"]
        _insert(
            conn,
            "tournament.team",
            id=team,
            tournament_id=ids["tournament_lol"],
            name=f"P4 LoL {side}",
            balancer_name=f"p4-lol-{side}",
            **_DATES,
        )
        _insert(
            conn,
            "encounter.team",
            id=seat,
            encounter_id=ids["encounter_lol"],
            tournament_id=ids["tournament_lol"],
            team_id=team,
            slot=slot,
            name=f"P4 LoL {side}",
            **_DATES,
        )
        _insert(
            conn,
            "encounter.game_team",
            game_id=ids["game_lol"],
            encounter_id=ids["encounter_lol"],
            encounter_team_id=seat,
            score=slot,
        )
    _insert(
        conn,
        "stats.match",
        id=ids["match_lol"],
        workspace_id=ids["workspace"],
        discipline="lol",
        encounter_id=ids["encounter_lol"],
        source_map_index=1,
        encounter_game_id=ids["game_lol"],
        map_entity_id=ids["map_lol"],
        duration_s=600.0,
        **_DATES,
    )
    for slot, side, member in ((1, "home", "member"), (2, "away", "member_away")):
        seat = ids[f"encounter_team_lol_{side}"]
        _insert(
            conn,
            "stats.match_team",
            match_id=ids["match_lol"],
            encounter_id=ids["encounter_lol"],
            encounter_team_id=seat,
            source_position=slot,
        )
        _insert(
            conn,
            "stats.match_player",
            match_id=ids["match_lol"],
            encounter_team_id=seat,
            workspace_member_id=ids[member],
            handle_snapshot=f"P4{side}#EUW",
            observed_role_id=ids["role_lol"],
        )
        _insert(
            conn,
            "stats.fact",
            match_id=ids["match_lol"],
            segment=0,
            encounter_team_id=seat,
            stat_id=ids["stat_lol_score"],
            value=float(slot),
        )
    for entity in (None, ids["hero_lol"]):
        for code, value in (("hero_damage_dealt", 1_000_000.0), ("hero_time_played", 600.0)):
            _insert(
                conn,
                "stats.fact",
                match_id=ids["match_lol"],
                segment=0,
                encounter_team_id=ids["encounter_team_lol_home"],
                workspace_member_id=ids["member"],
                entity_id=entity,
                stat_id=ids[f"stat_lol_{code}"],
                value=value,
            )
    _insert(
        conn,
        "stats.event",
        match_id=ids["match_lol"],
        segment=0,
        t=10.0,
        type_id=ids["event_type_lol_kill"],
        actor_member_id=ids["member"],
        actor_team_id=ids["encounter_team_lol_home"],
        target_member_id=ids["member_away"],
        target_team_id=ids["encounter_team_lol_away"],
        entity_id=ids["hero_lol"],
    )
    ids["baseline_lol"] = conn.scalar(
        sa.text(
            "INSERT INTO stats.stat_baseline(formula_version,role_id,rank_bucket,stat_id,mean,std,computed_at) "
            "VALUES ('p4-frozen-formula',:role,-1,:stat,1000000,25,:computed_at) RETURNING id"
        ),
        {"role": ids["role_lol"], "stat": ids["stat_lol_hero_damage_dealt"], "computed_at": STAMP},
    )
    conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))

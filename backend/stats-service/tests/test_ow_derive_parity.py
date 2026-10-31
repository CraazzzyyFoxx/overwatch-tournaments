"""``derive_match`` and the history backfill agree on every ``impact_v2`` fact, bit for bit.

The legacy golden (``fixtures/stats_derived_parity.json``) pins the v1 impact numbers and cannot be reproduced by
``impact_v2`` (see ``test_stats_derived_parity``); what must hold now is that the two writers of the impact facts -- the
live derivation of a decoded document and the backfill over stored facts -- produce the same values. Each fixture match
is backfilled, read back as the document the decoder would have produced (per-hero facts, kill feed with its fights),
bound to the same members, and derived against the same hand-built baselines and the real rank quintiles.
"""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared import models
from shared.core.enums import LogStatsName
from shared.disciplines.ingest import BoundMatch, BoundParticipant
from shared.disciplines.overwatch import baselines, ingest
from shared.disciplines.overwatch.backfill import BackfillService
from shared.disciplines.overwatch.impact_backfill import NEW_STAT_MEMBERS
from shared.schemas.match_doc import MatchDoc
from tests.test_stats_derived_parity import _facts, _load_players, seed_synthetic_baselines

#: Event counts are written by the backfill but come out of the decoder, not ``derive_match``.
IMPACT_CODES = {member.value for member in NEW_STAT_MEMBERS} - {
    "first_picks",
    "first_deaths",
    "ultimate_kills",
    "support_kills",
}


async def stored_document(session, service: BackfillService, match_id: int) -> tuple[MatchDoc, BoundMatch]:
    players = await _load_players(session, match_id)
    slug = dict(await _hero_slugs(session))
    stat_rows = await service._load_stat_rows(session, match_id)
    kills = await service._load_kills(session, match_id)

    seats = sorted({row.encounter_team_id for row in players})
    team_key = {seat: ("home", "away")[min(index, 1)] for index, seat in enumerate(seats)}
    key_of = {row.workspace_member_id: str(row.workspace_member_id) for row in players}
    facts = [
        {
            "participant": key_of[int(row.player_id)],
            "entity": None if pd.isna(row.hero) else slug[int(row.hero)],
            "stat": LogStatsName[row.name].value,
            "value": float(row.value),
            "segment": int(row.segment),
        }
        for row in stat_rows.itertuples(index=False)
    ]
    document = MatchDoc.model_validate(
        {
            "protocol": "owt.match/1",
            "discipline": "overwatch",
            "source": {"kind": "upload"},
            "played_at": "2026-10-18T12:00:00Z",
            "duration_s": 1e6,
            "map": "any",
            "teams": [{"key": "home"}, {"key": "away"}],
            "participants": [
                {
                    "key": key_of[row.workspace_member_id],
                    "team": team_key[row.encounter_team_id],
                    "identity": {"provider": "battlenet", "id": f"Player{row.workspace_member_id}#1234"},
                }
                for row in players
            ],
            "segments": [{"index": n, "kind": "round"} for n in sorted({f["segment"] for f in facts if f["segment"]})],
            "facts": facts,
            "events": [
                {
                    "t": float(kill.t),
                    "type": "kill",
                    "actor": None if kill.actor_member_id is None else key_of[kill.actor_member_id],
                    "target": None if kill.target_member_id is None else key_of[kill.target_member_id],
                    "entity": slug.get(kill.entity_id),
                    "related_entity": slug.get(kill.related_entity_id),
                    "segment": kill.segment,
                    "data": dict(kill.data or {}),
                }
                for kill in kills
            ],
        }
    )
    encounter_id = await session.scalar(
        sa.select(models.StatsMatch.encounter_id).where(models.StatsMatch.id == match_id)
    )
    bound = BoundMatch(
        workspace_id=1,
        encounter_id=encounter_id,
        encounter_game_id=1,
        participants={
            key_of[row.workspace_member_id]: BoundParticipant(
                member_id=row.workspace_member_id,
                user_id=row.user_id,
                encounter_team_id=row.encounter_team_id,
                role=None,
            )
            for row in players
        },
    )
    return document, bound


async def _hero_slugs(session):
    rows = await session.execute(
        sa.select(models.CatalogEntity.id, models.CatalogEntity.slug).where(
            models.CatalogEntity.discipline == "overwatch", models.CatalogEntity.kind == "character"
        )
    )
    return rows.all()


@pytest.mark.parametrize("name", ["match", "match_reversed"])
def test_derive_match_equals_the_backfill_facts(stats_parity_database, name):
    url, ids = stats_parity_database

    async def run() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await baselines.baseline_service.invalidate_cache(discipline="overwatch")
                await seed_synthetic_baselines(session, ids)
                backfill = BackfillService()
                assert await backfill.backfill_match(session, ids[name])
                await session.commit()
                written = {
                    (row["user_id"], row["round"], row["stat_code"]): row["value"]
                    for row in await _facts(session, [ids[name]])
                    if row["hero_id"] is None and row["stat_code"] in IMPACT_CODES
                }
                document, bound = await stored_document(session, backfill, ids[name])
                derived = await ingest.derive_match(session, document, bound)
                await baselines.baseline_service.invalidate_cache(discipline="overwatch")
                members = {str(row.workspace_member_id): row.user_id for row in await _load_players(session, ids[name])}
        finally:
            await engine.dispose()

        actual = {(members[f.participant], f.segment, f.stat): f.value for f in derived.facts if f.stat in IMPACT_CODES}
        assert written, "the fixture match scores at least one player"
        assert actual == written
        assert {stat for _, _, stat in actual} >= {"impact_points", "impact_rank"}
        replaced = IMPACT_CODES
        assert [f for f in derived.facts if f.stat not in replaced] == [
            f for f in document.facts if f.stat not in replaced
        ]

    asyncio.run(run())

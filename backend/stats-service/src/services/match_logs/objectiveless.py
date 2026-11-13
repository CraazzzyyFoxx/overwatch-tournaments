"""Resolve Push/Clash observed score facts without changing accepted results."""

from __future__ import annotations

from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.clients.s3 import S3Client
from shared.core import enums
from shared.disciplines import DISCIPLINES
from shared.domain.objectiveless_maps import (
    OBJECTIVELESS_GAMEMODES,
    AcceptedGame,
    LoggedMap,
    Series,
    resolve_scores,
)
from shared.repository.stats import StatsMatchRepository
from shared.repository.stats_queries import team_scores
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence

__all__ = ("load_producers", "resolve_encounter_maps")


async def load_producers(session: AsyncSession, s3: S3Client, encounter_id: int) -> dict[int, str]:
    """Job id -> ``canonical|decoded`` for every job behind the encounter's observations.

    Read before any final lock (it fetches envelopes from S3). A job without an envelope is undecoded raw Workshop
    input, so it reads as ``decoded``. Only a discipline that derives matches from raw logs has anything to rewrite,
    so the others' envelopes are never fetched.
    """
    from src.services.ingest.jobs import load_document

    rows = (
        await session.execute(
            sa.select(models.IngestJob.id, models.IngestJob.document_ref, models.IngestJob.discipline)
            .join(models.StatsMatch, models.StatsMatch.ingest_job_id == models.IngestJob.id)
            .where(models.StatsMatch.encounter_id == encounter_id)
        )
    ).all()
    producers: dict[int, str] = {}
    for job_id, document_ref, discipline in rows:
        if DISCIPLINES[discipline].derive_match is None:
            continue
        if document_ref is None:
            producers[job_id] = "decoded"
            continue
        try:
            _, producers[job_id] = await load_document(s3, document_ref)
        except LookupError, ValueError:
            producers[job_id] = "canonical"  # unreadable provenance is never rewritten
    return producers


async def resolve_encounter_maps(session: AsyncSession, encounter_id: int, *, producers: Mapping[int, str]) -> bool:
    """Flush score-only changes and evidence; the caller owns the existing commit.

    Push/Clash normalization repairs *raw Workshop* observations only. A match is writable when it has no job
    (historical) or its job's producer is ``decoded`` in ``producers`` (see :func:`load_producers`). Canonical
    observations (and a job unknown to ``producers``, written after it was read) are read-only inputs: their scores
    count as observed maps of the series but keep exactly the facts their producer supplied.

    Ingest calls this after staging its reparse, with the same encounter lock
    already held. Standalone calls take that lock before any match locks too.
    """
    encounter = await session.scalar(
        sa.select(models.Encounter)
        .where(
            models.Encounter.id == encounter_id,
            models.Encounter.discipline == "overwatch",
        )
        .with_for_update()
    )
    if encounter is None:
        return False
    mode = aliased(models.CatalogEntity, name="mode")
    match, game = models.StatsMatch, models.EncounterGame
    rows = (
        await session.execute(
            sa.select(match, mode.slug)
            .join(
                game,
                game.id == match.encounter_game_id,
            )
            # The match's own mode, not its map's catalog parent.
            .join(
                mode,
                sa.and_(
                    mode.id == match.mode_entity_id,
                    mode.discipline == match.discipline,
                    mode.kind == "mode",
                ),
            )
            .where(
                game.encounter_id == encounter_id,
                match.workspace_id == encounter.workspace_id,
                match.discipline == "overwatch",
            )
            .order_by(match.id)
            .with_for_update(of=match)
        )
    ).all()
    # Every observation is an input; only decoded (raw Workshop) ones may be rewritten.
    writable = {row.id for row, _ in rows if row.ingest_job_id is None or producers.get(row.ingest_job_id) == "decoded"}
    if not any(slug in OBJECTIVELESS_GAMEMODES and row.id in writable for row, slug in rows):
        return False

    scores_relation = team_scores(discipline="overwatch", stat_code="score")
    observed = (
        await session.execute(
            sa.select(scores_relation)
            .where(
                scores_relation.c.match_id.in_([row.id for row, _ in rows]),
            )
            .order_by(scores_relation.c.match_id, scores_relation.c.slot)
        )
    ).all()
    by_match = {}
    for score in observed:
        by_match.setdefault(score.match_id, []).append(score)
    seat_ids = {score.encounter_team_id for score in observed}
    seats = {
        seat.id: seat
        for seat in await session.scalars(
            sa.select(models.EncounterTeam).where(
                models.EncounterTeam.encounter_id == encounter_id,
                models.EncounterTeam.id.in_(seat_ids),
            )
        )
    }
    games = list(
        await session.scalars(
            sa.select(game)
            .where(
                game.encounter_id == encounter_id,
                game.state == enums.EncounterGameState.CONFIRMED,
            )
            .order_by(game.position)
        )
    )
    game_scores = {row.id: {} for row in games}
    for line in await session.scalars(
        sa.select(models.EncounterGameTeam).where(
            models.EncounterGameTeam.game_id.in_(game_scores),
        )
    ):
        game_scores[line.game_id][line.encounter_team_id] = line.score

    # Use each bound game's historical participants, not today's active seats.
    groups = {}
    for row, slug in rows:
        sides = by_match.get(row.id, [])
        if len(sides) != 2 or {side.slot for side in sides} != {1, 2}:
            continue  # The OW duel resolver cannot infer an incomplete/N-team observation.
        key = tuple(sorted(side.encounter_team_id for side in sides))
        groups.setdefault(key, []).append(
            LoggedMap(
                match_id=row.id,
                map_id=row.map_entity_id,
                home_team_id=sides[0].tournament_team_id,
                home_score=sides[0].value,
                away_score=sides[1].value,
                # A canonical Push/Clash map is an observed score like any other map: it constrains the series but is
                # never deduced or rewritten.
                objectiveless=slug in OBJECTIVELESS_GAMEMODES and row.id in writable,
            )
        )
    resolved = {}
    for pair, logged in groups.items():
        resolved.update(
            resolve_scores(
                Series(
                    teams={key: seats[key].team_id for key in pair},
                    completed=encounter.status == enums.EncounterStatus.COMPLETED,
                    scores={key: seats[key].score for key in pair},
                ),
                logged,
                [
                    AcceptedGame(map_id=row.map_id, scores=game_scores[row.id])
                    for row in games
                    if set(game_scores[row.id]) == set(pair)
                ],
            )
        )

    changed = False
    repository = StatsMatchRepository()
    for row, _ in rows:
        score = resolved.get(row.id) if row.id in writable else None
        if score is None:
            continue
        sides = by_match[row.id]
        if (sides[0].value, sides[1].value) == score:
            continue
        scopes = owner_scopes("match", (row.id,))
        before = await capture_stats_evidence(session, scopes=scopes)
        await repository.set_team_scores(
            session,
            match_id=row.id,
            discipline="overwatch",
            scores={side.encounter_team_id: value for side, value in zip(sides, score, strict=True)},
        )
        after = await capture_stats_evidence(session, scopes=scopes)
        await stage_stats_evidence(
            session,
            operation="stats.score_edit",
            before=before,
            after=after,
            workspace_id=row.workspace_id,
            entity_type="stats_match",
            entity_id=row.id,
        )
        changed = True
    return changed

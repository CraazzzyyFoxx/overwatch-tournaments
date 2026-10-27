"""Local -> Challonge: full export, single-result push and auto-push on confirmation."""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.challonge_refs import resolve_encounter_challonge
from shared.services.encounter.participants import active_teams
from src.clients.challonge import challonge_client
from src.services.challonge.sync._types import _ImportSource
from src.services.challonge.sync.helpers import _source_matches_encounter
from src.services.challonge.sync.locking import ADMIN_LOCK_WAIT_SECONDS, _sync_job_lock


class ExportMixin:
    """``ChallongeSyncService``'s export side; the service owns the repositories and collaborators."""

    async def _resolve_export_target(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        encounter: models.Encounter,
        *,
        sources: list[_ImportSource] | None,
        match_mappings: dict[int, models.ChallongeMatchMapping] | None = None,
    ) -> tuple[_ImportSource | None, int | None]:
        # ``match_mappings`` is an optional bulk prefetch (export path) keyed by
        # encounter_id, so the export loop doesn't issue one mapping query per encounter.
        if match_mappings is not None:
            mapping = match_mappings.get(encounter.id)
        else:
            mapping = await self.match_mapping_repo.get_by(
                session,
                options=[selectinload(models.ChallongeMatchMapping.source)],
                encounter_id=encounter.id,
            )
        if mapping is not None and mapping.source is not None:
            source_row = mapping.source
            return (
                _ImportSource(
                    challonge_id=source_row.challonge_tournament_id,
                    source_id=source_row.id,
                    source_type=source_row.source_type,
                    stage_item_id=source_row.stage_item_id,
                ),
                mapping.challonge_match_id,
            )

        # No challonge_match_mapping: the encounter is not linked to Challonge. Return
        # the best-guess source with no match id — the caller treats a missing match
        # id as "skip".
        if sources is None:
            sources = await self.mapping.discover_sources(session, tournament)
        position = await self.bracket_encounter_repo.get_position(session, encounter.id)
        candidates = [source for source in sources if _source_matches_encounter(source, position)]
        source = candidates[0] if candidates else (sources[0] if len(sources) == 1 else None)
        return source, None

    async def _resolve_winner_challonge_id(
        self,
        session: AsyncSession,
        source: _ImportSource,
        winner_team_id: int,
        encounter: models.Encounter,
        *,
        participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] | None = None,
    ) -> int | None:
        """Resolve the winner's Challonge participant id from ``challonge_participant_mapping``."""
        if source.source_id is None:
            return None

        # ``participant_mappings`` is an optional bulk prefetch (export path) keyed by
        # (source_id, team_id); a missing key falls back to the query so stale mappings
        # referencing undiscovered sources still resolve.
        cached = (
            participant_mappings.get((source.source_id, winner_team_id)) if participant_mappings is not None else None
        )
        if cached is not None:
            source_mappings = cached
        else:
            # The lowest id wins below, so the ORDER BY decides which participant id
            # a multiply-mapped team exports as.
            result = await session.execute(
                self.participant_mapping_repo.select()
                .where(
                    models.ChallongeParticipantMapping.source_id == source.source_id,
                    models.ChallongeParticipantMapping.team_id == winner_team_id,
                )
                .order_by(models.ChallongeParticipantMapping.id.asc())
            )
            source_mappings = list(result.scalars().all())
        if source_mappings:
            return source_mappings[0].challonge_participant_id
        return None

    async def export_tournament(self, session: AsyncSession, tournament_id: int) -> dict:
        """Full export: push all completed encounter results to Challonge. Admin-only, so the short lock wait."""
        async with _sync_job_lock(tournament_id, "export", wait_seconds=ADMIN_LOCK_WAIT_SECONDS) as job_id:
            tournament = await self.tournament_repo.get(
                session,
                tournament_id,
                options=[
                    selectinload(models.Tournament.stages).selectinload(models.Stage.items),
                ],
            )
            if not tournament:
                raise HTTPException(status_code=404, detail="Tournament not found")

            sources = await self.mapping.discover_sources(session, tournament)
            if not sources:
                raise HTTPException(status_code=422, detail="Tournament has no Challonge source")

            stats = {"job_id": job_id, "matches_pushed": 0, "errors": 0, "skipped": 0}
            source_ids = [source.source_id for source in sources if source.source_id is not None]

            # "Linked to Challonge" = has a challonge_match_mapping under this
            # tournament's sources.
            linked_encounter_ids = await self.match_mapping_repo.list_encounter_ids(session, source_ids)
            enc_result = await session.execute(
                self.encounter_repo.select()
                .where(
                    models.Encounter.tournament_id == tournament_id,
                    models.Encounter.status == enums.EncounterStatus.COMPLETED,
                    # Challonge matches are two-sided: a completed lobby has no
                    # two-number scoreline to push, so push_single_result would 409
                    # once per export and fill the sync log with it.
                    models.Encounter.slot_count == 2,
                    models.Encounter.id.in_(tuple(linked_encounter_ids)),
                )
                .options(selectinload(models.Encounter.teams))
            )
            encounters = enc_result.scalars().all()

            # Bulk prefetch of both mapping tables — the loop below would otherwise
            # issue two lookup queries per encounter.
            match_mappings: dict[int, models.ChallongeMatchMapping] = {}
            encounter_ids = [encounter.id for encounter in encounters]
            if encounter_ids:
                # Ordered + first-wins on purpose: an encounter mapped under two
                # sources must always export to the same one.
                mapping_rows = await session.execute(
                    self.match_mapping_repo.select()
                    .where(models.ChallongeMatchMapping.encounter_id.in_(encounter_ids))
                    .options(selectinload(models.ChallongeMatchMapping.source))
                    .order_by(models.ChallongeMatchMapping.id.asc())
                )
                for mapping_row in mapping_rows.scalars():
                    match_mappings.setdefault(mapping_row.encounter_id, mapping_row)

            participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] = {}
            participant_rows = await self.participant_mapping_repo.list_by_source_ids(session, source_ids)
            for participant_row in sorted(participant_rows, key=lambda row: row.id):
                participant_mappings.setdefault((participant_row.source_id, participant_row.team_id), []).append(
                    participant_row
                )

            for encounter in encounters:
                try:
                    pushed = await self.push_single_result(
                        session,
                        tournament,
                        encounter,
                        sources=sources,
                        match_mappings=match_mappings,
                        participant_mappings=participant_mappings,
                    )
                    if pushed:
                        stats["matches_pushed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    stats["errors"] += 1
                    failed_mapping = match_mappings.get(encounter.id)
                    await self.sync_log._log_sync(
                        session,
                        tournament_id,
                        "export",
                        "match",
                        encounter.id,
                        failed_mapping.challonge_match_id if failed_mapping is not None else None,
                        "failed",
                        operation="push_result",
                        error_message=f"{type(e).__name__}: {e}",
                    )

            await session.commit()
            logger.info(f"Challonge export for tournament {tournament_id}: {stats}")
            return stats

    async def push_single_result(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        encounter: models.Encounter,
        *,
        sources: list[_ImportSource] | None = None,
        match_mappings: dict[int, models.ChallongeMatchMapping] | None = None,
        participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] | None = None,
    ) -> bool:
        """Push a single encounter result to Challonge."""
        source, challonge_match_id = await self._resolve_export_target(
            session, tournament, encounter, sources=sources, match_mappings=match_mappings
        )
        # No challonge_match_mapping → the encounter is not linked to Challonge; skip.
        if source is None or challonge_match_id is None:
            return False

        # Slots 1 and 2 ARE Challonge's participants 1 and 2, in that order.
        seats = await active_teams(session, encounter.id)
        if len(seats) != 2:
            raise ValueError(f"Encounter {encounter.id} does not seat two participations to push")
        first, second = seats

        winner_challonge_id: int | str
        if first.score == second.score:
            # Challonge's documented draw encoding (RR/Swiss).
            winner_challonge_id = "tie"
        else:
            winner_seat = first if first.score > second.score else second
            if winner_seat.team_id is None:
                raise ValueError(f"Encounter {encounter.id} has no winner team")

            resolved = await self._resolve_winner_challonge_id(
                session,
                source,
                winner_seat.team_id,
                encounter,
                participant_mappings=participant_mappings,
            )
            if resolved is None:
                raise ValueError(
                    f"Winner team {winner_seat.team_id} has no Challonge participant mapping "
                    f"for source {source.challonge_id}"
                )
            winner_challonge_id = resolved

        scores_csv = f"{int(first.score)}-{int(second.score)}"

        # Commit (releasing the pgBouncer-backed connection) before the external
        # HTTP call: a transaction held across a rate-limited third-party round-trip
        # pins a pool slot for the whole wait. It also lands export_tournament's
        # mapping writes and _log_sync rows per encounter. Callers commit before
        # invoking the push flow, so nothing unrelated is committed here.
        await session.commit()

        await challonge_client.update_match(
            source.challonge_id,
            challonge_match_id,
            scores_csv=scores_csv,
            winner_id=winner_challonge_id,
        )

        await self.sync_log._log_sync(
            session,
            tournament.id,
            "export",
            "match",
            encounter.id,
            challonge_match_id,
            "success",
            source_id=source.source_id,
            operation="push_result",
            payload={"scores_csv": scores_csv, "winner_challonge_id": winner_challonge_id},
        )
        return True

    async def auto_push_on_confirm(self, session: AsyncSession, encounter_id: int) -> None:
        """Push a confirmed encounter result to Challonge; a no-op for an unlinked one.

        Run by the ``tournament_challonge_push`` consumer and the organizer's manual push. A failure is journaled
        in the sync log (committed) and re-raised, so the caller decides between retry and dead-letter.
        """
        encounter = await self.encounter_repo.get(
            session,
            encounter_id,
            options=[
                selectinload(models.Encounter.tournament),
                selectinload(models.Encounter.tournament)
                .selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items),
                selectinload(models.Encounter.teams),
            ],
        )
        if not encounter:
            return
        # "Linked to Challonge" is derived from challonge_match_mapping.
        challonge_match_id = (await resolve_encounter_challonge(session, [encounter.id])).get(encounter.id)
        if challonge_match_id is None:
            return

        tournament = encounter.tournament
        if not tournament:
            return

        try:
            await self.push_single_result(session, tournament, encounter)
            await session.commit()
            logger.info(f"Auto-pushed encounter {encounter_id} to Challonge")
        except Exception as e:
            logger.error(f"Auto-push failed for encounter {encounter_id}: {e}")
            await self.sync_log._log_sync(
                session,
                tournament.id,
                "export",
                "match",
                encounter.id,
                challonge_match_id,
                "failed",
                error_message=f"{type(e).__name__}: {e}",
            )
            await session.commit()
            raise

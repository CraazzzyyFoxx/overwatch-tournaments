"""``import_tournament``: the full Challonge -> local import."""

from loguru import logger
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.encounter.events import enqueue_encounter_completed
from src import schemas
from src.services.challonge.sync._types import _ImportSource, _source_lookup_key, _SourceFetch, _UpsertResult
from src.services.challonge.sync.helpers import _fetch_all_sources, _import_invalidated_resources
from src.services.challonge.sync.locking import _sync_job_lock
from src.services.tournament.events import (
    enqueue_tournament_recalculation,
    publish_tournament_invalidation,
)


class ImportMixin:
    """``ChallongeSyncService``'s full import; the service owns the repositories and collaborators."""

    async def import_tournament(
        self, session: AsyncSession, tournament_id: int, *, dry_run: bool = False, lock_wait_seconds: float = 30.0
    ) -> dict:
        """Full import from Challonge: upsert encounters with scores and status.

        ``lock_wait_seconds`` is how long to wait for an import of this tournament already running before the 409;
        an admin's request passes ``ADMIN_LOCK_WAIT_SECONDS``, the auto-sync keeps the default.
        """
        async with _sync_job_lock(tournament_id, "import", wait_seconds=lock_wait_seconds) as job_id:
            tournament = await self.tournament_repo.get(
                session,
                tournament_id,
                options=[
                    selectinload(models.Tournament.stages)
                    .selectinload(models.Stage.items)
                    .selectinload(models.StageItem.inputs),
                ],
            )
            if not tournament:
                raise HTTPException(status_code=404, detail="Tournament not found")

            sources = await self.mapping.discover_sources(session, tournament)
            if not sources:
                raise HTTPException(status_code=422, detail="Tournament has no Challonge source")

            stats = {
                "job_id": job_id,
                "dry_run": dry_run,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "conflicts": 0,
                "errors": 0,
                "matches_synced": 0,
                "matches_created": 0,
                "matches_updated": 0,
                "matches_skipped": 0,
                "groups_created": 0,
                "stages_created": 0,
                "stage_inputs_created": 0,
                "bracket_links_created": 0,
                "bracket_links_updated": 0,
            }

            # Release the DB connection before the (potentially slow, rate-limited)
            # Challonge HTTP round-trips: under pgBouncer transaction
            # pooling an open transaction pins a scarce backend slot for the whole
            # network wait, and statement_timeout does not bound idle-in-transaction
            # time. expire_on_commit=False keeps the loaded ``tournament`` (and its
            # eager-loaded relationships) fully usable; the writes below open a
            # fresh, short transaction.
            await session.commit()

            raw_fetches = await _fetch_all_sources(sources)
            fetches: list[tuple[_ImportSource, _SourceFetch]] = []
            for source, fetch_result in raw_fetches:
                if isinstance(fetch_result, Exception):
                    stats["errors"] += 1
                    if not dry_run:
                        await self.sync_log._log_sync(
                            session,
                            tournament_id,
                            "import",
                            "tournament",
                            tournament_id,
                            source.challonge_id,
                            "failed",
                            source_id=source.source_id,
                            operation="fetch_snapshot",
                            error_message=f"{type(fetch_result).__name__}: {fetch_result}",
                        )
                    continue
                try:
                    if not dry_run:
                        structure_stats = await self.structure._ensure_stage_structure_for_matches(
                            session,
                            tournament,
                            source,
                            fetch_result.matches,
                        )
                        stats["groups_created"] += structure_stats["groups_created"]
                        stats["stages_created"] += structure_stats["stages_created"]
                    fetches.append((source, fetch_result))
                except Exception as exc:
                    stats["errors"] += 1
                    logger.exception(
                        "Stage structure failed for challonge_id={} tournament={}",
                        source.challonge_id,
                        tournament_id,
                    )
                    if not dry_run:
                        await self.sync_log._log_sync(
                            session,
                            tournament_id,
                            "import",
                            "tournament",
                            tournament_id,
                            source.challonge_id,
                            "failed",
                            source_id=source.source_id,
                            operation="apply_structure",
                            error_message=f"{type(exc).__name__}: {exc}",
                        )

            source_ids = [source.source_id for source in sources if source.source_id is not None]
            team_lookup = await self.mapping._build_team_lookup(
                session, tournament, fetches, source_ids=source_ids, dry_run=dry_run
            )
            match_lookup = await self.mapping._build_match_lookup(session, sources, tournament_id=tournament.id)

            processed_match_keys: set[tuple[int, int]] = set()
            processed_matches: list[tuple[_ImportSource, schemas.ChallongeMatch]] = []

            for source, fetch in fetches:
                for cm in fetch.matches:
                    match_key = (_source_lookup_key(source), cm.id)
                    if match_key in processed_match_keys:
                        continue
                    processed_match_keys.add(match_key)
                    processed_matches.append((source, cm))

                    if dry_run:
                        existing = match_lookup.get(source, cm.id)
                        if existing is None:
                            stats["created"] += 1
                            stats["matches_created"] += 1
                        elif existing.status == enums.EncounterStatus.COMPLETED:
                            stats["skipped"] += 1
                            stats["matches_skipped"] += 1
                        else:
                            stats["updated"] += 1
                            stats["matches_updated"] += 1
                        continue

                    try:
                        # Reads first, outside any savepoint: an unchanged match (every match of a quiet tick)
                        # costs no SAVEPOINT/RELEASE round trips, and a match that cannot be mapped writes only
                        # its failure row.
                        plan = await self._plan_upsert(
                            session, tournament, source, cm, match_lookup=match_lookup, team_lookup=team_lookup
                        )
                        if isinstance(plan, _UpsertResult) and plan.action == "skipped":
                            stats["skipped"] += 1
                            stats["matches_skipped"] += 1
                            continue
                        if isinstance(plan, _UpsertResult):
                            await self.sync_log._log_sync(
                                session,
                                tournament_id,
                                "import",
                                "match",
                                None,
                                cm.id,
                                "failed",
                                source_id=source.source_id,
                                operation="apply_import",
                                payload=(
                                    {"missing_participant_ids": list(plan.missing_participant_ids)}
                                    if plan.missing_participant_ids
                                    else None
                                ),
                                error_message=plan.error,
                            )
                            stats["errors"] += 1
                            continue
                        # One savepoint per match that writes: a row that fails takes back its own writes, never
                        # the matches around it.
                        async with session.begin_nested():
                            upsert_result = await self._apply_upsert(
                                session, tournament, source, cm, plan, match_lookup=match_lookup
                            )
                            stage_inputs_created = await self.structure._ensure_encounter_stage_inputs(
                                session,
                                tournament,
                                upsert_result.encounter,
                            )
                            if upsert_result.action == "conflict":
                                await self.sync_log._log_sync(
                                    session,
                                    tournament_id,
                                    "import",
                                    "match",
                                    upsert_result.encounter.id if upsert_result.encounter else None,
                                    cm.id,
                                    "conflict",
                                    source_id=source.source_id,
                                    operation="apply_import",
                                    conflict_type=upsert_result.conflict_type,
                                    before=upsert_result.before,
                                    after=upsert_result.after,
                                )
                                stats["conflicts"] += 1
                                stats["matches_skipped"] += 1
                            else:
                                if upsert_result.newly_completed and upsert_result.encounter is not None:
                                    await enqueue_encounter_completed(
                                        session, upsert_result.encounter, source_service="tournament-service"
                                    )
                                await self.sync_log._log_sync(
                                    session,
                                    tournament_id,
                                    "import",
                                    "match",
                                    upsert_result.encounter.id if upsert_result.encounter else None,
                                    cm.id,
                                    "success",
                                    source_id=source.source_id,
                                    operation="apply_import",
                                    payload={
                                        "action": upsert_result.action,
                                        "scores_csv": cm.scores_csv,
                                        "state": cm.state,
                                        "challonge_tournament_id": source.challonge_id,
                                    },
                                    before=upsert_result.before,
                                    after=upsert_result.after,
                                )
                                # Only a real write: it is what requests the recompute and the invalidation below.
                                stats["matches_synced"] += 1
                                stats[upsert_result.action] += 1
                                stats[f"matches_{upsert_result.action}"] += 1
                            stats["stage_inputs_created"] += stage_inputs_created
                    except Exception as exc:
                        stats["errors"] += 1
                        logger.exception(
                            "Match upsert failed challonge_match_id={} tournament={}",
                            cm.id,
                            tournament_id,
                        )
                        # The savepoint took this match's writes back: its encounter is gone or expired, so
                        # the link pass below must not reach it, and whatever else the match had touched
                        # (a stage item's inputs) reloads before the next match reads it.
                        match_lookup.by_source_key.pop((_source_lookup_key(source), cm.id), None)
                        match_lookup.by_challonge_id.pop(cm.id, None)
                        for expired in [obj for obj in session.identity_map.values() if sa_inspect(obj).expired]:
                            await session.refresh(expired)
                        await self.sync_log._log_sync(
                            session,
                            tournament_id,
                            "import",
                            "match",
                            None,
                            cm.id,
                            "failed",
                            source_id=source.source_id,
                            operation="apply_import",
                            error_message=f"{type(exc).__name__}: {exc}",
                        )

            if not dry_run:
                link_stats = await self._sync_challonge_advancement_links(
                    session,
                    processed_matches,
                    match_lookup=match_lookup,
                )
                stats["bracket_links_created"] += link_stats["bracket_links_created"]
                stats["bracket_links_updated"] += link_stats["bracket_links_updated"]
                if link_stats["bracket_links_created"] or link_stats["bracket_links_updated"]:
                    await self._advance_completed_challonge_matches(
                        session,
                        processed_matches,
                        match_lookup=match_lookup,
                    )

                if stats["matches_synced"] > 0:
                    await enqueue_tournament_recalculation(session, tournament_id)

                # Both halves ride the caller's transaction: the auto-sync worker
                # configures cashews and the realtime rail itself, so the local drop
                # lands here, and the outbox row carries it to every other service
                # that caches this.
                resources = _import_invalidated_resources(stats)
                if resources:
                    await publish_tournament_invalidation(session, tournament_id, resources)
                await session.commit()
            logger.info(f"Challonge import for tournament {tournament_id}: {stats}")
            return stats

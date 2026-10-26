"""Cross-tournament admin list of participation reports.

The unit of the list is the *encounter*, not the report: a dispute spans every
participation's report and the action that settles it is per-encounter, so a row
that showed one report could never carry the resolve action.

Three things here refuse to be computed in Python:

* ``reported_count`` and whether the reports agree drive both a filter and a
  filter chip, so they must be expressible in SQL — a page-local computation
  would make ``mismatch_only`` return the wrong rows and the chips count only
  the current page. "They agree" is one distinct standing across the reports,
  where a standing is the whole set of ``team_report_result`` lines.
* ``last_resolution`` is the newest audit row per encounter, fetched for the
  page's encounters with one ``DISTINCT ON`` statement rather than a query per row.
* the stats counters deliberately ignore the chip filters themselves, so each
  chip reports how many rows it *would* select rather than how many are
  currently shown.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import pagination
from shared.models.encounter.report import EncounterTeamReport, EncounterTeamReportResult
from shared.models.encounter.team import EncounterTeam
from shared.models.tournament.bracket_encounter import BracketEncounter
from src import schemas
from src.services.encounter.captain import serialize_team_report
from src.services.encounter.replay_codes import replay_codes_by_encounter

__all__ = ("encounter_reports_service",)


def _standing_per_report(workspace_id: int) -> sa.Subquery:
    """Per report: a stable text of its whole standing, lines sorted.

    ``string_agg`` over the ordered lines rather than a row comparison: a report
    is N lines, so "two reports agree" is "their aggregated standings are the
    same string" — one grouping the planner can hash, at any participant count.
    Only the workspace's reports, picked by ``report_id`` (the lines' indexed
    key): the outer workspace filter cannot reach through a GROUP BY.
    """
    line = EncounterTeamReportResult
    report = EncounterTeamReport
    workspace_reports = (
        sa.select(report.id)
        .join(models.Encounter, models.Encounter.id == report.encounter_id)
        .where(models.Encounter.workspace_id == workspace_id)
    )
    return (
        sa.select(
            line.report_id.label("report_id"),
            line.encounter_id.label("encounter_id"),
            sa.func.string_agg(
                sa.func.concat_ws(
                    ":",
                    sa.cast(line.encounter_team_id, sa.Text),
                    sa.cast(line.score, sa.Text),
                    sa.cast(line.placement, sa.Text),
                    sa.cast(line.wins, sa.Text),
                ),
                sa.text("'|' ORDER BY encounter_team_id"),
            ).label("standing"),
        )
        .where(line.report_id.in_(workspace_reports))
        .group_by(line.report_id, line.encounter_id)
        .subquery("report_standing")
    )


def _report_aggregate(workspace_id: int) -> sa.Subquery:
    """Per encounter of the workspace: how many participations reported, and how
    many distinct standings they named. "They agree" is ``distinct_standings = 1``."""
    standing = _standing_per_report(workspace_id)
    report = EncounterTeamReport
    return (
        sa.select(
            report.encounter_id.label("encounter_id"),
            sa.func.count().label("reported_count"),
            sa.func.count(sa.distinct(standing.c.standing)).label("distinct_standings"),
        )
        .select_from(report)
        .join(models.Encounter, models.Encounter.id == report.encounter_id)
        .outerjoin(standing, standing.c.report_id == report.id)
        .where(models.Encounter.workspace_id == workspace_id)
        .group_by(report.encounter_id)
        .subquery("report_agg")
    )


class _Query:
    """Shared joins and predicates for the list and its stats.

    Both surfaces must agree on what "in scope" means, so the scope predicates
    are built once. The chip predicates are kept separate because the stats
    deliberately drop them.
    """

    def __init__(self, workspace_id: int, params: schemas.EncounterReportsSearchParams) -> None:
        self.params = params
        self.agg = _report_aggregate(workspace_id)
        self.workspace_id = workspace_id

    def join(self, query: sa.Select) -> sa.Select:
        return (
            query.join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .outerjoin(self.agg, self.agg.c.encounter_id == models.Encounter.id)
            .outerjoin(BracketEncounter, BracketEncounter.encounter_id == models.Encounter.id)
        )

    def scope_predicates(self) -> list[sa.ColumnElement[bool]]:
        """Where the admin is looking: workspace, tournament, stage, free text."""
        params = self.params
        where: list[sa.ColumnElement[bool]] = [models.Tournament.workspace_id == self.workspace_id]
        if params.tournament_id is not None:
            where.append(models.Encounter.tournament_id == params.tournament_id)
        if params.stage_id is not None:
            where.append(BracketEncounter.stage_id == params.stage_id)
        if params.query:
            like = f"%{params.query}%"
            # The seat NAMES, not a team join: a participation carries the name
            # it was seated under, which outlives the source team.
            where.append(
                sa.or_(
                    models.Encounter.name.ilike(like),
                    sa.exists()
                    .where(EncounterTeam.encounter_id == models.Encounter.id)
                    .where(EncounterTeam.active.is_(True))
                    .where(EncounterTeam.name.ilike(like)),
                )
            )
        return where

    def chip_predicates(self) -> list[sa.ColumnElement[bool]]:
        """What the admin narrowed to inside that scope."""
        params = self.params
        where: list[sa.ColumnElement[bool]] = []
        if params.result_status:
            where.append(models.Encounter.result_status.in_(params.result_status))
        if params.mismatch_only:
            where.append(sa.and_(self.agg.c.reported_count >= 2, self.agg.c.distinct_standings > 1))
        if params.reported_count is not None:
            # A zero has to match rows with no aggregate row at all.
            if params.reported_count == 0:
                where.append(self.agg.c.reported_count.is_(None))
            else:
                where.append(self.agg.c.reported_count == params.reported_count)
        return where


def _series_valid(encounter: models.Encounter, reports: Sequence[EncounterTeamReport]) -> bool:
    """Advisory: a report may predate the encounter's current card, so a
    ``games_played`` past ``best_of`` is information, not a violation nobody can
    act on. No reports contradicts nothing."""
    return all(report.games_played is None or report.games_played <= encounter.best_of for report in reports)


class AdminEncounterReportsService:
    """Read-only admin views over participation reports.

    Both methods are analytical, not CRUD — aggregate subqueries, chip counters
    and pagination — so the statements stay here rather than behind repository
    methods.
    """

    def _row(
        self,
        encounter: models.Encounter,
        seats: Sequence[EncounterTeam],
        reports: Sequence[EncounterTeamReport],
        lines: dict[int, list[EncounterTeamReportResult]],
        names: dict[int, str],
        replay_codes: Sequence[schemas.ReplayCodeRead],
        *,
        stage_name: str | None,
        stage_type: object | None,
        round_number: int | None,
        tournament_name: str | None,
        reported_count: int | None,
        distinct_standings: int | None,
        resolution: schemas.LastResolutionRead | None,
    ) -> schemas.EncounterReportsRow:
        count = int(reported_count or 0)
        return schemas.EncounterReportsRow(
            id=encounter.id,
            name=encounter.name,
            tournament_id=encounter.tournament_id,
            tournament_name=tournament_name,
            stage_name=stage_name,
            stage_type=stage_type,
            round=round_number,
            best_of=encounter.best_of,
            status=encounter.status,
            result_status=encounter.result_status,
            scheduled_at=encounter.scheduled_at,
            participations=[
                schemas.EncounterParticipationRef(
                    encounter_team_id=seat.id, slot=seat.slot, team_id=seat.team_id, name=seat.name
                )
                for seat in seats
            ],
            reports=[
                serialize_team_report(
                    report,
                    lines.get(report.id, []),
                    names.get(report.reporter_user_id) if report.reporter_user_id else None,
                )
                for report in reports
            ],
            replay_codes=list(replay_codes),
            reported_count=count,
            # Undecided until every seat has answered: "they disagree" and "only
            # some have reported" are different states.
            standings_match=(distinct_standings == 1) if count >= len(seats) and seats else None,
            series_score_valid=_series_valid(encounter, reports),
            last_resolution=resolution,
        )

    async def list_encounter_reports(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        params: schemas.EncounterReportsSearchParams,
    ) -> pagination.Paginated[schemas.EncounterReportsRow]:
        builder = _Query(workspace_id, params)
        where = builder.scope_predicates() + builder.chip_predicates()

        query = (
            builder.join(
                sa.select(
                    models.Encounter,
                    models.Tournament.name.label("tournament_name"),
                    BracketEncounter.round.label("bracket_round"),
                    BracketEncounter.stage_id.label("bracket_stage_id"),
                    BracketEncounter.stage_item_id.label("bracket_stage_item_id"),
                    builder.agg.c.reported_count,
                    builder.agg.c.distinct_standings,
                )
            )
            .where(*where)
            .order_by(models.Encounter.updated_at.desc().nullslast(), models.Encounter.id.desc())
        )
        # The shared helper, not a hand-rolled offset/limit: it is what caps
        # ``per_page=-1`` at MAX_UNLIMITED_RESULTS and honours ``only_count``.
        query = params.apply_pagination(query)

        total_query = builder.join(sa.select(sa.func.count()).select_from(models.Encounter)).where(*where)

        rows = (await session.execute(query)).unique().all()
        total = (await session.execute(total_query)).scalar_one()
        encounters = [row[0] for row in rows]

        seats, reports, lines, names, stages, items, resolutions = await self._page_context(session, encounters, rows)
        codes = await replay_codes_by_encounter(session, [encounter.id for encounter in encounters])
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[
                self._row(
                    row[0],
                    seats.get(row[0].id, []),
                    reports.get(row[0].id, []),
                    lines,
                    names,
                    codes.get(row[0].id, []),
                    stage_name=items.get(row.bracket_stage_item_id)
                    or stages.get(row.bracket_stage_id, (None, None))[0],
                    stage_type=stages.get(row.bracket_stage_id, (None, None))[1],
                    round_number=row.bracket_round,
                    tournament_name=row.tournament_name,
                    reported_count=row.reported_count,
                    distinct_standings=row.distinct_standings,
                    resolution=resolutions.get(row[0].id),
                )
                for row in rows
            ],
        )

    async def _page_context(
        self,
        session: AsyncSession,
        encounters: Sequence[models.Encounter],
        rows: Sequence[sa.Row],
    ) -> tuple[
        dict[int, list[EncounterTeam]],
        dict[int, list[EncounterTeamReport]],
        dict[int, list[EncounterTeamReportResult]],
        dict[int, str],
        dict[int, tuple[str | None, object | None]],
        dict[int, str],
        dict[int, schemas.LastResolutionRead],
    ]:
        """Seats, reports, lines, reporter names, stage name/type, stage-item names and
        the newest audit row for ONE page.

        A statement each for the whole page, not one per row: the list is the
        admin's inbox and it is read at 50 rows at a time.
        """
        seats: dict[int, list[EncounterTeam]] = {}
        reports: dict[int, list[EncounterTeamReport]] = {}
        lines: dict[int, list[EncounterTeamReportResult]] = {}
        names: dict[int, str] = {}
        stages: dict[int, tuple[str | None, object | None]] = {}
        # Its own map: stage and stage-item ids are separate sequences, so one dict let an item
        # overwrite the stage that shares its number and blanked that stage's type.
        items: dict[int, str] = {}
        resolutions: dict[int, schemas.LastResolutionRead] = {}
        if not encounters:
            return seats, reports, lines, names, stages, items, resolutions

        ids = [encounter.id for encounter in encounters]
        for seat in (
            await session.execute(
                sa.select(EncounterTeam)
                .where(EncounterTeam.encounter_id.in_(ids), EncounterTeam.active.is_(True))
                .order_by(EncounterTeam.encounter_id, EncounterTeam.slot)
            )
        ).scalars():
            seats.setdefault(seat.encounter_id, []).append(seat)
        for report in (
            await session.execute(
                sa.select(EncounterTeamReport)
                .where(EncounterTeamReport.encounter_id.in_(ids))
                .order_by(EncounterTeamReport.encounter_id, EncounterTeamReport.encounter_team_id)
            )
        ).scalars():
            reports.setdefault(report.encounter_id, []).append(report)
        report_ids = [report.id for page in reports.values() for report in page]
        if report_ids:
            for line in (
                await session.execute(
                    sa.select(EncounterTeamReportResult).where(EncounterTeamReportResult.report_id.in_(report_ids))
                )
            ).scalars():
                lines.setdefault(line.report_id, []).append(line)
        reporter_ids = {
            report.reporter_user_id
            for page in reports.values()
            for report in page
            if report.reporter_user_id is not None
        }
        if reporter_ids:
            names = dict(
                (
                    await session.execute(
                        sa.select(models.User.id, models.User.name).where(models.User.id.in_(reporter_ids))
                    )
                ).all()
            )

        stage_ids = {row.bracket_stage_id for row in rows if row.bracket_stage_id is not None}
        item_ids = {row.bracket_stage_item_id for row in rows if row.bracket_stage_item_id is not None}
        if stage_ids:
            for stage_id, name, stage_type in (
                await session.execute(
                    sa.select(models.Stage.id, models.Stage.name, models.Stage.stage_type).where(
                        models.Stage.id.in_(stage_ids)
                    )
                )
            ).all():
                stages[stage_id] = (name, stage_type)
        if item_ids:
            items = dict(
                (
                    await session.execute(
                        sa.select(models.StageItem.id, models.StageItem.name).where(models.StageItem.id.in_(item_ids))
                    )
                ).all()
            )
        audit = models.EncounterResultAudit
        for resolution in (
            await session.execute(
                sa.select(
                    audit.encounter_id,
                    audit.action,
                    audit.actor_user_id,
                    models.User.name.label("actor_name"),
                    audit.created_at,
                )
                .outerjoin(models.User, models.User.id == audit.actor_user_id)
                .where(audit.encounter_id.in_(ids))
                .distinct(audit.encounter_id)
                .order_by(audit.encounter_id, audit.created_at.desc(), audit.id.desc())
            )
        ).all():
            resolutions[resolution.encounter_id] = schemas.LastResolutionRead(
                action=resolution.action,
                actor_user_id=resolution.actor_user_id,
                actor_name=resolution.actor_name,
                created_at=resolution.created_at,
            )
        return seats, reports, lines, names, stages, items, resolutions

    async def get_reports_stats(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        params: schemas.EncounterReportsSearchParams,
    ) -> schemas.EncounterReportsStats:
        """Counters for the filter chips.

        Scoped by tournament/stage/search but **not** by the chip filters: a chip
        must say how many rows it would select, not how many survive its own
        selection. Selecting "disputed" otherwise zeroes every other chip.
        """
        builder = _Query(workspace_id, params)
        scope = builder.scope_predicates()

        by_status_query = (
            builder.join(sa.select(models.Encounter.result_status, sa.func.count()).select_from(models.Encounter))
            .where(*scope)
            .group_by(models.Encounter.result_status)
        )
        by_status = {status.value: int(count) for status, count in (await session.execute(by_status_query)).all()}

        counts_query = builder.join(
            sa.select(
                sa.func.count()
                .filter(sa.and_(builder.agg.c.reported_count >= 2, builder.agg.c.distinct_standings > 1))
                .label("mismatch"),
                sa.func.count().filter(builder.agg.c.reported_count == 1).label("awaiting_second"),
            ).select_from(models.Encounter)
        ).where(*scope)
        counts = (await session.execute(counts_query)).one()

        return schemas.EncounterReportsStats(
            by_result_status=by_status,
            mismatch_count=int(counts.mismatch),
            awaiting_second_count=int(counts.awaiting_second),
        )


encounter_reports_service = AdminEncounterReportsService()

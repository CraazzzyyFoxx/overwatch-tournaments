"""Per-captain encounter result reporting.

Each captain submits their own report (series score + closeness rating + optional
per-map codes) independently — there is no blocking submit/confirm handshake. The
encounter result is DERIVED from the reports:

- < 2 reports        -> ``pending_confirmation`` (waiting on the other captain).
- 2 reports, scores match -> ``confirmed`` (via ``finalize_encounter_score``,
  which advances the bracket); ``Encounter.closeness`` = average of the two
  ratings / 10.
- 2 reports, scores differ -> ``disputed`` (admin resolves).

A captain may re-submit (upsert) their report until the encounter is confirmed;
afterwards only an admin can change the result (``set_encounter_result`` /
admin encounter edit).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.enums import (
    EncounterFormat,
    EncounterResultAuditAction,
    EncounterResultStatus,
    EncounterStatus,
    MapPoolEntryStatus,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_engine as engine
from shared.domain.encounter_format import ensure_format
from shared.messaging.config import (
    TOURNAMENT_EVENTS_EXCHANGE,
)
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.tournament.pick_ban import PickBanEntry, PickBanSession
from shared.repository import (
    EncounterCaptainReportRepository,
    EncounterMapCodeRepository,
    EncounterRepository,
    EncounterResultAuditRepository,
    UserRepository,
)
from shared.schemas.events import EncounterCompletedEvent
from shared.services.bracket import advancement
from shared.services.bracket.usability import is_encounter_live
from shared.services.challonge_refs import resolve_encounter_challonge
from shared.services.encounter.result_audit import record_result_transition
from shared.services.scrim_scope import is_scrim_container
from src import models, schemas
from src.services.challonge.sync import sync_service
from src.services.encounter import report_form
from src.services.encounter.finalize import FinalizeService, finalize_service
from src.services.encounter.report_form import ReportFormService, report_form_service
from src.services.tournament.events import enqueue_tournament_recalculation

# One per-map code: (map_index 1-based, replay/match code string). Defined by the
# report-form service, which validates them.
MapCodeInput = report_form.MapCodeInput

_ENCOUNTER_LOCK_OPTIONS = (
    selectinload(models.Encounter.home_team),
    selectinload(models.Encounter.away_team),
    selectinload(models.Encounter.stage),
)


def serialize_map_code(code: models.EncounterMapCode) -> schemas.EncounterMapCodeRead:
    return schemas.EncounterMapCodeRead(
        id=code.id,
        map_index=code.map_index,
        map_id=code.map_id,
        code=code.code,
    )


def serialize_captain_report(
    report: models.EncounterCaptainReport,
    encounter: models.Encounter,
    map_codes: Sequence[models.EncounterMapCode],
    reporter_name: str | None = None,
) -> schemas.CaptainReportRead:
    """Build the report payload shared by the public read and the admin list."""
    side: str | None = None
    if report.team_id == encounter.home_team_id:
        side = "home"
    elif report.team_id == encounter.away_team_id:
        side = "away"
    return schemas.CaptainReportRead(
        id=report.id,
        encounter_id=report.encounter_id,
        team_id=report.team_id,
        side=side,
        reporter_user_id=report.reporter_user_id,
        reporter_name=reporter_name,
        home_score=report.home_score,
        away_score=report.away_score,
        closeness=report.closeness,
        comment=report.comment,
        custom_fields=dict(report.custom_fields_json or {}),
        map_codes=[serialize_map_code(mc) for mc in sorted(map_codes, key=lambda c: c.map_index)],
        created_at=report.created_at.isoformat() if report.created_at else None,
        updated_at=report.updated_at.isoformat() if report.updated_at else None,
    )


class CaptainService:
    """The captain-facing result flow plus the admin overrides that resolve it."""

    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        report_repo: EncounterCaptainReportRepository = EncounterCaptainReportRepository(),
        map_code_repo: EncounterMapCodeRepository = EncounterMapCodeRepository(),
        audit_repo: EncounterResultAuditRepository = EncounterResultAuditRepository(),
        user_repo: UserRepository = UserRepository(),
        report_forms: ReportFormService = report_form_service,
        finalize: FinalizeService = finalize_service,
    ) -> None:
        self.encounter_repo = encounter_repo
        self.report_repo = report_repo
        self.map_code_repo = map_code_repo
        self.audit_repo = audit_repo
        self.user_repo = user_repo
        self.report_forms = report_forms
        self.finalize = finalize

    async def _enqueue_tournament_recalculation(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> None:
        await enqueue_tournament_recalculation(session, tournament_id)

    async def _enqueue_encounter_completed(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
    ) -> None:
        # This event has exactly one consumer: parser-service republishes it as an
        # AchievementEvaluateEvent (serve.py:368-398). For a scrim that evaluation is
        # verifiably empty — every achievement condition reaches its users through an
        # inner join on Player or through MatchStatistics, and a scrim room has
        # neither (docs/plans/2026-08-12-scrim-rooms.md §4.1, §5). It is not free
        # though: it costs an outbox row, a queue round trip, an EvaluationRun audit
        # row and one full query per encounter-dependent rule, per scrim result. Not
        # publishing beats publishing and discarding.
        if await is_scrim_container(session, encounter.tournament_id):
            return

        winner_team_id: int | None = None
        if encounter.home_score > encounter.away_score:
            winner_team_id = encounter.home_team_id
        elif encounter.away_score > encounter.home_score:
            winner_team_id = encounter.away_team_id

        await enqueue_outbox_event(
            session,
            EncounterCompletedEvent(
                tournament_id=encounter.tournament_id,
                encounter_id=encounter.id,
                home_team_id=encounter.home_team_id,
                away_team_id=encounter.away_team_id,
                winner_team_id=winner_team_id,
                source_service="tournament-service",
            ),
            exchange=TOURNAMENT_EVENTS_EXCHANGE,
            routing_key="tournament.encounter.completed",
        )

    async def _resolve_captain_identity(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser,
        encounter: models.Encounter,
    ) -> tuple[str, int, int]:
        """Determine if the auth user is captain of the home or away team.

        Returns ``(side, captain_user_id, team_id)`` where ``captain_user_id`` is the
        linked ``players.user`` id and ``team_id`` the captain's team.
        Raises 403 if the user is not a captain of either team.
        """
        player = await self.user_repo.get_by_auth_user_id(session, auth_user.id)

        if player is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No player profile linked to your account",
            )

        if encounter.home_team and encounter.home_team.captain_id == player.id:
            return "home", encounter.home_team.captain_id, encounter.home_team.id
        if encounter.away_team and encounter.away_team.captain_id == player.id:
            return "away", encounter.away_team.captain_id, encounter.away_team.id

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a captain of either team in this encounter",
        )

    async def resolve_captain_side(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser,
        encounter: models.Encounter,
    ) -> str:
        side, _captain_user_id, _team_id = await self._resolve_captain_identity(session, auth_user, encounter)
        return side

    async def resolve_captain_identity(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser,
        encounter: models.Encounter,
    ) -> tuple[str, int, int]:
        """Public wrapper for callers (outside this module) that need the
        domain ``players.user`` id and team id alongside the side, not just the
        side ``resolve_captain_side`` returns."""
        return await self._resolve_captain_identity(session, auth_user, encounter)

    async def _load_encounter(self, session: AsyncSession, encounter_id: int) -> models.Encounter:
        """Every caller of this is a series feature -- a lobby has no home/away
        report to file, so it is refused here rather than at each command."""
        encounter = await self.encounter_repo.get_for_update(
            session, encounter_id, options=list(_ENCOUNTER_LOCK_OPTIONS)
        )
        if not encounter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Encounter not found",
            )
        ensure_format(encounter, EncounterFormat.DUEL)
        return encounter

    async def _load_encounter_with_reports(self, session: AsyncSession, encounter_id: int) -> models.Encounter:
        """Like ``_load_encounter`` but also eager-loads captain reports + map codes."""
        encounter = await self.encounter_repo.get_for_update(
            session,
            encounter_id,
            options=[
                *_ENCOUNTER_LOCK_OPTIONS,
                selectinload(models.Encounter.captain_reports).selectinload(models.EncounterCaptainReport.map_codes),
            ],
        )
        if not encounter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Encounter not found",
            )
        ensure_format(encounter, EncounterFormat.DUEL)
        return encounter

    async def _picked_map_ids(self, session: AsyncSession, encounter_id: int) -> dict[int, int]:
        """``map_index`` (1-based position in the series) -> ``map_id``, for every
        map the veto has settled.

        ``PickBanEntry.order`` is NOT the index: it is a per-round display/tiebreak
        field that starts at 0 and is spaced by ``round * 1000``
        (``pick_ban_session.advance_to_next_round``), so reading an index off it
        produced ``map_index=0`` — which the ``map_index >= 1`` check on
        ``EncounterMapCode`` rejects outright — and ``1000`` for a second map. The
        index is the position in PLAY order, which is what ``action_index`` records.

        ``picked`` is the whole settled set: a pick is never re-stamped once its
        position is played (the result lives on ``EncounterGame``), so the veto's
        play order is complete the moment the series ends.

        Returns an empty dict when there is no veto pool (map codes then keep
        ``map_id = NULL``). Soft binding: callers never fail on an index beyond the
        settled count — it simply is not in the dict.
        """
        # Analytical: a three-column projection over a PickBanSession join, narrowed
        # by kind and entry status — one statement no CRUD repository method can
        # express (backend/docs/repository-boundaries.md).
        rows = await session.execute(
            select(PickBanEntry.order, PickBanEntry.action_index, PickBanEntry.item_id)
            .join(PickBanSession, PickBanSession.id == PickBanEntry.session_id)
            .where(
                PickBanSession.encounter_id == encounter_id,
                PickBanSession.kind == PickBanKind.MAP,
                PickBanEntry.status == MapPoolEntryStatus.PICKED,
            )
        )
        settled = sorted(rows.all(), key=lambda row: row[1] if row[1] is not None else row[0])
        return {index: int(row[2]) for index, row in enumerate(settled, start=1)}

    async def get_encounter_reports(self, session: AsyncSession, encounter_id: int) -> list[dict]:
        """Read both captains' reports for an encounter (public/read-only).

        Reports and their map codes are fetched with explicit awaited queries rather
        than via relationship attribute access: touching a lazily-loaded collection
        on a materialized ORM instance emits implicit IO, which raises
        ``MissingGreenlet`` under async SQLAlchemy. Grouping codes in Python keeps
        this a fixed two-query read regardless of ORM load state.
        """
        encounter = await self.encounter_repo.get(session, encounter_id)
        if not encounter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        reports = list(await self.report_repo.list_for_encounter(session, encounter_id))
        if not reports:
            return []

        codes = list(await self.map_code_repo.list_for_reports(session, [r.id for r in reports]))
        codes_by_report: dict[int, list[models.EncounterMapCode]] = {}
        for code in codes:
            codes_by_report.setdefault(code.report_id, []).append(code)

        reporter_ids = {r.reporter_user_id for r in reports if r.reporter_user_id is not None}
        names_by_user_id: dict[int, str] = {}
        if reporter_ids:
            # Analytical: an (id, name) projection for the labels, not a row load.
            rows = await session.execute(
                select(models.User.id, models.User.name).where(models.User.id.in_(reporter_ids))
            )
            names_by_user_id = dict(rows.all())

        return [
            serialize_captain_report(
                r,
                encounter,
                codes_by_report.get(r.id, []),
                reporter_name=names_by_user_id.get(r.reporter_user_id) if r.reporter_user_id else None,
            ).model_dump(mode="json")
            for r in reports
        ]

    async def get_result_audit(self, session: AsyncSession, encounter_id: int) -> list[dict]:
        """The encounter's result history, newest first.

        Explicit awaited query with the actor eagerly joined, for the same reason
        ``get_encounter_reports`` avoids relationship access: touching a lazily
        loaded collection on a materialized instance raises ``MissingGreenlet``
        under async SQLAlchemy.
        """
        rows = list(
            await self.audit_repo.list_for_encounter(
                session,
                encounter_id,
                options=[selectinload(models.EncounterResultAudit.actor)],
            )
        )
        return [
            {
                "id": row.id,
                "encounter_id": row.encounter_id,
                "actor_user_id": row.actor_user_id,
                "actor_name": row.actor.name if row.actor is not None else None,
                "action": row.action,
                "from_result_status": row.from_result_status,
                "to_result_status": row.to_result_status,
                "home_score_before": row.home_score_before,
                "away_score_before": row.away_score_before,
                "home_score_after": row.home_score_after,
                "away_score_after": row.away_score_after,
                "adopted_team_id": row.adopted_team_id,
                "source": row.source,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def _recompute_encounter_result(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
        *,
        actor_user_id: int,
    ) -> bool:
        """Recompute the derived encounter result from its captain reports.

        Returns ``True`` when the encounter was auto-confirmed (so the caller can run
        post-commit side effects like Challonge push).
        """
        reports = list(encounter.captain_reports)
        now = datetime.now(UTC)

        from_result_status = encounter.result_status
        home_score_before = encounter.home_score
        away_score_before = encounter.away_score

        if len(reports) < 2:
            encounter.result_status = EncounterResultStatus.PENDING_CONFIRMATION
            encounter.confirmed_at = None
            encounter.closeness = None
            await self._enqueue_tournament_recalculation(session, encounter.tournament_id)
            return False

        by_team = {r.team_id: r for r in reports}
        home_report = by_team.get(encounter.home_team_id)
        away_report = by_team.get(encounter.away_team_id)

        # Defensive: both team reports must be present for a two-report encounter.
        if home_report is None or away_report is None:
            encounter.result_status = EncounterResultStatus.PENDING_CONFIRMATION
            encounter.closeness = None
            await self._enqueue_tournament_recalculation(session, encounter.tournament_id)
            return False

        scores_match = (
            home_report.home_score == away_report.home_score and home_report.away_score == away_report.away_score
        )
        # A tournament may have the match-quality field disabled, so a report can
        # legitimately carry no rating; there is then nothing to average.
        if home_report.closeness is None or away_report.closeness is None:
            avg_closeness = None
        else:
            avg_closeness = (home_report.closeness + away_report.closeness) / 2.0

        if not scores_match:
            encounter.result_status = EncounterResultStatus.DISPUTED
            encounter.closeness = None
            record_result_transition(
                session,
                encounter,
                action=EncounterResultAuditAction.AUTO_DISPUTE,
                source="captain",
                actor_user_id=actor_user_id,
                from_result_status=from_result_status,
                home_score_before=home_score_before,
                away_score_before=away_score_before,
            )
            await self._enqueue_tournament_recalculation(session, encounter.tournament_id)
            return False

        encounter.closeness = None if avg_closeness is None else avg_closeness / 10.0
        await self.finalize.finalize_encounter_score(
            session,
            encounter.id,
            encounter=encounter,
            home_score=home_report.home_score,
            away_score=home_report.away_score,
            source="captain",
            result_status=EncounterResultStatus.CONFIRMED,
            confirmed_at=now,
        )
        record_result_transition(
            session,
            encounter,
            action=EncounterResultAuditAction.AUTO_CONFIRM,
            source="captain",
            actor_user_id=actor_user_id,
            from_result_status=from_result_status,
            home_score_before=home_score_before,
            away_score_before=away_score_before,
        )
        await self._enqueue_tournament_recalculation(session, encounter.tournament_id)
        await self._enqueue_encounter_completed(session, encounter)
        return True

    async def submit_captain_report(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser,
        encounter_id: int,
        *,
        home_score: int,
        away_score: int,
        closeness: int | None,
        map_codes: Sequence[MapCodeInput] = (),
        comment: str | None = None,
        custom_fields: dict[str, str] | None = None,
    ) -> models.Encounter:
        """Upsert the calling captain's report and recompute the derived result.

        ``home_score``/``away_score`` are in the encounter's home/away orientation.
        ``map_codes`` are ``(map_index, code)`` pairs; ``map_id`` is softly resolved
        from the veto pool when one is complete.

        Which of ``closeness``/``map_codes``/``comment`` and which custom fields are
        offered and mandatory comes from the tournament's report-form config; values
        for disabled fields are dropped rather than rejected, so a client holding a
        stale config cannot fail a submit it could not have known about.
        """
        if home_score < 0 or away_score < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="scores must be non-negative",
            )

        seen_indices: set[int] = set()
        for map_index, _code in map_codes:
            if map_index < 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="map_index must be >= 1",
                )
            if map_index in seen_indices:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"duplicate map_index {map_index}",
                )
            seen_indices.add(map_index)

        encounter = await self._load_encounter_with_reports(session, encounter_id)

        if not await is_encounter_live(session, encounter):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stage bracket is a preview and is not active yet; wait for the organizer to activate it",
            )

        if encounter.result_status == EncounterResultStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encounter result is confirmed; only an admin can change it",
            )

        _side, captain_user_id, team_id = await self._resolve_captain_identity(session, auth_user, encounter)

        # A captain report is the FINAL series score, so it must actually end the
        # series: a Bo3 cannot finish 1:0, and no side can win more maps than the
        # format has to give (review §6, "Завершение BoN"). Checked after the
        # captain is identified so a stranger still gets 403, not a hint about the
        # format. Admin paths stay advisory — a historical or technical result is
        # the organizer's call.
        if (
            not engine.series_complete(
                engine.SeriesScore(home_score, away_score, home_score + away_score), encounter.best_of
            )
            or max(home_score, away_score) > encounter.best_of // 2 + 1
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{home_score}:{away_score} is not a valid final score for a best-of-{encounter.best_of} series",
            )

        form = await self.report_forms.resolve_report_form(session, encounter.tournament_id)
        # Resolved before validation, not just before persisting the codes: a required
        # `map_codes` config may only demand a code for a slot the captain was offered.
        map_id_by_index = await self._picked_map_ids(session, encounter_id)
        submission = report_form.validate_submission(
            form,
            home_score=home_score,
            away_score=away_score,
            closeness=closeness,
            map_codes=map_codes,
            comment=comment,
            custom_fields=custom_fields,
            available_map_indices=report_form.series_map_indices(map_id_by_index, encounter.best_of),
        )

        report = next((r for r in encounter.captain_reports if r.team_id == team_id), None)
        if report is None:
            report = models.EncounterCaptainReport(encounter_id=encounter.id, team_id=team_id)
            # An empty collection assigned BEFORE the flush below, so the append that
            # follows it never reads the table. Once the row is persistent a
            # ``map_codes`` touch that was never loaded emits a lazy SELECT --
            # ``lazy="selectin"`` is a QUERY-time strategy and falls back to a plain
            # lazy load for a single instance -- and that implicit IO from sync
            # attribute access is ``MissingGreenlet`` under async SQLAlchemy. Only
            # the first report of a team hit this: the branch below re-uses a report
            # whose codes ``_load_encounter_with_reports`` already eager-loaded.
            report.map_codes = []
            session.add(report)
            encounter.captain_reports.append(report)
        else:
            # Drop existing codes up front so re-inserting the same (report_id,
            # map_index) never collides with rows pending deletion in one flush.
            await self.map_code_repo.delete_for_report(session, report.id)
            report.map_codes.clear()

        report.reporter_user_id = captain_user_id
        report.home_score = home_score
        report.away_score = away_score
        report.closeness = submission.closeness
        report.comment = submission.comment
        report.custom_fields_json = submission.custom_fields

        # Ensure the (possibly new) report has an id before attaching codes.
        await session.flush()

        for map_index, code in submission.map_codes:
            report.map_codes.append(
                models.EncounterMapCode(
                    map_index=map_index,
                    code=code,
                    map_id=map_id_by_index.get(map_index),
                )
            )

        confirmed = await self._recompute_encounter_result(session, encounter, actor_user_id=captain_user_id)
        await session.commit()

        if confirmed:
            challonge_links = await resolve_encounter_challonge(session, [encounter.id])
            if challonge_links.get(encounter.id) is not None:
                await sync_service.auto_push_on_confirm(session, encounter.id)

        await session.refresh(encounter)
        return encounter

    async def set_encounter_result(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        actor_user_id: int | None,
        home_score: int | None = None,
        away_score: int | None = None,
        closeness: int | None = None,
        adopt_report_team_id: int | None = None,
    ) -> models.Encounter:
        """Confirm an encounter result as an admin, in one transaction.

        This is THE admin write: the score, ``status``, ``result_status`` and the
        audit row move together, so a dispute can never be left half-resolved the
        way "edit the score, then confirm" could. The score is taken from the first
        source that yields one:

        1. an explicit ``home_score``/``away_score``;
        2. the report of ``adopt_report_team_id`` — "this side was right";
        3. both reports, when they already agree;
        4. the encounter's own score, when it is not still 0-0.

        Nothing left? 422 rather than finalizing a bogus 0-0 draw (which would also
        400 on an elimination stage, where a winner is required).
        """
        encounter = await self._load_encounter_with_reports(session, encounter_id)

        if encounter.result_status == EncounterResultStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Encounter result is already confirmed — reopen it first",
            )
        if (home_score is None) != (away_score is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="home_score and away_score must be provided together",
            )
        if closeness is not None and not 1 <= closeness <= 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="closeness must be between 1 and 10",
            )

        adopted_team_id: int | None = None
        if home_score is not None and away_score is not None:
            resolved_home, resolved_away = home_score, away_score
        elif adopt_report_team_id is not None:
            report = next((r for r in encounter.captain_reports if r.team_id == adopt_report_team_id), None)
            if report is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="That team has not reported this encounter",
                )
            resolved_home, resolved_away = report.home_score, report.away_score
            adopted_team_id = adopt_report_team_id
        else:
            reported = {(r.home_score, r.away_score) for r in encounter.captain_reports}
            if len(reported) == 1:
                resolved_home, resolved_away = next(iter(reported))
            elif (encounter.home_score, encounter.away_score) != (0, 0):
                resolved_home, resolved_away = encounter.home_score, encounter.away_score
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="result_score_unresolved: pass a score or adopt one of the reports",
                )

        if closeness is not None:
            encounter.closeness = closeness / 10.0
        else:
            # A tournament may have the match-quality field disabled, so skip the
            # reports that carry no rating rather than summing a None.
            closeness_values = [r.closeness for r in encounter.captain_reports if r.closeness is not None]
            if closeness_values:
                encounter.closeness = (sum(closeness_values) / len(closeness_values)) / 10.0

        from_result_status = encounter.result_status
        home_score_before = encounter.home_score
        away_score_before = encounter.away_score
        tournament_id = encounter.tournament_id

        await self.finalize.finalize_encounter_score(
            session,
            encounter.id,
            encounter=encounter,
            home_score=resolved_home,
            away_score=resolved_away,
            source="admin",
            result_status=EncounterResultStatus.CONFIRMED,
            confirmed_at=datetime.now(UTC),
        )
        record_result_transition(
            session,
            encounter,
            action=EncounterResultAuditAction.CONFIRM,
            source="admin",
            actor_user_id=actor_user_id,
            from_result_status=from_result_status,
            home_score_before=home_score_before,
            away_score_before=away_score_before,
            adopted_team_id=adopted_team_id,
        )
        await self._enqueue_tournament_recalculation(session, tournament_id)
        await self._enqueue_encounter_completed(session, encounter)
        await session.commit()

        challonge_links = await resolve_encounter_challonge(session, [encounter.id])
        if challonge_links.get(encounter.id) is not None:
            await sync_service.auto_push_on_confirm(session, encounter.id)

        await session.refresh(encounter)
        return encounter

    async def reopen_encounter_result(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        actor_user_id: int | None,
    ) -> models.Encounter:
        """Un-confirm an encounter so it can be played or reported again.

        The counterpart to :meth:`set_encounter_result`, and the only way out of a
        dispute an admin does not want to force-confirm. Captain reports are kept —
        reopening is a correction, not a purge, and the submissions remain the
        evidence. Anything the old result advanced downstream is cleared with it.
        """
        encounter = await self._load_encounter_with_reports(session, encounter_id)

        if encounter.result_status == EncounterResultStatus.NONE and encounter.status == EncounterStatus.OPEN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Encounter has no recorded result to reopen",
            )

        tournament_id = encounter.tournament_id
        await advancement.reset_encounter_result(
            session,
            encounter,
            action=EncounterResultAuditAction.REOPEN,
            actor_user_id=actor_user_id,
            source="admin",
        )
        await self._enqueue_tournament_recalculation(session, tournament_id)
        await session.commit()
        await session.refresh(encounter)
        return encounter


captain_service = CaptainService()

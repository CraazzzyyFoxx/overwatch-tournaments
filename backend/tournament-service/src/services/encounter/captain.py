"""Per-participation reporting of the WHOLE encounter, and the admin overrides
that settle it.

Each participation files its own report -- the final standing, how many games it
took, a closeness rating, an optional comment and the organizer's custom fields
-- independently; there is no submit/confirm handshake. The encounter's result
is DERIVED from them:

- not every live participation has reported -> ``pending_confirmation``;
- all reported, standings agree -> ``confirmed`` with source ``series_claim``,
  and the positions nobody played are cancelled;
- all reported, standings differ -> ``disputed``, for an organizer to settle.

A report is checked against the games already on record by
:func:`shared.domain.encounter_scoring.series_claim_errors`: it must name the
encounter's participations, claim at least the confirmed games and at most the
card, end the encounter under the rule's own end formula without having ended
earlier (which is what makes a 3:0 in a Bo3 impossible), and agree with the
computed totals when every claimed game is confirmed.

A participation may re-file until the encounter's result is confirmed; a
report filed afterwards still lands -- its codes, rating, comment and custom
fields -- but must state the confirmed score (``_reject_score_change``). Only
an organizer moves a confirmed result, through :meth:`set_encounter_result` or
:meth:`reopen_encounter_result`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.enums import (
    EncounterGameState,
    EncounterResultAuditAction,
    EncounterResultSource,
    EncounterResultStatus,
    EncounterStatus,
    MapPoolEntryStatus,
    PickBanKind,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_scoring import SeriesClaim, series_claim_errors
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.pick_ban import PickBanEntry, PickBanSession
from shared.models.encounter.report import EncounterTeamReport, EncounterTeamReportResult
from shared.models.encounter.team import EncounterTeam
from shared.repository import (
    EncounterRepository,
    EncounterResultAuditRepository,
    EncounterTeamReportRepository,
    UserRepository,
)
from shared.services.encounter.events import enqueue_encounter_completed
from shared.services.encounter.participants import active_teams
from shared.services.encounter.result import apply_result, hold_result, lock_encounter, reopen
from src import schemas
from src.services.bracket import advancement
from src.services.bracket.usability import is_encounter_live
from src.services.encounter import report_form
from src.services.encounter.dispute_review import notify_dispute
from src.services.encounter.games import EncounterGameService, encounter_game_service, require_filled_seats
from src.services.encounter.report_form import ReportFormService, report_form_service
from src.services.encounter.room_journal import record_room_event
from src.services.encounter.settle import enqueue_challonge_push, settle_confirmed
from src.services.tournament.events import enqueue_tournament_recalculation

__all__ = ("CaptainService", "ReportResultIn", "captain_service", "serialize_team_report")

# One per-position replay/match code: (position 1-based, code string). Defined
# by the report-form service, which validates them.
MapCodeInput = report_form.MapCodeInput


@dataclass(frozen=True, slots=True)
class ReportResultIn:
    """One participation's line of a series report.

    ``wins`` is ``None`` when the rule does not count wins (a lobby's card,
    where points alone decide); ``placement`` is ``None`` when the form does not
    ask for places.
    """

    encounter_team_id: int
    score: float
    placement: int | None = None
    wins: int | None = None


def serialize_team_report(
    report: EncounterTeamReport,
    results: Sequence[EncounterTeamReportResult],
    reporter_name: str | None = None,
) -> schemas.TeamReportRead:
    """The report payload shared by the public read and the admin list."""
    return schemas.TeamReportRead(
        id=report.id,
        encounter_id=report.encounter_id,
        encounter_team_id=report.encounter_team_id,
        reporter_user_id=report.reporter_user_id,
        reporter_name=reporter_name,
        games_played=report.games_played,
        basis_version=report.basis_version,
        closeness=report.closeness,
        comment=report.comment,
        # Answers only: enclayer01 parks a list audit (``historical_replay_codes``) in the same blob.
        custom_fields={
            key: value for key, value in (report.custom_fields_json or {}).items() if isinstance(value, str)
        },
        results=[
            schemas.TeamReportResultRead(
                encounter_team_id=row.encounter_team_id,
                score=row.score,
                placement=row.placement,
                wins=row.wins,
            )
            for row in sorted(results, key=lambda row: row.encounter_team_id)
        ],
        created_at=report.created_at.isoformat() if report.created_at else None,
        updated_at=report.updated_at.isoformat() if report.updated_at else None,
    )


class CaptainService:
    """The participant-facing result flow plus the admin overrides that resolve it."""

    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        report_repo: EncounterTeamReportRepository = EncounterTeamReportRepository(),
        audit_repo: EncounterResultAuditRepository = EncounterResultAuditRepository(),
        user_repo: UserRepository = UserRepository(),
        report_forms: ReportFormService = report_form_service,
        games: EncounterGameService = encounter_game_service,
    ) -> None:
        self.encounter_repo = encounter_repo
        self.report_repo = report_repo
        self.audit_repo = audit_repo
        self.user_repo = user_repo
        self.report_forms = report_forms
        self.games = games

    # -- loading -----------------------------------------------------------
    async def _load_encounter(self, session: AsyncSession, encounter_id: int, *, for_update: bool = True) -> Encounter:
        """The encounter, locked or not. State polling opts out of the lock --
        the room's state read is pure."""
        if for_update:
            return await lock_encounter(session, encounter_id)
        encounter = await self.encounter_repo.get(session, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
        return encounter

    async def resolve_participant(
        self, session: AsyncSession, auth_user: models.AuthUser, encounter: Encounter
    ) -> tuple[EncounterTeam, int, bool, int | None]:
        """``(seat, player id, is_captain, own seat)`` of this account in the encounter (spec §7.3).

        A tournament seat is found through its team's live ``Team.captain_id`` only, so it is always the captain's. A
        mix seat is found through the roster snapshot (``encounter.team_member`` -> workspace member -> player) and
        carries the snapshot's ``is_captain``. 403 without a linked player or a seat.

        The own seat is the mix snapshot's ``encounter.team_member`` id (a member step names it, spec §11.6); ``None``
        for a tournament seat.
        """
        player = await self.user_repo.get_by_auth_user_id(session, auth_user.id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No player profile linked to your account",
            )
        seats = await active_teams(session, encounter.id)
        if encounter.custom_game_id is not None:
            row = (
                await session.execute(
                    sa.select(
                        models.EncounterTeamMember.encounter_team_id,
                        models.EncounterTeamMember.is_captain,
                        models.EncounterTeamMember.id,
                    )
                    .join(
                        models.WorkspaceMember,
                        models.WorkspaceMember.id == models.EncounterTeamMember.workspace_member_id,
                    )
                    .where(
                        models.EncounterTeamMember.encounter_id == encounter.id,
                        models.EncounterTeamMember.active.is_(True),
                        models.WorkspaceMember.player_id == player.id,
                    )
                )
            ).first()
            for seat in seats:
                if row is not None and seat.id == row.encounter_team_id:
                    return seat, player.id, bool(row.is_captain), row.id
        else:
            team_ids = [seat.team_id for seat in seats if seat.team_id is not None]
            if team_ids:
                rows = await session.execute(
                    sa.select(models.Team.id).where(models.Team.id.in_(team_ids), models.Team.captain_id == player.id)
                )
                captained = set(rows.scalars())
                for seat in seats:
                    if seat.team_id in captained:
                        return seat, player.id, True, None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not captain any team in this encounter",
        )

    async def captain_seat(
        self, session: AsyncSession, auth_user: models.AuthUser, encounter: Encounter
    ) -> tuple[EncounterTeam, int]:
        """The seat this account captains and its player id; 403 otherwise. Every captain-only write goes here."""
        seat, player_id, is_captain, _member = await self.resolve_participant(session, auth_user, encounter)
        if not is_captain:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not captain any team in this encounter",
            )
        return seat, player_id

    async def acting_seat(
        self, session: AsyncSession, auth_user: models.AuthUser, encounter: Encounter, member_id: int | None
    ) -> tuple[EncounterTeam, bool, int | None]:
        """``(seat, is_captain, own seat)`` this account acts for on a pick-ban step (spec §11.3, §11.6 R4-9): the
        own seat is ``resolve_participant``'s, which the action's answer reads the room as.

        Without ``member_id`` the step is the team's and only its captain acts. With one -- a mix's member pick --
        the member themselves or their team's captain acts; anyone else, a member of the other team included, is a
        403. A tournament seat names no members: its captain is resolved as ever and the action service refuses the
        ``member_id`` (422), the one check the organizer route shares. Hosts act through the organizer route."""
        seat, _player_id, is_captain, own = await self.resolve_participant(session, auth_user, encounter)
        if member_id is None or encounter.custom_game_id is None:
            if not is_captain:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not captain any team in this encounter",
                )
            return seat, True, own
        team = await session.scalar(
            sa.select(models.EncounterTeamMember.encounter_team_id).where(
                models.EncounterTeamMember.id == member_id,
                models.EncounterTeamMember.encounter_id == encounter.id,
                models.EncounterTeamMember.active.is_(True),
            )
        )
        if team != seat.id or not (is_captain or own == member_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You pick for yourself, or as captain for your own team"
            )
        return seat, is_captain, own

    # -- reads -------------------------------------------------------------
    async def _position_map_ids(self, session: AsyncSession, encounter_id: int) -> dict[int, int]:
        """``position`` (1-based, in play order) -> the map the veto settled.

        ``PickBanEntry.order`` is NOT the index: it is a per-round display field
        spaced by ``round * 1000``, so the index is the position in PLAY order,
        which is what ``action_index`` records. Empty when there is no veto.
        """
        rows = await session.execute(
            sa.select(PickBanEntry.order, PickBanEntry.action_index, PickBanEntry.item_id)
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
        """Every participation's series report (public/read-only).

        Explicit awaited queries rather than relationship attribute access:
        touching a lazily loaded collection on a materialized instance emits
        implicit IO, which is ``MissingGreenlet`` under async SQLAlchemy.
        """
        encounter = await self.encounter_repo.get(session, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        reports = list(await self.report_repo.list_for_encounter(session, encounter_id))
        if not reports:
            return []
        results = await self.report_repo.results_for_reports(session, [row.id for row in reports])

        reporter_ids = {row.reporter_user_id for row in reports if row.reporter_user_id is not None}
        names: dict[int, str] = {}
        if reporter_ids:
            rows = await session.execute(
                sa.select(models.User.id, models.User.name).where(models.User.id.in_(reporter_ids))
            )
            names = dict(rows.all())
        return [
            serialize_team_report(
                row,
                results.get(row.id, []),
                reporter_name=names.get(row.reporter_user_id) if row.reporter_user_id else None,
            ).model_dump(mode="json")
            for row in reports
        ]

    async def get_result_audit(self, session: AsyncSession, encounter_id: int) -> list[dict]:
        """The encounter's result history, newest first."""
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
                "result_version": row.result_version,
                "actor_user_id": row.actor_user_id,
                "actor_name": row.actor.name if row.actor is not None else None,
                "action": row.action,
                "from_result_status": row.from_result_status,
                "to_result_status": row.to_result_status,
                "snapshot_scope": row.snapshot_scope,
                "game_id": row.game_id,
                "before": row.before,
                "after": row.after,
                "adopted_team_id": row.adopted_team_id,
                "reason": row.reason,
                "source": row.source,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    # -- the participant's report ------------------------------------------
    async def submit_team_report(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        encounter_team_id: int,
        reporter_user_id: int | None,
        games_played: int,
        results: Sequence[ReportResultIn],
        basis_version: int,
        closeness: int | None = None,
        comment: str | None = None,
        custom_fields: Mapping[str, str] | None = None,
        map_codes: Sequence[MapCodeInput] = (),
        actor_auth_user_id: int | None = None,
    ) -> Encounter:
        """Upsert one participation's report of the finished encounter.

        Which of ``closeness``/``map_codes``/``comment`` and which custom fields
        are offered and mandatory comes from the tournament's report-form
        config; values for disabled fields are dropped rather than rejected, so
        a client holding a stale config cannot fail a submit it could not have
        known about. On a confirmed encounter the report is evidence only: its
        score has to be the confirmed one and the result is not re-derived, only
        the encounter's closeness follows the new rating. Commits.
        """
        encounter = await lock_encounter(session, encounter_id)
        if not await is_encounter_live(session, encounter):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stage bracket is a preview and is not active yet; wait for the organizer to activate it",
            )
        # A confirmed result is official -- the games, an agreement or an
        # organizer decided it. A late report still files everything else.
        locked = encounter.result_status == EncounterResultStatus.CONFIRMED
        # A filed report parks the result in ``pending_confirmation`` and that
        # takes a version of its own, but it moves no standing: the opponent's
        # form, filled in against the version before it, is still about the same
        # result. Only a version that came from anything else makes it stale.
        holds = await self.audit_repo.pending_holds_since_last_decision(session, encounter.id)
        if not encounter.result_version - holds <= basis_version <= encounter.result_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    ApiExc(
                        code="stale_state",
                        msg=f"This encounter has moved on (version {encounter.result_version}); reload before reporting",
                    )
                ],
            )

        seats = await active_teams(session, encounter.id)
        live = {seat.id for seat in seats}
        if encounter_team_id not in live:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="That participation does not play in this encounter",
            )
        require_filled_seats(encounter, seats)
        if locked:
            self._reject_score_change(encounter, seats, games_played, results)
        else:
            await self._reject_impossible_report(session, encounter, seats, games_played, results)

        form = await self.report_forms.resolve_report_form(session, encounter.tournament_id)
        map_id_by_position = await self._position_map_ids(session, encounter.id)
        submission = report_form.validate_submission(
            form,
            games_played=games_played,
            closeness=closeness,
            map_codes=map_codes,
            comment=comment,
            custom_fields=dict(custom_fields or {}),
            available_map_indices=report_form.series_map_indices(map_id_by_position, encounter.best_of),
        )

        report = await self.report_repo.get_by(session, encounter_id=encounter.id, encounter_team_id=encounter_team_id)
        if report is None:
            report = await self.report_repo.create(
                session,
                EncounterTeamReport(
                    encounter_id=encounter.id,
                    encounter_team_id=encounter_team_id,
                    reporter_user_id=reporter_user_id,
                    games_played=games_played,
                    basis_version=basis_version,
                ),
            )
            changed = True
        else:
            changed = report.games_played != games_played or self._shape(
                await self._results_of(session, report)
            ) != self._claim_shape(results)
            report.reporter_user_id = reporter_user_id
            report.games_played = games_played
            report.basis_version = basis_version
        report.closeness = submission.closeness
        report.comment = submission.comment
        report.custom_fields_json = dict(submission.custom_fields)
        await self.report_repo.replace_results(
            session,
            report,
            [
                EncounterTeamReportResult(
                    report_id=report.id,
                    encounter_id=encounter.id,
                    encounter_team_id=item.encounter_team_id,
                    score=float(item.score),
                    placement=item.placement,
                    wins=item.wins,
                )
                for item in results
            ],
        )
        await self._write_replay_codes(session, encounter, encounter_team_id, submission.map_codes)

        if changed:
            await record_room_event(
                session,
                encounter.id,
                action="series_reported",
                source="captain",
                encounter_team_id=encounter_team_id,
                actor_auth_user_id=actor_auth_user_id,
                data={"games_played": games_played},
            )

        if locked:
            encounter.closeness = self._closeness(await self.report_repo.list_for_encounter(session, encounter.id))
            await session.commit()
            return encounter

        confirmed = await self._recompute_from_reports(
            session, encounter, seats, actor_user_id=reporter_user_id, actor_auth_user_id=actor_auth_user_id
        )
        if confirmed:
            await enqueue_challonge_push(session, encounter)
        else:
            await enqueue_tournament_recalculation(session, encounter.tournament_id)
        await session.commit()
        return encounter

    @staticmethod
    def _reject_score_change(
        encounter: Encounter,
        seats: Sequence[EncounterTeam],
        games_played: int,
        results: Sequence[ReportResultIn],
    ) -> None:
        """Refuse a late report that moves the confirmed score.

        Not :meth:`_reject_impossible_report`: the standing is already decided,
        and an organizer's (a forfeit's 1:0 in a Bo3) need not be one the
        captains could have claimed -- checking it again would leave the
        captains no report to file.
        """
        if {item.encounter_team_id: float(item.score) for item in results} != {seat.id: seat.score for seat in seats}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    ApiExc(
                        code="result_locked",
                        msg="This encounter's result is confirmed; its score can only be changed by an organizer",
                    )
                ],
            )
        if games_played > encounter.best_of:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=[ApiExc(code="series_claim_games_played", msg="More games than the card holds")],
            )

    async def _reject_impossible_report(
        self,
        session: AsyncSession,
        encounter: Encounter,
        seats: Sequence[EncounterTeam],
        games_played: int,
        results: Sequence[ReportResultIn],
    ) -> None:
        """Refuse a standing this encounter cannot have ended on.

        The whole check is :func:`series_claim_errors`, the one implementation
        of "can this card end like that", shared with the admin write.
        """
        errors = series_claim_errors(
            await self.games.rules(session, encounter),
            best_of=encounter.best_of,
            team_ids=[seat.id for seat in seats],
            confirmed_games=await self.games.confirmed_game_lines(session, encounter, seats=seats),
            claim=SeriesClaim(
                games_played=games_played,
                totals={item.encounter_team_id: float(item.score) for item in results},
                wins=(
                    {item.encounter_team_id: int(item.wins) for item in results}
                    if all(item.wins is not None for item in results) and results
                    else None
                ),
                placements=(
                    {item.encounter_team_id: int(item.placement) for item in results}
                    if all(item.placement is not None for item in results) and results
                    else None
                ),
            ),
        )
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=[ApiExc(code=code, msg=f"This report contradicts the encounter: {code}") for code in errors],
            )

    async def _write_replay_codes(
        self,
        session: AsyncSession,
        encounter: Encounter,
        encounter_team_id: int,
        map_codes: Sequence[MapCodeInput],
    ) -> None:
        """Store the reporter's replay codes on the positions they name.

        The code belongs to the participation that played the position
        (``game_team.replay_code``). A freeplay card opens its games as claims
        arrive, so a captain who reports the series straight away names
        positions with no row yet: those are opened (planned, every live seat
        in them, like ``ensure_next_game`` does) rather than losing the code.
        Only positions of the card (``1..best_of``) are accepted; a position
        past it is dropped, not an error. A confirmed card is closed: its codes
        land on the rows it has, including the positions a series claim
        cancelled, and never open a new one.
        """
        if not map_codes:
            return
        closed = encounter.result_status == EncounterResultStatus.CONFIRMED
        # Series order, so a re-opened position's newest row is the one kept.
        by_position = {
            game.position: game for game in await self.games.list_games(session, encounter.id, include_cancelled=closed)
        }
        wanted = {position for position, _code in map_codes if 1 <= position <= encounter.best_of}
        # From 1, so the room's "next position" never skips one the codes did not name.
        for position in range(1, max(wanted, default=0) + 1):
            if position not in by_position and not closed:
                by_position[position] = await self.games.open_game(session, encounter, position=position)
        lines = await self.games.lines_by_game(session, list(by_position.values()))
        for position, code in map_codes:
            game = by_position.get(position) if position in wanted else None
            if game is None:
                continue
            for row in lines.get(game.id, []):
                if row.encounter_team_id == encounter_team_id:
                    row.replay_code = code
        await session.flush()

    async def _results_of(self, session: AsyncSession, report: EncounterTeamReport) -> list[EncounterTeamReportResult]:
        return (await self.report_repo.results_for_reports(session, [report.id])).get(report.id, [])

    @staticmethod
    def _shape(rows: Sequence[EncounterTeamReportResult]) -> tuple:
        """What two reports have to agree on, order-independent."""
        return tuple(sorted((row.encounter_team_id, row.score, row.placement, row.wins) for row in rows))

    @staticmethod
    def _claim_shape(results: Sequence[ReportResultIn]) -> tuple:
        return tuple(sorted((item.encounter_team_id, float(item.score), item.placement, item.wins) for item in results))

    @staticmethod
    def _closeness(reports: Sequence[EncounterTeamReport]) -> float | None:
        """The reports' mean rating (1..10 stars) as the encounter's 0..1 closeness."""
        ratings = [row.closeness for row in reports if row.closeness is not None]
        return (sum(ratings) / len(ratings)) / 10.0 if ratings else None

    async def _recompute_from_reports(
        self,
        session: AsyncSession,
        encounter: Encounter,
        seats: Sequence[EncounterTeam],
        *,
        actor_user_id: int | None,
        actor_auth_user_id: int | None,
    ) -> bool:
        """Derive the encounter's result from its reports. True once confirmed."""
        reports = list(await self.report_repo.list_for_encounter(session, encounter.id))
        results = await self.report_repo.results_for_reports(session, [row.id for row in reports])
        live = {seat.id for seat in seats}
        reported = {row.encounter_team_id for row in reports}

        if not live.issubset(reported):
            # A captain re-filing while the others are still owed changes nothing
            # the result can show; only the move INTO pending is a transition.
            if encounter.result_status != EncounterResultStatus.PENDING_CONFIRMATION:
                await hold_result(
                    session,
                    encounter,
                    status=EncounterResultStatus.PENDING_CONFIRMATION,
                    action=EncounterResultAuditAction.AUTO_PENDING,
                    audit_source="series_claim",
                    actor_user_id=actor_user_id,
                )
            return False

        standing = {self._shape(results.get(row.id, [])) for row in reports if row.encounter_team_id in live}
        games = {row.games_played for row in reports if row.encounter_team_id in live}
        if len(standing) > 1 or len(games) > 1:
            await self._mark_disputed(session, encounter, actor_user_id=actor_user_id)
            await notify_dispute(session, encounter, seats=seats, actor_auth_user_id=actor_auth_user_id)
            return False

        agreed = next(row for row in reports if row.encounter_team_id in live)
        lines = results.get(agreed.id, [])
        encounter.closeness = self._closeness(reports)
        await apply_result(
            session,
            encounter,
            source=EncounterResultSource.SERIES_CLAIM,
            totals={row.encounter_team_id: float(row.score) for row in lines},
            placements={row.encounter_team_id: row.placement for row in lines if row.placement is not None}
            or self._places_from_scores(lines),
            action=EncounterResultAuditAction.AUTO_CONFIRM,
            audit_source="series_claim",
            actor_user_id=actor_user_id,
            reason=None,
        )
        # The card's unplayed tail is history the encounter never had: the
        # report IS the result, so a PLANNED position left open would offer a
        # game nobody may play.
        await self._cancel_unplayed(session, encounter, actor_user_id=actor_user_id)
        await enqueue_encounter_completed(session, encounter, source_service="tournament-service")
        await settle_confirmed(session, encounter)
        return True

    @staticmethod
    def _places_from_scores(lines: Sequence[EncounterTeamReportResult | ReportResultIn]) -> dict[int, int]:
        """Competition ranking over the reported (or stated) totals, best first.

        Used only when the form -- or the organizer -- gives no places: a
        standing without one would leave every seat unplaced, and the bracket
        resolves its links by place.
        """
        ordered = sorted(lines, key=lambda row: -float(row.score))
        places: dict[int, int] = {}
        for index, row in enumerate(ordered):
            previous = ordered[index - 1] if index else None
            places[row.encounter_team_id] = (
                places[previous.encounter_team_id]
                if previous is not None and float(previous.score) == float(row.score)
                else index + 1
            )
        return places

    async def _cancel_unplayed(self, session: AsyncSession, encounter: Encounter, *, actor_user_id: int | None) -> None:
        unplayed = [
            game
            for game in await self.games.list_games(session, encounter.id)
            if game.state != EncounterGameState.CONFIRMED
        ]
        if unplayed:
            await self.games.cancel_games(
                session, encounter, unplayed, actor_user_id=actor_user_id, reason="series_reported"
            )

    async def _mark_disputed(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        actor_user_id: int | None,
    ) -> None:
        """Record the contradiction. The standing is untouched -- nobody's
        numbers are adopted by a dispute, only the status moves."""
        await hold_result(
            session,
            encounter,
            status=EncounterResultStatus.DISPUTED,
            action=EncounterResultAuditAction.AUTO_DISPUTE,
            audit_source="series_claim",
            actor_user_id=actor_user_id,
        )

    # -- the organizer's overrides -----------------------------------------
    async def set_encounter_result(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        results: Sequence[ReportResultIn],
        reason: str,
        actor_user_id: int | None,
        adopt_report_team_id: int | None = None,
        closeness: int | None = None,
    ) -> Encounter:
        """Confirm an encounter result as an organizer, in one transaction.

        THE admin write: the standing, ``status``, ``result_status`` and the
        journal row move together, so a dispute can never be left half-resolved.
        ``reason`` is required -- an admin result overrides what the
        participants said, and the journal has to say why. Pass
        ``adopt_report_team_id`` to take one participation's report as truth
        instead of stating the numbers.
        """
        if not (reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="reason_required", msg="An admin result needs a stated reason")],
            )
        encounter = await lock_encounter(session, encounter_id)
        if encounter.result_status == EncounterResultStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[ApiExc(code="result_locked", msg="Encounter result is already confirmed — reopen it first")],
            )
        if closeness is not None and not 1 <= closeness <= 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="closeness must be between 1 and 10",
            )

        adopted_team_id: int | None = None
        if adopt_report_team_id is not None:
            report = await self.report_repo.get_by(
                session, encounter_id=encounter.id, encounter_team_id=adopt_report_team_id
            )
            if report is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="That participation has not reported this encounter",
                )
            lines = await self._results_of(session, report)
            results = [
                ReportResultIn(
                    encounter_team_id=row.encounter_team_id,
                    score=row.score,
                    placement=row.placement,
                    wins=row.wins,
                )
                for row in lines
            ]
            adopted_team_id = adopt_report_team_id
        if not results:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    ApiExc(
                        code="result_score_unresolved",
                        msg="Pass a standing or adopt one of the reports",
                    )
                ],
            )

        if closeness is not None:
            encounter.closeness = closeness / 10.0
        placements = {item.encounter_team_id: item.placement for item in results if item.placement is not None}
        await apply_result(
            session,
            encounter,
            source=EncounterResultSource.ADMIN,
            totals={item.encounter_team_id: float(item.score) for item in results},
            placements=placements or self._places_from_scores(results),
            action=EncounterResultAuditAction.CONFIRM,
            audit_source="admin",
            actor_user_id=actor_user_id,
            reason=reason,
        )
        if adopted_team_id is not None:
            # ``apply_result`` journals the transition; the adopted report is
            # the one thing it cannot know, so it is stamped on the row it just
            # wrote rather than in a second row the version key would refuse.
            latest = await self.audit_repo.get_by(
                session, encounter_id=encounter.id, result_version=encounter.result_version
            )
            if latest is not None:
                latest.adopted_team_id = adopted_team_id
        await self._cancel_unplayed(session, encounter, actor_user_id=actor_user_id)
        await enqueue_encounter_completed(session, encounter, source_service="tournament-service")
        await settle_confirmed(session, encounter)
        await enqueue_challonge_push(session, encounter)
        await session.commit()
        return encounter

    async def reopen_encounter_result(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        actor_user_id: int,
        reason: str,
    ) -> Encounter:
        """Un-confirm an encounter so it can be played or reported again.

        The counterpart to :meth:`set_encounter_result`, and the only way out of
        a dispute an organizer does not want to force-confirm. Reports are kept
        -- reopening is a correction, not a purge, and the submissions remain
        the evidence. Whatever the old result advanced downstream is unwound
        with it (:func:`advancement.reset_downstream`).
        """
        encounter = await lock_encounter(session, encounter_id)
        if encounter.result_status == EncounterResultStatus.NONE and encounter.status == EncounterStatus.OPEN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Encounter has no recorded result to reopen",
            )
        await reopen(session, encounter, actor_user_id=actor_user_id, reason=reason)
        await advancement.reset_downstream(session, encounter, actor_user_id=actor_user_id)
        await enqueue_tournament_recalculation(session, encounter.tournament_id)
        await session.commit()
        return encounter


captain_service = CaptainService()

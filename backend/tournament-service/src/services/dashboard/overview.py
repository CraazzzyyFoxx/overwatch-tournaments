"""The organizer dashboard of one workspace: phase cards, timeline, work queue and backlog.

A card is every tournament that is not finished, plus a ``completed`` one inside
its wrap-up window (14 days after ``finished_at``) whose wrap-up is not done.
Round trips: the candidates (their per-tournament extras, the granted readiness
counts included, ride as correlated scalar subqueries), one GROUP BY over their
encounters, the backlog (newest rows plus window totals in one statement) and
the roster's identity count. A card costs no statement of its own: its readiness
is assembled from the candidate row and the encounter counts.

``wrap_up.done`` is decided on unmasked data: whether a completed tournament
still has a card must not depend on who is looking. Every other gated value is
masked to ``None`` (never zero) after it is computed; the work-queue issues are
derived from the masked card, so they inherit the same gates.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import astuple, dataclass
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.tournament_state import FINISHED_STATUSES, PHASE_ORDER
from src import schemas
from src.services.dashboard.readiness import (
    build_readiness,
    has_enabled_achievement_rules,
    latest_evaluation_run_status,
    setup_counts,
    standings_recalc_pending,
    team_counts,
)

__all__ = ("AdminDashboardService", "DashboardPermissions", "overview")

_TS = enums.TournamentStatus

WRAP_UP_WINDOW = timedelta(days=14)
TIMELINE_WINDOW = timedelta(days=7)
#: A phase start this late without the status having moved is overdue (the worker tick needs a moment).
OVERDUE_GRACE = timedelta(minutes=10)
#: Pending registrations turn critical when registration closes sooner than this.
REGISTRATION_URGENT = timedelta(hours=24)
BACKLOG_ROWS = 20

_PHASES: dict[enums.TournamentStatus, schemas.DashboardPhase] = {
    _TS.ANNOUNCEMENT: "preparation",
    _TS.REGISTRATION: "registration",
    _TS.CHECK_IN: "formation",
    _TS.DRAFT: "formation",
    _TS.LIVE: "live",
    _TS.PLAYOFFS: "live",
    _TS.COMPLETED: "wrap_up",
}
_ACHIEVEMENTS_SETTLED = frozenset({"done", "not_configured"})
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_RESOURCES = ("tournament", "team", "match", "user", "achievement")


@dataclass(frozen=True)
class DashboardPermissions:
    """The caller's workspace ``<resource>.read`` grants; each unmasks one field group."""

    tournament_read: bool
    team_read: bool
    match_read: bool
    user_read: bool
    achievement_read: bool

    @classmethod
    def of(cls, user: Any, workspace_id: int) -> DashboardPermissions:
        return cls(*(user.has_workspace_permission(workspace_id, resource, "read") for resource in _RESOURCES))

    @property
    def any_granted(self) -> bool:
        return any(astuple(self))


def _live_condition(now: datetime) -> sa.ColumnElement[bool]:
    """Copy of tournament-service ``services/encounter/service.py::_live_condition`` (services never import
    each other): a ball in play, a game position reported, or a pending match past its slot."""
    encounter = models.Encounter
    return sa.or_(
        sa.and_(encounter.started_at.is_not(None), encounter.ended_at.is_(None)),
        sa.and_(encounter.status == enums.EncounterStatus.PENDING, encounter.current_game_position.is_not(None)),
        sa.and_(
            encounter.status == enums.EncounterStatus.PENDING,
            encounter.scheduled_at <= now,
            encounter.ended_at.is_(None),
        ),
    )


def _timeline_events(tournament: models.Tournament, now: datetime) -> list[schemas.DashboardTimelineEvent]:
    """The tournament's schedule boundaries inside ``[now, now + 7d]``, plus every overdue phase start."""
    events = []
    for entry in tournament.phase_schedule:
        for edge, at in (("start", entry.starts_at), ("end", entry.ends_at)):
            if at is None:
                continue
            overdue = (
                edge == "start"
                and at <= now - OVERDUE_GRACE
                and PHASE_ORDER[tournament.status] < PHASE_ORDER[entry.status]
            )
            if overdue or now <= at <= now + TIMELINE_WINDOW:
                events.append(
                    schemas.DashboardTimelineEvent(
                        tournament_id=tournament.id,
                        tournament_name=tournament.name,
                        status=entry.status.value,
                        edge=edge,
                        at=at,
                        overdue=overdue,
                    )
                )
    return events


def _wrap_up(row: sa.Row, counts: Counter, permissions: DashboardPermissions) -> schemas.DashboardWrapUp:
    results_open = counts["pending_confirmation"] + counts["disputed"]
    logs_used = counts["with_logs"] > 0
    achievements = (row.run_status or "none") if row.has_achievement_rules else "not_configured"
    done = (
        results_open == 0
        and (not logs_used or counts["duels_with_logs"] >= counts["duels"])
        and achievements in _ACHIEVEMENTS_SETTLED
        and not row.recalc_pending
    )
    match_read = permissions.match_read
    return schemas.DashboardWrapUp(
        done=done,
        results_open=results_open if match_read else None,
        logs_used=logs_used if match_read else None,
        duel_encounters_total=counts["duels"] if match_read else None,
        duel_encounters_with_logs=counts["duels_with_logs"] if match_read else None,
        achievements_status=achievements if permissions.achievement_read else None,
        standings_recalc_pending=row.recalc_pending if permissions.tournament_read else None,
    )


def _card_issues(
    card: schemas.DashboardTournamentCard,
    *,
    phase_overdue: bool,
    slots_empty: int | None,
    now: datetime,
) -> list[schemas.DashboardIssue]:
    """The card's work-queue items, in key order. A masked group is ``None`` on the card and so raises nothing."""
    found: list[tuple[str, str, int | None]] = []
    play = card.play
    if play is not None:
        for key, count in (
            ("results_disputed", play.encounters_disputed),
            ("results_overdue", play.encounters_overdue),
            ("results_pending_confirmation", play.encounters_pending_confirmation),
        ):
            if count > 0:
                found.append((key, "critical", count))
    if phase_overdue:
        found.append(("phase_overdue", "critical", None))

    readiness = card.readiness
    if card.phase in ("registration", "formation"):
        if readiness.registrations_pending:
            closes = card.registration_closes_at
            severity = "critical" if closes is not None and closes - now < REGISTRATION_URGENT else "warning"
            found.append(("registrations_pending", severity, readiness.registrations_pending))
        if card.team_formation == "balancer" and readiness.pool_need_fix:
            found.append(("pool_need_fix", "warning", readiness.pool_need_fix))
        if readiness.registrations_approved is not None:
            unranked = readiness.registrations_approved - (readiness.registrations_ranked or 0)
            if unranked > 0:
                found.append(("ranks_missing", "warning", unranked))
    if card.phase in ("formation", "live"):
        if card.team_formation == "balancer" and readiness.balance_saved and readiness.balance_exported_at is None:
            found.append(("balance_not_exported", "warning", None))
        if slots_empty:
            found.append(("stage_slots_empty", "warning", slots_empty))

    wrap_up = card.wrap_up
    if wrap_up is not None:
        if wrap_up.logs_used and wrap_up.duel_encounters_with_logs < wrap_up.duel_encounters_total:
            found.append(("logs_missing", "warning", wrap_up.duel_encounters_total - wrap_up.duel_encounters_with_logs))
        if wrap_up.achievements_status is not None and wrap_up.achievements_status not in _ACHIEVEMENTS_SETTLED:
            found.append(("achievements_pending", "warning", None))
        if wrap_up.standings_recalc_pending:
            found.append(("standings_recalc_pending", "warning", None))

    return [
        schemas.DashboardIssue(
            key=key, severity=severity, tournament_id=card.id, tournament_name=card.name, count=count
        )
        for key, severity, count in found
    ]


class AdminDashboardService:
    """Assembles :class:`schemas.AdminDashboard`; ``now`` is injected so the windows are testable."""

    async def get_dashboard(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        permissions: DashboardPermissions,
        now: datetime,
    ) -> schemas.AdminDashboard:
        candidates = await self._candidates(session, workspace_id, permissions, now)
        encounters = await self._encounter_counts(session, [row.Tournament.id for row in candidates], now)

        built: list[
            tuple[
                tuple,
                schemas.DashboardTournamentCard,
                list[schemas.DashboardTimelineEvent],
                list[schemas.DashboardIssue],
            ]
        ] = []
        for row in candidates:
            tournament: models.Tournament = row.Tournament
            counts = encounters.get(tournament.id, Counter())
            phase = _PHASES[tournament.status]
            wrap_up = None
            if phase == "wrap_up":
                wrap_up = _wrap_up(row, counts, permissions)
                if wrap_up.done:
                    continue
            schedule = tournament.phase_schedule
            deadline = min(
                (at for entry in schedule for at in (entry.starts_at, entry.ends_at) if at is not None and at > now),
                default=None,
            )
            card = schemas.DashboardTournamentCard(
                id=tournament.id,
                name=tournament.name,
                discipline=tournament.discipline,
                status=tournament.status.value,
                phase=phase,
                is_hidden=tournament.is_hidden,
                logo_url=tournament.logo_url,
                cover_image_url=tournament.cover_image_url,
                team_formation=tournament.team_formation,
                start_date=tournament.start_date,
                end_date=tournament.end_date,
                finished_at=row.finished_at if phase == "wrap_up" else None,
                phase_schedule=[
                    schemas.DashboardScheduleEntry(
                        status=entry.status.value, starts_at=entry.starts_at, ends_at=entry.ends_at
                    )
                    for entry in schedule
                ]
                if permissions.tournament_read
                else [],
                next_deadline_at=deadline if permissions.tournament_read else None,
                registration_closes_at=next(
                    (entry.ends_at for entry in schedule if entry.status == _TS.REGISTRATION), None
                )
                if tournament.status == _TS.REGISTRATION
                else None,
                registrations_last_24h=row.registrations_last_24h if permissions.team_read else None,
                has_challonge_source=row.has_challonge_source,
                readiness=build_readiness(
                    tournament,
                    {**row._mapping, **counts},
                    can_tournament_read=permissions.tournament_read,
                    can_team_read=permissions.team_read,
                    can_match_read=permissions.match_read,
                    can_achievement_read=permissions.achievement_read,
                ),
                play=schemas.DashboardPlay(
                    encounters_total=counts["total"],
                    encounters_completed=counts["completed"],
                    encounters_live=counts["live"],
                    encounters_overdue=counts["overdue"],
                    encounters_pending_confirmation=counts["pending_confirmation"],
                    encounters_disputed=counts["disputed"],
                )
                if permissions.match_read
                else None,
                wrap_up=wrap_up,
            )
            # Ordered on the unmasked deadline: the order is not a secret, the schedule fields are masked.
            group = 0 if phase == "live" else 2 if phase == "wrap_up" else 1
            key = (group, deadline is None, deadline.timestamp() if deadline else 0.0, -tournament.id)
            events = _timeline_events(tournament, now)
            card_issues = _card_issues(
                card,
                phase_overdue=permissions.tournament_read and any(event.overdue for event in events),
                slots_empty=row.slots_empty if permissions.tournament_read else None,
                now=now,
            )
            built.append((key, card, events, card_issues))
        built.sort(key=lambda item: item[0])

        issues: list[schemas.DashboardIssue] = []
        timeline: list[schemas.DashboardTimelineEvent] = []
        for _key, _card, events, card_issues in built:
            timeline.extend(events)
            issues.extend(card_issues)
        issues.sort(key=lambda issue: _SEVERITY_RANK[issue.severity])
        timeline.sort(key=lambda event: event.at)

        cards = [card for _key, card, _events, _issues in built]
        return schemas.AdminDashboard(
            generated_at=now,
            tournaments=cards,
            timeline=timeline if permissions.tournament_read else None,
            issues=issues,
            backlog=await self._backlog(
                session,
                workspace_id,
                permissions,
                card_ids=[card.id for card in cards],
                users_without_identities=await self._users_without_identities(session, workspace_id)
                if permissions.user_read
                else None,
            ),
        )

    async def _candidates(
        self, session: AsyncSession, workspace_id: int, permissions: DashboardPermissions, now: datetime
    ) -> list[sa.Row]:
        """Card candidates with their per-tournament extras and the granted readiness counts; wrap-up ``done``
        is decided by the caller."""
        tournament = models.Tournament
        encounter = models.Encounter
        last_confirmed = (
            sa.select(sa.func.max(encounter.confirmed_at)).where(encounter.tournament_id == tournament.id)
        ).scalar_subquery()
        finished_at = sa.func.coalesce(tournament.end_date, last_confirmed)

        registration = models.Registration
        registrations_last_24h = sa.select(sa.func.count(registration.id)).where(
            registration.tournament_id == tournament.id,
            registration.deleted_at.is_(None),
            registration.submitted_at >= now - timedelta(hours=24),
        )
        # The frontend's ``hasChallongeSource``: a tournament slug, or a stage slug -- the stage-scoped
        # source keeps its ``stage_id`` (``shared.services.challonge_refs``).
        source = models.ChallongeSource
        has_challonge_source = sa.exists().where(
            source.tournament_id == tournament.id,
            source.slug.is_not(None),
            source.slug != "",
            sa.or_(
                source.source_type == "tournament",
                sa.and_(source.source_type == "stage", source.stage_id.is_not(None)),
            ),
        )

        result = await session.execute(
            sa.select(
                tournament,
                finished_at.label("finished_at"),
                registrations_last_24h.scalar_subquery().label("registrations_last_24h"),
                has_challonge_source.label("has_challonge_source"),
                latest_evaluation_run_status(tournament.id).label("run_status"),
                has_enabled_achievement_rules(tournament.workspace_id, tournament.discipline).label(
                    "has_achievement_rules"
                ),
                standings_recalc_pending(tournament.id).label("recalc_pending"),
                *(setup_counts(tournament.id) if permissions.tournament_read else ()),
                *(team_counts(tournament.id) if permissions.team_read else ()),
            ).where(
                tournament.workspace_id == workspace_id,
                sa.or_(
                    tournament.status.not_in(tuple(FINISHED_STATUSES)),
                    sa.and_(tournament.status == _TS.COMPLETED, finished_at >= now - WRAP_UP_WINDOW),
                ),
            )
        )
        return list(result.all())

    async def _encounter_counts(
        self, session: AsyncSession, tournament_ids: list[int], now: datetime
    ) -> dict[int, Counter]:
        if not tournament_ids:
            return {}
        encounter = models.Encounter
        count = sa.func.count(encounter.id)
        duel = encounter.slot_count == 2
        has_logs = encounter.has_logs.is_(True)
        rows = await session.execute(
            sa.select(
                encounter.tournament_id,
                count.label("total"),
                count.filter(encounter.status == enums.EncounterStatus.COMPLETED).label("completed"),
                count.filter(_live_condition(now)).label("live"),
                count.filter(
                    encounter.result_status == enums.EncounterResultStatus.NONE,
                    encounter.scheduled_at < now,
                    encounter.status != enums.EncounterStatus.COMPLETED,
                ).label("overdue"),
                count.filter(encounter.result_status == enums.EncounterResultStatus.PENDING_CONFIRMATION).label(
                    "pending_confirmation"
                ),
                count.filter(encounter.result_status == enums.EncounterResultStatus.DISPUTED).label("disputed"),
                count.filter(has_logs).label("with_logs"),
                # A lobby never produces a match log: only duels count toward log coverage.
                count.filter(duel).label("duels"),
                count.filter(duel, has_logs).label("duels_with_logs"),
            )
            .where(encounter.tournament_id.in_(tournament_ids))
            .group_by(encounter.tournament_id)
        )
        return {row.tournament_id: Counter(row._asdict()) for row in rows}

    async def _backlog(
        self,
        session: AsyncSession,
        workspace_id: int,
        permissions: DashboardPermissions,
        *,
        card_ids: list[int],
        users_without_identities: int | None,
    ) -> schemas.DashboardBacklog:
        """Workspace tournaments without a card that have a visible data-quality issue (counts ``NULL`` when
        masked): the newest ``BACKLOG_ROWS`` of them, with the totals over all of them as window aggregates."""
        tournament = models.Tournament
        encounter = models.Encounter
        team = models.Team
        stage = models.Stage
        slot = models.StageItemInput

        # Duels only: a lobby produces no match logs at all, so "missing logs" never applies to it.
        missing_logs = sa.select(sa.func.count(encounter.id)).where(
            encounter.tournament_id == tournament.id, encounter.slot_count == 2, encounter.has_logs.is_(False)
        )
        teams_without_players = sa.select(sa.func.count(team.id)).where(
            team.tournament_id == tournament.id, ~sa.exists().where(models.Player.team_id == team.id)
        )
        # Bracket slots never wired to a team/winner source.
        stage_slots_empty = (
            sa.select(sa.func.count(slot.id))
            .join(models.StageItem, models.StageItem.id == slot.stage_item_id)
            .join(stage, stage.id == models.StageItem.stage_id)
            .where(stage.tournament_id == tournament.id, slot.input_type == enums.StageItemInputType.EMPTY)
        )
        has_stages = sa.exists().where(stage.tournament_id == tournament.id)

        def gated(granted: bool, column: Any, type_: Any) -> Any:
            # Typed: an untyped NULL leaves the subquery column ``text``, which the ``> 0`` below cannot compare.
            return column if granted else sa.cast(sa.null(), type_)

        scan = (
            sa.select(
                tournament.id,
                tournament.name,
                tournament.discipline,
                tournament.start_date,
                gated(permissions.match_read, missing_logs.scalar_subquery(), sa.BigInteger).label("missing_logs"),
                gated(permissions.team_read, teams_without_players.scalar_subquery(), sa.BigInteger).label(
                    "teams_without_players"
                ),
                gated(permissions.tournament_read, stage_slots_empty.scalar_subquery(), sa.BigInteger).label(
                    "stage_slots_empty"
                ),
                gated(permissions.tournament_read, has_stages, sa.Boolean).label("has_stages"),
            )
            .where(tournament.workspace_id == workspace_id, tournament.id.not_in(card_ids))
            .subquery("scan")
        )
        rows = (
            await session.execute(
                sa.select(
                    scan,
                    sa.func.count().over().label("tournaments_total"),
                    sa.func.sum(scan.c.missing_logs).over().label("missing_logs_total"),
                    sa.func.sum(scan.c.teams_without_players).over().label("teams_without_players_total"),
                    sa.func.count().filter(scan.c.has_stages.is_(False)).over().label("without_stages_total"),
                    sa.func.sum(scan.c.stage_slots_empty).over().label("stage_slots_empty_total"),
                )
                .where(
                    sa.or_(
                        scan.c.missing_logs > 0,
                        scan.c.teams_without_players > 0,
                        scan.c.stage_slots_empty > 0,
                        scan.c.has_stages.is_(False),
                    )
                )
                .order_by(scan.c.start_date.desc().nulls_last(), scan.c.id.desc())
                .limit(BACKLOG_ROWS)
            )
        ).all()
        # The window runs before the LIMIT: every row carries the totals over all matches; no row, nothing to total.
        totals = rows[0] if rows else None

        def total(column: str, granted: bool) -> int | None:
            if not granted:
                return None
            return int(getattr(totals, column)) if totals is not None else 0

        return schemas.DashboardBacklog(
            rows=[
                schemas.DashboardBacklogRow(
                    tournament_id=row.id,
                    tournament_name=row.name,
                    discipline=row.discipline,
                    encounters_missing_logs=row.missing_logs,
                    teams_without_players=row.teams_without_players,
                    stage_slots_empty=row.stage_slots_empty,
                    has_stages=row.has_stages,
                )
                for row in rows
            ],
            tournaments_total=total("tournaments_total", True),
            encounters_missing_logs=total("missing_logs_total", permissions.match_read),
            teams_without_players=total("teams_without_players_total", permissions.team_read),
            tournaments_without_stages=total("without_stages_total", permissions.tournament_read),
            stage_slots_empty=total("stage_slots_empty_total", permissions.tournament_read),
            users_without_identities=users_without_identities,
        )

    @staticmethod
    async def _users_without_identities(session: AsyncSession, workspace_id: int) -> int:
        """Roster players with no social account. Identities are platform-wide, so the workspace is reached
        through ``workspace_member`` -- the hop the Player-identities list uses (``services.admin.user``)."""
        user = models.User
        return (
            await session.scalar(
                sa.select(sa.func.count(user.id)).where(
                    ~sa.exists().where(models.SocialAccount.user_id == user.id),
                    sa.exists().where(
                        models.WorkspaceMember.player_id == user.id, models.WorkspaceMember.workspace_id == workspace_id
                    ),
                )
            )
            or 0
        )


overview = AdminDashboardService()

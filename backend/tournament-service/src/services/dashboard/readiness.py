"""Tournament readiness aggregate for the hub living checklist.

One round trip of count/exists scalar subqueries over the shared models on top
of the tournament fetch. Field groups are masked by the caller's workspace
permissions: ``tournament.read`` gates setup/bracket/logs/recalc fields,
``team.read`` gates registration/pool/balance/draft fields, ``match.read`` gates
the result backlog and ``achievement.read`` the evaluation status — a missing
group yields ``None`` so the checklist renders "no-access" instead of zeros. A
masked group's subqueries are not selected at all.

``registrations_ranked`` counts SAVED rank data on registration roles
(``RegistrationRole.rank_value``), never an autofill preview.

The module-level builders take a column or a literal: the dashboard correlates
them on ``Tournament``, the checklist binds one tournament. Both assemble the
result with :func:`build_readiness` — the dashboard from the rows it already
fetched for its cards, so a card costs no statement of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.draft import DraftSession
from shared.repository import TournamentRepository
from src.schemas import TournamentReadiness

__all__ = (
    "ReadinessService",
    "build_readiness",
    "has_enabled_achievement_rules",
    "latest_evaluation_run_status",
    "readiness",
    "setup_counts",
    "standings_recalc_pending",
    "team_counts",
)


def latest_evaluation_run_status(tournament_id: sa.SQLColumnExpression[int] | int) -> sa.ScalarSelect[Any]:
    """Status of the tournament's newest achievement evaluation run; ``NULL`` when it never ran."""
    run = models.EvaluationRun
    return (
        sa.select(run.status)
        .where(run.tournament_id == tournament_id)
        .order_by(run.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )


def has_enabled_achievement_rules(
    workspace_id: sa.SQLColumnExpression[int] | int, discipline: sa.SQLColumnExpression[str] | str
) -> sa.Exists:
    """The engine evaluates one game's enabled rules at a time, so "nothing to evaluate" is per discipline."""
    rule = models.AchievementRule
    return sa.exists().where(rule.workspace_id == workspace_id, rule.discipline == discipline, rule.enabled.is_(True))


def standings_recalc_pending(tournament_id: sa.SQLColumnExpression[int] | int) -> sa.Exists:
    """A standings recalculation was requested and has not completed yet."""
    state = models.TournamentRecalculationState
    return sa.exists().where(
        state.tournament_id == tournament_id, state.requested_generation > state.completed_generation
    )


def setup_counts(tournament_id: sa.SQLColumnExpression[int] | int) -> list[sa.Label[Any]]:
    """Stage, bracket-slot and bracketed-encounter counts: the part of the ``tournament.read`` group that
    neither the tournament row nor the encounter counts answer."""
    stage = models.Stage
    slot = models.StageItemInput
    stages_total = sa.select(sa.func.count(stage.id)).where(stage.tournament_id == tournament_id)
    slots_total = (
        sa.select(sa.func.count(slot.id))
        .join(models.StageItem, models.StageItem.id == slot.stage_item_id)
        .join(stage, stage.id == models.StageItem.stage_id)
        .where(stage.tournament_id == tournament_id)
    )
    slots_empty = slots_total.where(slot.input_type == enums.StageItemInputType.EMPTY)
    encounters_bracket = (
        sa.select(sa.func.count(models.Encounter.id))
        .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
        .where(models.Encounter.tournament_id == tournament_id, models.BracketEncounter.stage_id.is_not(None))
    )
    return [
        stages_total.scalar_subquery().label("stages_total"),
        slots_total.scalar_subquery().label("slots_total"),
        slots_empty.scalar_subquery().label("slots_empty"),
        encounters_bracket.scalar_subquery().label("bracket_encounters"),
    ]


def team_counts(tournament_id: sa.SQLColumnExpression[int] | int) -> list[sa.Label[Any]]:
    """Registration/pool/balance/draft state — the ``team.read`` group.

    Form row exists, saved balance and latest draft status are scalar
    subqueries like the counters.
    """
    reg = models.Registration
    active = (reg.tournament_id == tournament_id, reg.deleted_at.is_(None))
    reg_pending = sa.select(sa.func.count(reg.id)).where(*active, reg.status == "pending")
    reg_approved = sa.select(sa.func.count(reg.id)).where(*active, reg.status == "approved")
    reg_checked_in = sa.select(sa.func.count(reg.id)).where(*active, reg.checked_in.is_(True))
    # Saved rank data only: >=1 role row with a stored rank_value. A join, not ``IN (subquery)``: SQLAlchemy
    # correlates a subquery with its immediately enclosing SELECT only, and the dashboard correlates on ``Tournament``.
    role = models.RegistrationRole
    reg_ranked = (
        sa.select(sa.func.count(sa.distinct(role.registration_id)))
        .join(reg, reg.id == role.registration_id)
        .where(*active, role.rank_value.is_not(None))
    )
    pool_ready = sa.select(sa.func.count(reg.id)).where(*active, reg.balancer_status == "ready")
    pool_need_fix = sa.select(sa.func.count(reg.id)).where(*active, reg.balancer_status == "incomplete")
    # "A form row exists", not "registration is open": openness is the phase
    # schedule's window, and a tournament whose window merely ENDED still has
    # its form configured.
    form_configured = (
        sa.select(sa.literal(1))
        .select_from(models.RegistrationForm)
        .where(models.RegistrationForm.tournament_id == tournament_id)
        .limit(1)
    )
    # Existence and value are separate probes: ``exported_at`` is nullable, so
    # a single scalar subquery could not tell "no balance saved" apart from
    # "saved but never exported".
    balance_id = (
        sa.select(models.BalancerBalance.id).where(models.BalancerBalance.tournament_id == tournament_id).limit(1)
    )
    balance_exported_at = (
        sa.select(models.BalancerBalance.exported_at)
        .where(models.BalancerBalance.tournament_id == tournament_id)
        .limit(1)
    )
    draft_status = (
        sa.select(DraftSession.status)
        .where(DraftSession.tournament_id == tournament_id)
        .order_by(DraftSession.created_at.desc())
        .limit(1)
    )
    return [
        reg_pending.scalar_subquery().label("registrations_pending"),
        reg_approved.scalar_subquery().label("registrations_approved"),
        reg_checked_in.scalar_subquery().label("registrations_checked_in"),
        reg_ranked.scalar_subquery().label("registrations_ranked"),
        pool_ready.scalar_subquery().label("pool_ready"),
        pool_need_fix.scalar_subquery().label("pool_need_fix"),
        form_configured.scalar_subquery().label("form_configured"),
        balance_id.scalar_subquery().label("balance_id"),
        balance_exported_at.scalar_subquery().label("balance_exported_at"),
        draft_status.scalar_subquery().label("draft_session_status"),
    ]


def build_readiness(
    tournament: models.Tournament,
    values: Mapping[str, Any],
    *,
    can_tournament_read: bool,
    can_team_read: bool,
    can_match_read: bool,
    can_achievement_read: bool,
) -> TournamentReadiness:
    """The masked checklist. ``values`` carries, for the granted groups, the labels of :func:`setup_counts`
    and :func:`team_counts` plus the dashboard's names for the rest: ``duels``, ``duels_with_logs``,
    ``recalc_pending``, ``overdue``, ``pending_confirmation``, ``disputed``, ``has_achievement_rules`` and
    ``run_status``. A missing count reads as zero (a tournament without encounters has no count row)."""

    def count(key: str) -> int:
        return values.get(key) or 0

    # Every field starts masked; each granted group fills its own.
    fields: dict[str, Any] = dict.fromkeys(TournamentReadiness.model_fields)
    fields.update(
        tournament_id=tournament.id,
        status=tournament.status.value,
        team_formation=tournament.team_formation,
    )

    if can_tournament_read:
        duels_with_logs = count("duels_with_logs")
        fields.update(
            # The schedule is loaded with every tournament (``lazy="selectin"``).
            schedule_configured=bool(tournament.phase_schedule),
            grid_selected=tournament.division_grid_version_id is not None,
            stages_total=count("stages_total"),
            stage_slots_filled=count("slots_total") > 0 and count("slots_empty") == 0,
            bracket_generated=count("bracket_encounters") > 0,
            duel_encounters_total=count("duels"),
            duel_encounters_with_logs=duels_with_logs,
            logs_used=duels_with_logs > 0,
            standings_recalc_pending=bool(values.get("recalc_pending")),
        )

    if can_team_read:
        exported_at = values.get("balance_exported_at")
        fields.update(
            registration_form_configured=values.get("form_configured") is not None,
            registrations_pending=count("registrations_pending"),
            registrations_approved=count("registrations_approved"),
            registrations_checked_in=count("registrations_checked_in"),
            registrations_ranked=count("registrations_ranked"),
            pool_ready=count("pool_ready"),
            pool_need_fix=count("pool_need_fix"),
            balance_saved=values.get("balance_id") is not None,
            balance_exported_at=exported_at.isoformat() if exported_at is not None else None,
            draft_session_status=values.get("draft_session_status"),
        )

    if can_match_read:
        fields.update(
            results_overdue=count("overdue"),
            results_pending_confirmation=count("pending_confirmation"),
            results_disputed=count("disputed"),
        )
    if can_achievement_read:
        fields["achievements_status"] = (
            (values.get("run_status") or "none") if values.get("has_achievement_rules") else "not_configured"
        )

    return TournamentReadiness(**fields)


class ReadinessService:
    """The tournament-readiness checklist: one select of the granted groups'
    scalar subqueries, assembled by :func:`build_readiness`."""

    def __init__(self, *, tournaments: TournamentRepository = TournamentRepository()) -> None:
        self.tournaments = tournaments

    async def get_tournament_or_404(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        tournament = await self.tournaments.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        return tournament

    async def compute_readiness(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        can_tournament_read: bool = True,
        can_team_read: bool = True,
        can_match_read: bool = True,
        can_achievement_read: bool = True,
    ) -> TournamentReadiness:
        tournament = await self.get_tournament_or_404(session, tournament_id)
        encounter = models.Encounter

        def encounters(*where: sa.ColumnElement[bool]) -> sa.ScalarSelect[Any]:
            return (
                sa.select(sa.func.count(encounter.id))
                .where(encounter.tournament_id == tournament_id, *where)
                .scalar_subquery()
            )

        columns: list[Any] = []
        if can_tournament_read:
            # A lobby never produces a match log: only duels count toward log coverage.
            duel = encounter.slot_count == 2
            columns += [
                *setup_counts(tournament_id),
                encounters(duel).label("duels"),
                encounters(duel, encounter.has_logs.is_(True)).label("duels_with_logs"),
                standings_recalc_pending(tournament_id).label("recalc_pending"),
            ]
        if can_team_read:
            columns += team_counts(tournament_id)
        if can_match_read:
            columns += [
                # The dashboard's "overdue": no result for a past slot of an unfinished match.
                encounters(
                    encounter.result_status == enums.EncounterResultStatus.NONE,
                    encounter.scheduled_at < datetime.now(UTC),
                    encounter.status != enums.EncounterStatus.COMPLETED,
                ).label("overdue"),
                encounters(encounter.result_status == enums.EncounterResultStatus.PENDING_CONFIRMATION).label(
                    "pending_confirmation"
                ),
                encounters(encounter.result_status == enums.EncounterResultStatus.DISPUTED).label("disputed"),
            ]
        if can_achievement_read:
            columns += [
                has_enabled_achievement_rules(tournament.workspace_id, tournament.discipline).label(
                    "has_achievement_rules"
                ),
                latest_evaluation_run_status(tournament.id).label("run_status"),
            ]

        values = (await session.execute(sa.select(*columns))).one()._mapping if columns else {}
        return build_readiness(
            tournament,
            values,
            can_tournament_read=can_tournament_read,
            can_team_read=can_team_read,
            can_match_read=can_match_read,
            can_achievement_read=can_achievement_read,
        )


readiness = ReadinessService()

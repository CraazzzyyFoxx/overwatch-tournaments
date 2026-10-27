"""The organizer dashboard (real-DB integration): card set and phases, the wrap-up window and its ``done``
rule, the timeline's overdue rule, issue severities, backlog invariants, card readiness against the checklist,
the statement budget and permission masking::

    uv run pytest tournament-service/tests/test_admin_dashboard.py -v

Each test seeds its own workspace through the shared ``db_session`` fixture and drops it again (the workspace
cascade takes tournaments, encounters, rules and runs with it). Skips only when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event as sa_event

from shared.core import enums
from shared.models.achievements import AchievementRule, EvaluationRun
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.identity.social import SocialAccount
from shared.models.identity.user import User
from shared.models.registration.registration import Registration, RegistrationForm, RegistrationRole
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament import (
    BracketEncounter,
    Stage,
    StageItem,
    StageItemInput,
    Team,
    Tournament,
    TournamentPhaseSchedule,
    TournamentRecalculationState,
)
from src.schemas import AdminDashboard
from src.services.dashboard.overview import DashboardPermissions, overview
from src.services.dashboard.readiness import readiness
from tests.encounter_seed import seed_encounter, seed_scoring_rule

TS = enums.TournamentStatus
TOPIC = "rpc.tournament.admin_dashboard"
TRENDS_TOPIC = "rpc.tournament.admin_dashboard_trends"
EVERYTHING = DashboardPermissions(True, True, True, True, True)
SUPERUSER = {"user_id": 1, "is_superuser": True, "is_active": True}

Seed = Callable[[Any, int, datetime], Awaitable[dict[str, Any]]]


async def _workspace(session: Any) -> int:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"dash-{suffix}", name=f"Dashboard {suffix}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _tournament(
    session: Any,
    workspace_id: int,
    status: enums.TournamentStatus,
    *,
    schedule: tuple[tuple[enums.TournamentStatus, datetime, datetime | None], ...] = (),
    **columns: Any,
) -> Tournament:
    suffix = uuid.uuid4().hex[:12]
    tournament = Tournament(
        workspace_id=workspace_id, name=f"{status.value} {suffix}", slug=f"dash-{suffix}", status=status, **columns
    )
    session.add(tournament)
    await session.flush()
    session.add_all(
        TournamentPhaseSchedule(tournament_id=tournament.id, status=phase, starts_at=starts_at, ends_at=ends_at)
        for phase, starts_at, ends_at in schedule
    )
    await session.flush()
    return tournament


async def _duel(session: Any, tournament: Tournament, rule_id: int, **kwargs: Any) -> Any:
    return await seed_encounter(session, tournament, rule_id, [(None, 0), (None, 0)], name="A vs B", **kwargs)


async def _drop(session: Any, workspace_id: int, user_ids: list[int]) -> None:
    await session.rollback()
    # Workspace first: its member rows anchor the players.
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.execute(sa.delete(User).where(User.id.in_(user_ids)))
    await session.commit()


def _run(db_session: Any, seed: Seed) -> tuple[AdminDashboard, dict[str, Any], datetime]:
    """Seed a fresh workspace, read its dashboard with every permission, drop it."""
    now = datetime.now(UTC)

    async def go() -> tuple[AdminDashboard, dict[str, Any]]:
        workspace_id = await _workspace(db_session)
        ctx: dict[str, Any] = {}
        try:
            ctx = await seed(db_session, workspace_id, now)
            await db_session.commit()
            # Fresh loads: the seeded tournaments' schedules were added beside them, not through them.
            db_session.expunge_all()
            dashboard = await overview.get_dashboard(
                db_session, workspace_id=workspace_id, permissions=EVERYTHING, now=now
            )
            return dashboard, ctx
        finally:
            await _drop(db_session, workspace_id, ctx.get("users", []))

    dashboard, ctx = asyncio.run(go())
    return dashboard, ctx, now


def _issues(dashboard: AdminDashboard, tournament_id: int) -> list[tuple[str, str, int | None]]:
    return [(i.key, i.severity, i.count) for i in dashboard.issues if i.tournament_id == tournament_id]


def _identity(workspace_id: int, perms: list[dict[str, str]]) -> dict:
    return {
        "user_id": 424242,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [{"workspace_id": workspace_id, "rbac_roles": [], "rbac_permissions": perms}],
    }


# --- card set ----------------------------------------------------------------


def test_every_unfinished_tournament_is_a_card_in_its_phase(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        ids = {}
        for status, hidden in (
            (TS.ANNOUNCEMENT, False),
            (TS.REGISTRATION, False),
            (TS.CHECK_IN, False),
            (TS.DRAFT, False),
            (TS.LIVE, False),
            (TS.PLAYOFFS, True),
            (TS.ARCHIVED, False),
        ):
            ids[status] = (await _tournament(session, workspace_id, status, is_hidden=hidden)).id
        # Finished a month ago: long past its wrap-up window.
        ids["old"] = (await _tournament(session, workspace_id, TS.COMPLETED, end_date=now - timedelta(days=30))).id
        return ids

    dashboard, ids, _now = _run(db_session, seed)

    assert {card.id: card.phase for card in dashboard.tournaments} == {
        ids[TS.ANNOUNCEMENT]: "preparation",
        ids[TS.REGISTRATION]: "registration",
        ids[TS.CHECK_IN]: "formation",
        ids[TS.DRAFT]: "formation",
        ids[TS.LIVE]: "live",
        ids[TS.PLAYOFFS]: "live",
    }
    # Hidden tournaments keep their card; the live phase leads, newest first on a tie.
    assert [(card.id, card.is_hidden) for card in dashboard.tournaments[:2]] == [
        (ids[TS.PLAYOFFS], True),
        (ids[TS.LIVE], False),
    ]


def test_a_completed_tournament_is_a_wrap_up_card_for_14_days(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        rule_id = await seed_scoring_rule(session, workspace_id)
        ids: dict[str, Any] = {}
        for label, days in (("recent", 13), ("stale", 15)):
            tournament = await _tournament(session, workspace_id, TS.COMPLETED, end_date=now - timedelta(days=days))
            encounter = await _duel(session, tournament, rule_id, completed=False)
            encounter.result_status = enums.EncounterResultStatus.PENDING_CONFIRMATION
            ids[label] = tournament.id
        await session.flush()
        return ids

    dashboard, ids, now = _run(db_session, seed)

    (card,) = dashboard.tournaments
    assert card.id == ids["recent"]
    assert card.phase == "wrap_up"
    assert card.finished_at == now - timedelta(days=13)
    assert card.wrap_up is not None and card.wrap_up.done is False and card.wrap_up.results_open == 1
    assert _issues(dashboard, ids["recent"]) == [("results_pending_confirmation", "critical", 1)]
    # Past the window it drops to the backlog whatever is still open.
    assert ids["stale"] in [row.tournament_id for row in dashboard.backlog.rows]
    assert _issues(dashboard, ids["stale"]) == []


def test_a_done_wrap_up_drops_the_card(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        rule_id = await seed_scoring_rule(session, workspace_id)
        ids = {}
        for label in ("done", "recalc"):
            tournament = await _tournament(session, workspace_id, TS.COMPLETED, end_date=now - timedelta(days=2))
            await _duel(session, tournament, rule_id)
            # A lobby: never a duel, so never an encounter missing its logs.
            await seed_encounter(session, tournament, rule_id, [(None, 0), (None, 0), (None, 0)], name="Lobby")
            ids[label] = tournament.id
        session.add(
            TournamentRecalculationState(tournament_id=ids["recalc"], requested_generation=2, completed_generation=1)
        )
        await session.flush()
        return ids

    dashboard, ids, _now = _run(db_session, seed)

    (card,) = dashboard.tournaments
    assert card.id == ids["recalc"]
    assert card.wrap_up is not None
    assert card.wrap_up.done is False
    assert card.wrap_up.standings_recalc_pending is True
    assert card.wrap_up.results_open == 0
    # Nothing logged at all: the tournament does not use logs, so coverage does not hold it open.
    assert card.wrap_up.logs_used is False
    assert card.wrap_up.duel_encounters_total == 1
    assert card.wrap_up.achievements_status == "not_configured"
    assert _issues(dashboard, ids["recalc"]) == [("standings_recalc_pending", "warning", None)]
    (done_row,) = [row for row in dashboard.backlog.rows if row.tournament_id == ids["done"]]
    assert done_row.encounters_missing_logs == 1


def test_enabled_achievement_rules_hold_wrap_up_open_until_evaluated(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        session.add(
            AchievementRule(
                workspace_id=workspace_id,
                slug=f"dash-{uuid.uuid4().hex[:8]}",
                name="Rule",
                description_ru="ru",
                description_en="en",
                discipline="overwatch",
                category="overall",
                scope="global",
                grain="user",
                condition_tree={},
                depends_on=[],
                enabled=True,
                rule_version=1,
            )
        )
        evaluated = await _tournament(session, workspace_id, TS.COMPLETED, end_date=now - timedelta(days=1))
        pending = await _tournament(session, workspace_id, TS.COMPLETED, end_date=now - timedelta(days=1))
        session.add(
            EvaluationRun(workspace_id=workspace_id, trigger="manual", tournament_id=evaluated.id, status="done")
        )
        await session.flush()
        return {"evaluated": evaluated.id, "pending": pending.id}

    dashboard, ids, _now = _run(db_session, seed)

    (card,) = dashboard.tournaments
    assert card.id == ids["pending"]
    assert card.wrap_up is not None and card.wrap_up.achievements_status == "none"
    assert _issues(dashboard, ids["pending"]) == [("achievements_pending", "warning", None)]


# --- timeline + issues ---------------------------------------------------------


def test_a_phase_start_is_overdue_only_past_the_grace_and_ahead_of_the_status(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        behind = await _tournament(
            session,
            workspace_id,
            TS.REGISTRATION,
            schedule=(
                (TS.REGISTRATION, now - timedelta(days=3), now + timedelta(hours=1)),
                (TS.CHECK_IN, now - timedelta(minutes=30), None),
                # Inside the grace: the worker tick may simply not have run yet.
                (TS.DRAFT, now - timedelta(minutes=5), None),
                (TS.LIVE, now + timedelta(days=2), None),
            ),
        )
        # Its check-in start passed, but the status already reached it.
        on_time = await _tournament(
            session, workspace_id, TS.CHECK_IN, schedule=((TS.CHECK_IN, now - timedelta(minutes=30), None),)
        )
        return {"behind": behind.id, "on_time": on_time.id}

    dashboard, ids, now = _run(db_session, seed)

    assert dashboard.timeline is not None
    assert [(e.tournament_id, e.status, e.edge, e.at, e.overdue) for e in dashboard.timeline] == [
        (ids["behind"], "check_in", "start", now - timedelta(minutes=30), True),
        (ids["behind"], "registration", "end", now + timedelta(hours=1), False),
        (ids["behind"], "live", "start", now + timedelta(days=2), False),
    ]
    assert ("phase_overdue", "critical", None) in _issues(dashboard, ids["behind"])
    assert _issues(dashboard, ids["on_time"]) == []
    behind = next(card for card in dashboard.tournaments if card.id == ids["behind"])
    assert behind.next_deadline_at == now + timedelta(hours=1)
    assert behind.registration_closes_at == now + timedelta(hours=1)


def test_pending_registrations_turn_critical_inside_24h_of_closing(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        ids = {}
        for label, closes_in in (("calm", timedelta(days=3)), ("urgent", timedelta(hours=2)), ("unscheduled", None)):
            schedule = ((TS.REGISTRATION, now - timedelta(days=1), now + closes_in),) if closes_in else ()
            tournament = await _tournament(session, workspace_id, TS.REGISTRATION, schedule=schedule)
            session.add(Registration(tournament_id=tournament.id, display_name="p", status="pending"))
            ids[label] = tournament.id
        await session.flush()
        return ids

    dashboard, ids, _now = _run(db_session, seed)

    assert [(i.tournament_id, i.key, i.severity, i.count) for i in dashboard.issues] == [
        (ids["urgent"], "registrations_pending", "critical", 1),
        (ids["calm"], "registrations_pending", "warning", 1),
        (ids["unscheduled"], "registrations_pending", "warning", 1),
    ]
    assert all(card.registrations_last_24h == 1 for card in dashboard.tournaments)


# --- backlog -------------------------------------------------------------------


def test_users_without_identities_count_only_the_workspace_roster(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        suffix = uuid.uuid4().hex[:12]
        # The third has no identity either, but is no member of this workspace.
        users = [User(name=f"dash-{suffix}-{i}") for i in range(3)]
        linked, unlinked = users[:2]
        session.add_all(users)
        await session.flush()
        session.add_all(WorkspaceMember(workspace_id=workspace_id, player_id=user.id) for user in (linked, unlinked))
        session.add(SocialAccount(user_id=linked.id, provider="discord", username=f"dash-{suffix}"))
        await session.flush()
        return {"users": [user.id for user in users]}

    dashboard, _ctx, _now = _run(db_session, seed)

    assert dashboard.backlog.users_without_identities == 1


def test_backlog_totals_count_every_row_past_the_twenty_shown(db_session) -> None:
    async def seed(session: Any, workspace_id: int, now: datetime) -> dict[str, Any]:
        rule_id = await seed_scoring_rule(session, workspace_id)
        archived = []
        for days in range(25):
            tournament = await _tournament(session, workspace_id, TS.ARCHIVED, start_date=now - timedelta(days=days))
            session.add(Team(tournament_id=tournament.id, name="Empty", balancer_name="empty"))
            archived.append(tournament)
        # Every extra lands on a tournament past the 20 rows shown: only the totals can see it.
        session.add(Team(tournament_id=archived[-1].id, name="Empty too", balancer_name="empty too"))
        await _duel(session, archived[-2], rule_id)
        stage = Stage(
            tournament_id=archived[-3].id,
            name="Groups",
            stage_type=enums.StageType.ROUND_ROBIN,
            scoring_rule_id=rule_id,
        )
        session.add(stage)
        await session.flush()
        item = StageItem(stage_id=stage.id, name="Bracket", type=enums.StageItemType.GROUP)
        session.add(item)
        await session.flush()
        session.add_all(StageItemInput(stage_item_id=item.id, slot=slot) for slot in (1, 2, 3))
        # A card: its issues are the work queue's, never the backlog's.
        card = await _tournament(session, workspace_id, TS.REGISTRATION)
        session.add(Team(tournament_id=card.id, name="Card", balancer_name="card"))
        await session.flush()
        return {"archived": [tournament.id for tournament in archived]}

    dashboard, ids, _now = _run(db_session, seed)

    backlog = dashboard.backlog
    assert [row.tournament_id for row in backlog.rows] == ids["archived"][:20]
    assert (
        backlog.tournaments_total,
        backlog.teams_without_players,
        backlog.encounters_missing_logs,
        backlog.stage_slots_empty,
        backlog.tournaments_without_stages,
    ) == (25, 26, 1, 3, 24)


# --- card readiness + statement budget ----------------------------------------------


def test_card_readiness_is_the_checklist_of_its_tournament(db_session) -> None:
    """A card's readiness is assembled from the dashboard's own rows; it must still be exactly the checklist of its
    tournament under the same grants. Two cards with different data: a subquery correlated on the wrong tournament
    shows up as one card carrying the other's counts."""
    now = datetime.now(UTC)
    grants = (
        EVERYTHING,
        DashboardPermissions(False, True, False, False, False),
        DashboardPermissions(True, False, True, False, True),
    )

    async def go() -> tuple[list[tuple[Any, Any]], dict[str, int]]:
        workspace_id = await _workspace(db_session)
        try:
            rule_id = await seed_scoring_rule(db_session, workspace_id)
            registration = await _tournament(
                db_session,
                workspace_id,
                TS.REGISTRATION,
                schedule=((TS.REGISTRATION, now - timedelta(days=1), now + timedelta(days=3)),),
            )
            live = await _tournament(db_session, workspace_id, TS.LIVE)
            team = Team(tournament_id=live.id, name="Seeded", balancer_name="seeded")
            db_session.add(team)
            db_session.add(RegistrationForm(tournament_id=registration.id, workspace_id=workspace_id, is_open=True))
            regs = [
                Registration(
                    tournament_id=registration.id,
                    display_name="a",
                    status="approved",
                    checked_in=True,
                    balancer_status="ready",
                ),
                Registration(
                    tournament_id=registration.id, display_name="b", status="approved", balancer_status="incomplete"
                ),
                Registration(tournament_id=registration.id, display_name="c", status="pending"),
                Registration(tournament_id=live.id, display_name="d", status="approved", checked_in=True),
            ]
            db_session.add_all(regs)
            await db_session.flush()
            roles = {
                role.code: role
                for role in await db_session.scalars(
                    sa.select(CatalogRole)
                    .join(RoleDimension, RoleDimension.id == CatalogRole.dimension_id)
                    .where(
                        RoleDimension.discipline == registration.discipline,
                        RoleDimension.rated.is_(True),
                        CatalogRole.workspace_id.is_(None),
                    )
                )
            }
            for reg, code in ((regs[0], "tank"), (regs[2], "support"), (regs[3], "damage")):
                db_session.add(
                    RegistrationRole(
                        registration_id=reg.id,
                        catalog_role=roles[code],
                        dimension_id=roles[code].dimension_id,
                        is_primary=True,
                        rank_value=2000,
                    )
                )
            # One single-slot bracket each: unwired on the registration card, filled on the live one.
            stage_ids = {}
            for tournament, input_type, team_id in (
                (registration, enums.StageItemInputType.EMPTY, None),
                (live, enums.StageItemInputType.FINAL, team.id),
            ):
                stage = Stage(
                    tournament_id=tournament.id,
                    name="Bracket",
                    stage_type=enums.StageType.SINGLE_ELIMINATION,
                    scoring_rule_id=rule_id,
                )
                db_session.add(stage)
                await db_session.flush()
                item = StageItem(stage_id=stage.id, name="Bracket", type=enums.StageItemType.SINGLE_BRACKET)
                db_session.add(item)
                await db_session.flush()
                db_session.add(StageItemInput(stage_item_id=item.id, slot=1, input_type=input_type, team_id=team_id))
                stage_ids[tournament.id] = stage.id
            placed = await _duel(db_session, live, rule_id, round_=None)
            db_session.add(
                BracketEncounter(encounter_id=placed.id, tournament_id=live.id, stage_id=stage_ids[live.id], round=1)
            )
            await _duel(db_session, live, rule_id, completed=False, scheduled_at=now - timedelta(hours=1))
            for status in (enums.EncounterResultStatus.PENDING_CONFIRMATION, enums.EncounterResultStatus.DISPUTED):
                (await _duel(db_session, live, rule_id, completed=False)).result_status = status
            await seed_encounter(db_session, live, rule_id, [(None, 0), (None, 0), (None, 0)], name="Lobby")
            db_session.add_all(
                [
                    TournamentRecalculationState(tournament_id=live.id, requested_generation=2, completed_generation=1),
                    AchievementRule(
                        workspace_id=workspace_id,
                        slug=f"dash-{uuid.uuid4().hex[:8]}",
                        name="Rule",
                        description_ru="ru",
                        description_en="en",
                        discipline=live.discipline,
                        category="overall",
                        scope="global",
                        grain="user",
                        condition_tree={},
                        depends_on=[],
                        enabled=True,
                        rule_version=1,
                    ),
                    EvaluationRun(workspace_id=workspace_id, trigger="manual", tournament_id=live.id, status="done"),
                ]
            )
            ids = {"registration": registration.id, "live": live.id}
            await db_session.commit()
            db_session.expunge_all()

            pairs = []
            for permissions in grants:
                dashboard = await overview.get_dashboard(
                    db_session, workspace_id=workspace_id, permissions=permissions, now=now
                )
                for card in dashboard.tournaments:
                    checklist = await readiness.compute_readiness(
                        db_session,
                        card.id,
                        can_tournament_read=permissions.tournament_read,
                        can_team_read=permissions.team_read,
                        can_match_read=permissions.match_read,
                        can_achievement_read=permissions.achievement_read,
                    )
                    pairs.append((card.readiness, checklist))
            return pairs, ids
        finally:
            await _drop(db_session, workspace_id, [])

    pairs, ids = asyncio.run(go())

    assert len(pairs) == 2 * len(grants)
    for card_readiness, checklist in pairs:
        assert card_readiness == checklist
    # Not two empty checklists agreeing: every group carries data, and the two cards carry different data.
    full = {card_readiness.tournament_id: card_readiness for card_readiness, _ in pairs[:2]}
    registration, live = full[ids["registration"]], full[ids["live"]]
    assert (registration.schedule_configured, registration.stage_slots_filled, registration.bracket_generated) == (
        True,
        False,
        False,
    )
    assert (registration.registrations_pending, registration.registrations_ranked, registration.pool_need_fix) == (
        1,
        2,
        1,
    )
    assert registration.registration_form_configured is True
    assert (live.stage_slots_filled, live.bracket_generated, live.duel_encounters_total) == (True, True, 4)
    assert (live.results_overdue, live.results_pending_confirmation, live.results_disputed) == (1, 1, 1)
    assert (live.registrations_checked_in, live.registrations_ranked) == (1, 1)
    assert (live.standings_recalc_pending, live.achievements_status, registration.achievements_status) == (
        True,
        "done",
        "none",
    )


def test_the_dashboard_costs_the_same_statements_at_any_card_count(db_session) -> None:
    now = datetime.now(UTC)

    async def go() -> list[tuple[int, int]]:
        workspace_id = await _workspace(db_session)
        engine = db_session.bind.sync_engine
        statements: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            statements.append(statement)

        sa_event.listen(engine, "before_cursor_execute", record)
        try:
            costs = []
            for added in (1, 2):
                for _ in range(added):
                    tournament = await _tournament(
                        db_session,
                        workspace_id,
                        TS.REGISTRATION,
                        schedule=((TS.REGISTRATION, now - timedelta(days=1), now + timedelta(days=3)),),
                    )
                    db_session.add(Registration(tournament_id=tournament.id, display_name="p", status="pending"))
                await db_session.commit()
                db_session.expunge_all()
                statements.clear()
                dashboard = await overview.get_dashboard(
                    db_session, workspace_id=workspace_id, permissions=EVERYTHING, now=now
                )
                costs.append((len(dashboard.tournaments), len(statements)))
            return costs
        finally:
            sa_event.remove(engine, "before_cursor_execute", record)
            await _drop(db_session, workspace_id, [])

    (one, one_cost), (three, three_cost) = asyncio.run(go())

    assert (one, three) == (1, 3)
    assert one_cost == three_cost


# --- RPC gate + masking ------------------------------------------------------------


def test_masked_groups_are_null_not_zero(rpc, db_session) -> None:
    now = datetime.now(UTC)

    async def go() -> tuple[dict, int, int]:
        workspace_id = await _workspace(db_session)
        try:
            tournament = await _tournament(
                db_session,
                workspace_id,
                TS.REGISTRATION,
                schedule=((TS.REGISTRATION, now - timedelta(days=1), now + timedelta(days=3)),),
            )
            db_session.add(Registration(tournament_id=tournament.id, display_name="p", status="pending"))
            archived = await _tournament(db_session, workspace_id, TS.ARCHIVED)
            db_session.add(Team(tournament_id=archived.id, name="Empty", balancer_name="empty"))
            await db_session.commit()
            resp = await rpc.call(
                TOPIC,
                {
                    "query": {"workspace_id": [str(workspace_id)]},
                    "identity": _identity(workspace_id, [{"resource": "team", "action": "read"}]),
                },
            )
            return resp, tournament.id, archived.id
        finally:
            await _drop(db_session, workspace_id, [])

    resp, tournament_id, archived_id = asyncio.run(go())

    assert resp["ok"] is True, resp
    data = resp["data"]
    (card,) = data["tournaments"]
    assert card["id"] == tournament_id
    # tournament.read / match.read groups: masked.
    assert card["phase_schedule"] == []
    assert card["next_deadline_at"] is None
    assert card["play"] is None
    assert card["readiness"]["stages_total"] is None
    assert data["timeline"] is None
    # team.read group: visible.
    assert card["registrations_last_24h"] == 1
    assert card["readiness"]["registrations_pending"] == 1
    assert [issue["key"] for issue in data["issues"]] == ["registrations_pending"]
    backlog = data["backlog"]
    (row,) = backlog["rows"]
    assert (row["tournament_id"], row["teams_without_players"]) == (archived_id, 1)
    assert row["encounters_missing_logs"] is None
    assert row["stage_slots_empty"] is None
    assert row["has_stages"] is None
    assert backlog["teams_without_players"] == 1
    for masked in ("encounters_missing_logs", "tournaments_without_stages", "stage_slots_empty"):
        assert backlog[masked] is None
    assert backlog["users_without_identities"] is None


def test_workspace_id_is_required_even_for_a_superuser(rpc) -> None:
    for topic in (TOPIC, TRENDS_TOPIC):
        resp = rpc.call_sync(topic, {"identity": SUPERUSER})
        assert resp["ok"] is False
        assert resp["error"]["code"] == "unprocessable"


def test_forbidden_without_any_dashboard_permission(rpc) -> None:
    workspace_id = 987654321
    resp = rpc.call_sync(
        TOPIC,
        {
            "query": {"workspace_id": [str(workspace_id)]},
            "identity": _identity(workspace_id, [{"resource": "log", "action": "read"}]),
        },
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "forbidden"


def test_trends_need_tournament_read(rpc) -> None:
    workspace_id = 987654321
    resp = rpc.call_sync(
        TRENDS_TOPIC,
        {
            "query": {"workspace_id": [str(workspace_id)]},
            "identity": _identity(workspace_id, [{"resource": "team", "action": "read"}]),
        },
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "forbidden"

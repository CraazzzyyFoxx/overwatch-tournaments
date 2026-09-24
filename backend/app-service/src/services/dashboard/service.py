import asyncio

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.services.registration_window import registration_open_clause
from src import models, schemas
from src.core.db import async_session_maker

__all__ = ("DashboardService", "dashboard")


class DashboardService:
    """Aggregate dashboard reads: counts, data-quality issues, active-tournament
    stats, and the fan-out that runs the three of them concurrently."""

    async def get_dashboard_stats(self, *, workspace_id: int | None = None) -> schemas.DashboardStats:
        counts, issues, active_stats = await self._gather(workspace_id)

        active_tournament_stats = None
        if active_stats is not None:
            active_tournament_stats = schemas.DashboardActiveTournamentStats(**active_stats)

        return schemas.DashboardStats(
            **counts,
            active_tournament_stats=active_tournament_stats,
            issues=schemas.DashboardIssues(**issues),
        )

    async def _gather(self, workspace_id: int | None) -> tuple[dict, dict, dict | None]:
        # AsyncSession isn't concurrency-safe for parallel .execute() — spawn
        # independent sessions so the three independent dashboard queries
        # actually run in parallel.
        async def _run_counts() -> dict:
            async with async_session_maker() as s:
                return await self.get_counts(s, workspace_id)

        async def _run_issues() -> dict:
            async with async_session_maker() as s:
                return await self.get_issues(s, workspace_id)

        async def _run_active_stats() -> dict | None:
            async with async_session_maker() as s:
                return await self.get_active_tournament_stats(s, workspace_id)

        return await asyncio.gather(_run_counts(), _run_issues(), _run_active_stats())

    async def get_counts(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
    ) -> dict[str, int]:
        # Hidden tournaments (issue #115) never contribute to the public dashboard —
        # counts, issues, or the active-tournament pick — regardless of viewer. Every
        # query below is Tournament-scoped, so this exclusion is safe across all.
        ws_filters: list = [models.Tournament.is_hidden.is_(False)]
        if workspace_id is not None:
            ws_filters.append(models.Tournament.workspace_id == workspace_id)

        tournaments_total = sa.select(sa.func.count(models.Tournament.id)).where(*ws_filters)
        tournaments_active = sa.select(sa.func.count(models.Tournament.id)).where(
            models.Tournament.is_finished.is_(False), *ws_filters
        )
        teams_total = (
            sa.select(sa.func.count(models.Team.id))
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*ws_filters)
        )
        players_total = (
            sa.select(sa.func.count(models.Player.id))
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(*ws_filters)
        )
        encounters_total = (
            sa.select(sa.func.count(models.Encounter.id))
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*ws_filters)
        )
        # Decision metrics. `encounters_completed` pairs with `encounters_total` so
        # the dashboard can state bracket progress instead of a lifetime total, and
        # `tournaments_registration_open` answers "is anyone able to sign up right
        # now" — the number an organiser actually acts on.
        encounters_completed = (
            sa.select(sa.func.count(models.Encounter.id))
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(models.Encounter.status == enums.EncounterStatus.COMPLETED, *ws_filters)
        )
        # "Is anyone able to sign up right now" — now answered by the REGISTRATION
        # schedule window rather than a form boolean. The join to the form row stays:
        # a tournament with no registration form cannot be signed up for at all.
        tournaments_registration_open = (
            sa.select(sa.func.count(models.Tournament.id))
            .join(
                models.BalancerRegistrationForm,
                models.BalancerRegistrationForm.tournament_id == models.Tournament.id,
            )
            .where(registration_open_clause(), *ws_filters)
        )
        heroes_total = sa.select(sa.func.count(models.Hero.id))
        gamemodes_total = sa.select(sa.func.count(models.Gamemode.id))
        maps_total = sa.select(sa.func.count(models.Map.id))

        results = await session.execute(
            sa.select(
                tournaments_total.scalar_subquery(),
                tournaments_active.scalar_subquery(),
                teams_total.scalar_subquery(),
                players_total.scalar_subquery(),
                encounters_total.scalar_subquery(),
                encounters_completed.scalar_subquery(),
                tournaments_registration_open.scalar_subquery(),
                heroes_total.scalar_subquery(),
                gamemodes_total.scalar_subquery(),
                maps_total.scalar_subquery(),
            )
        )
        row = results.one()
        return {
            "tournaments_total": row[0] or 0,
            "tournaments_active": row[1] or 0,
            "teams_total": row[2] or 0,
            "players_total": row[3] or 0,
            "encounters_total": row[4] or 0,
            "encounters_completed": row[5] or 0,
            "tournaments_registration_open": row[6] or 0,
            "heroes_total": row[7] or 0,
            "gamemodes_total": row[8] or 0,
            "maps_total": row[9] or 0,
        }

    async def get_issues(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
    ) -> dict[str, int]:
        # Hidden tournaments (issue #115) never contribute to the public dashboard —
        # counts, issues, or the active-tournament pick — regardless of viewer. Every
        # query below is Tournament-scoped, so this exclusion is safe across all.
        ws_filters: list = [models.Tournament.is_hidden.is_(False)]
        if workspace_id is not None:
            ws_filters.append(models.Tournament.workspace_id == workspace_id)

        encounters_missing_logs = (
            sa.select(sa.func.count(models.Encounter.id))
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            # Same reason as the coverage join in ``get_active_tournament_stats``: a
            # lobby produces no match logs at all, so "missing logs" never applies.
            .where(models.Encounter.has_logs.is_(False), models.Encounter.format == "duel", *ws_filters)
        )

        # Anti-joins use correlated NOT EXISTS instead of NOT IN (subquery):
        # better plans (anti-join) and NULL-safe semantics.

        # Teams that have zero players
        teams_without_players_q = (
            sa.select(sa.func.count(models.Team.id))
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(
                ~sa.exists().where(models.Player.team_id == models.Team.id),
                *ws_filters,
            )
        )

        # Tournaments that have zero stages
        tournaments_without_stages_q = sa.select(sa.func.count(models.Tournament.id)).where(
            ~sa.exists().where(models.Stage.tournament_id == models.Tournament.id),
            *ws_filters,
        )

        # A scheduled slot that has passed with nothing recorded — the encounter is
        # neither completed nor carrying a captain submission. Unscheduled matches
        # are excluded: there is no deadline to be late against.
        encounters_awaiting_result_q = (
            sa.select(sa.func.count(models.Encounter.id))
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(
                models.Encounter.status != enums.EncounterStatus.COMPLETED,
                models.Encounter.result_status == enums.EncounterResultStatus.NONE,
                models.Encounter.scheduled_at.is_not(None),
                models.Encounter.scheduled_at < sa.func.now(),
                *ws_filters,
            )
        )

        # Captains reported, an admin still has to confirm.
        encounters_pending_confirmation_q = (
            sa.select(sa.func.count(models.Encounter.id))
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(
                models.Encounter.result_status == enums.EncounterResultStatus.PENDING_CONFIRMATION,
                *ws_filters,
            )
        )

        # Bracket slots never wired to a team/winner source.
        stage_slots_empty_q = (
            sa.select(sa.func.count(models.StageItemInput.id))
            .join(models.StageItem, models.StageItem.id == models.StageItemInput.stage_item_id)
            .join(models.Stage, models.Stage.id == models.StageItem.stage_id)
            .join(models.Tournament, models.Tournament.id == models.Stage.tournament_id)
            .where(
                models.StageItemInput.input_type == enums.StageItemInputType.EMPTY,
                *ws_filters,
            )
        )

        # Users that have no social account (battle_tag / discord / twitch / …).
        # Player identities are platform-wide, so unlike every count above there is
        # no Tournament to hang ``ws_filters`` on: the workspace is reached through
        # ``workspace_member``, the same hop the Player-identities list uses
        # (``services.admin.user.get_users``). Without it a workspace owner — who
        # now sees this card — would be handed the platform-wide number and land on
        # a page listing only their own roster.
        users_without_identities_q = sa.select(sa.func.count(models.User.id)).where(
            ~sa.exists().where(models.SocialAccount.user_id == models.User.id)
        )
        if workspace_id is not None:
            users_without_identities_q = users_without_identities_q.where(
                sa.exists()
                .where(models.WorkspaceMember.player_id == models.User.id)
                .where(models.WorkspaceMember.workspace_id == workspace_id)
            )

        results = await session.execute(
            sa.select(
                encounters_missing_logs.scalar_subquery(),
                teams_without_players_q.scalar_subquery(),
                tournaments_without_stages_q.scalar_subquery(),
                users_without_identities_q.scalar_subquery(),
                encounters_awaiting_result_q.scalar_subquery(),
                encounters_pending_confirmation_q.scalar_subquery(),
                stage_slots_empty_q.scalar_subquery(),
            )
        )
        row = results.one()
        return {
            "encounters_missing_logs": row[0] or 0,
            "teams_without_players": row[1] or 0,
            "tournaments_without_stages": row[2] or 0,
            "users_without_identities": row[3] or 0,
            "encounters_awaiting_result": row[4] or 0,
            "encounters_pending_confirmation": row[5] or 0,
            "stage_slots_empty": row[6] or 0,
        }

    async def get_active_tournament_stats(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
    ) -> dict | None:
        # Hidden tournaments (issue #115) never contribute to the public dashboard —
        # counts, issues, or the active-tournament pick — regardless of viewer. Every
        # query below is Tournament-scoped, so this exclusion is safe across all.
        ws_filters: list = [models.Tournament.is_hidden.is_(False)]
        if workspace_id is not None:
            ws_filters.append(models.Tournament.workspace_id == workspace_id)

        # Most recent live tournament + its encounter counts in one round trip.
        # An empty CTE (no live tournament) yields zero rows → None.
        active = (
            sa.select(models.Tournament.id.label("tournament_id"))
            .where(models.Tournament.is_finished.is_(False), *ws_filters)
            .order_by(models.Tournament.id.desc())
            .limit(1)
            .cte("active_tournament")
        )
        stats_q = (
            sa.select(
                active.c.tournament_id,
                sa.func.count(models.Encounter.id),
                sa.func.count(models.Encounter.id).filter(models.Encounter.has_logs.is_(False)),
            )
            .select_from(active)
            .outerjoin(
                models.Encounter,
                sa.and_(
                    models.Encounter.tournament_id == active.c.tournament_id,
                    # A lobby has no log format yet: counting it as "missing logs"
                    # would drag coverage down for a tournament that is complete.
                    models.Encounter.format == "duel",
                ),
            )
            .group_by(active.c.tournament_id)
        )
        row = (await session.execute(stats_q)).one_or_none()
        if row is None:
            return None

        tournament_id, total, missing = row
        total = total or 0
        missing = missing or 0
        coverage = round(((total - missing) / total) * 100) if total > 0 else 100

        return {
            "tournament_id": tournament_id,
            "encounters_total": total,
            "encounters_missing_logs": missing,
            "log_coverage_percent": coverage,
        }


dashboard = DashboardService()

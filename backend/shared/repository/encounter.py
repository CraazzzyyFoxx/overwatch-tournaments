"""Encounter-satellite CRUD: games, audits, room journal, saved views, links.

The ``Encounter`` row itself lives in :mod:`shared.repository.tournament`
(``EncounterRepository``); this module owns the tables that hang off it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import enums
from shared.repository.base import BaseRepository


class EncounterGameRepository(BaseRepository[models.EncounterGame]):
    def __init__(self) -> None:
        super().__init__(models.EncounterGame)

    async def list_for_encounter(
        self, session: AsyncSession, encounter_id: int, *, include_cancelled: bool = False
    ) -> Sequence[models.EncounterGame]:
        query = self.select().where(models.EncounterGame.encounter_id == encounter_id)
        if not include_cancelled:
            query = query.where(models.EncounterGame.state != enums.EncounterGameState.CANCELLED)
        result = await session.execute(query.order_by(models.EncounterGame.position, models.EncounterGame.id))
        return result.scalars().all()

    async def get_for_update(self, session: AsyncSession, game_id: int) -> models.EncounterGame | None:
        result = await session.execute(
            self.select()
            .where(models.EncounterGame.id == game_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()


class EncounterGameTeamRepository(BaseRepository[models.EncounterGameTeam]):
    """``encounter.game_team`` — one participation's side and numbers in one game."""

    def __init__(self) -> None:
        super().__init__(models.EncounterGameTeam)

    def add(self, session: AsyncSession, row: models.EncounterGameTeam) -> models.EncounterGameTeam:
        """Stage one row. No flush: the caller sets its side before its own flush."""
        session.add(row)
        return row

    async def confirmed_lines(self, session: AsyncSession, encounter_id: int) -> list[list[models.EncounterGameTeam]]:
        """Every confirmed game's rows, oldest position first, grouped per game.

        The shape the scoring engine is handed: one inner list per game, in the
        order they count. Cancelled and unfinished positions are not part of a
        standing, so they never reach it.
        """
        result = await session.execute(
            sa.select(models.EncounterGameTeam, models.EncounterGame.id)
            .join(models.EncounterGame, models.EncounterGame.id == models.EncounterGameTeam.game_id)
            .where(
                models.EncounterGame.encounter_id == encounter_id,
                models.EncounterGame.state == enums.EncounterGameState.CONFIRMED,
            )
            .order_by(
                models.EncounterGame.position,
                models.EncounterGame.id,
                models.EncounterGameTeam.encounter_team_id,
            )
        )
        games: dict[int, list[models.EncounterGameTeam]] = {}
        for line, game_id in result:
            games.setdefault(game_id, []).append(line)
        return list(games.values())

    async def list_for_games(
        self, session: AsyncSession, game_ids: Sequence[int]
    ) -> Sequence[models.EncounterGameTeam]:
        """Every line of the given games, in game then participation order."""
        if not game_ids:
            return []
        result = await session.execute(
            self.select()
            .where(models.EncounterGameTeam.game_id.in_(tuple(game_ids)))
            .order_by(models.EncounterGameTeam.game_id, models.EncounterGameTeam.encounter_team_id)
        )
        return result.scalars().all()

    def _stage_lines(self, stage_id: int) -> sa.Select:
        """Every confirmed game line of one stage, through the bracket position."""
        return (
            self.select()
            .join(models.EncounterGame, models.EncounterGame.id == models.EncounterGameTeam.game_id)
            .join(
                models.BracketEncounter,
                models.BracketEncounter.encounter_id == models.EncounterGame.encounter_id,
            )
            .where(
                models.BracketEncounter.stage_id == stage_id,
                models.EncounterGame.state == enums.EncounterGameState.CONFIRMED,
            )
        )

    async def stage_has_unplaced_results(self, session: AsyncSession, stage_id: int) -> bool:
        """Is any confirmed line of this stage missing an entered placement?

        The guard behind a formula edit: a rule that READS a team's place needs
        every place entered by hand, and a stage that already recorded games
        without one cannot be re-scored by it.
        """
        row = await session.execute(
            self._stage_lines(stage_id).where(models.EncounterGameTeam.placement.is_(None)).limit(1)
        )
        return row.scalars().first() is not None

    async def stat_keys_for_stage(self, session: AsyncSession, stage_id: int) -> set[str]:
        """Every organizer column key this stage's games actually recorded.

        Read off the stored documents rather than the rule, so dropping a column
        that games were entered under can be refused.
        """
        rows = await session.execute(
            sa.select(sa.func.jsonb_object_keys(models.EncounterGameTeam.column_values))
            .select_from(models.EncounterGameTeam)
            .join(models.EncounterGame, models.EncounterGame.id == models.EncounterGameTeam.game_id)
            .join(
                models.BracketEncounter,
                models.BracketEncounter.encounter_id == models.EncounterGame.encounter_id,
            )
            .where(
                models.BracketEncounter.stage_id == stage_id,
                models.EncounterGame.state == enums.EncounterGameState.CONFIRMED,
            )
        )
        return set(rows.scalars())


class EncounterGameClaimRepository(BaseRepository[models.EncounterGameClaim]):
    """``encounter.game_claim`` — what one participation says a game ended on.

    A claim is one row per claimant plus one ``game_claim_result`` row per
    participation it names, so a lobby's claim and a duel's are the same shape.
    """

    def __init__(self) -> None:
        super().__init__(models.EncounterGameClaim)

    async def list_for_game(self, session: AsyncSession, game_id: int) -> Sequence[models.EncounterGameClaim]:
        result = await session.execute(
            self.select()
            .where(models.EncounterGameClaim.game_id == game_id)
            .order_by(models.EncounterGameClaim.claimant_team_id)
        )
        return result.scalars().all()

    async def results_for_claims(
        self, session: AsyncSession, claim_ids: Sequence[int]
    ) -> dict[int, list[models.EncounterGameClaimResult]]:
        """``claim_id -> its lines``; every asked-for claim gets a key."""
        grouped: dict[int, list[models.EncounterGameClaimResult]] = {claim_id: [] for claim_id in claim_ids}
        if not claim_ids:
            return grouped
        rows = await session.execute(
            sa.select(models.EncounterGameClaimResult)
            .where(models.EncounterGameClaimResult.claim_id.in_(tuple(claim_ids)))
            .order_by(
                models.EncounterGameClaimResult.claim_id,
                models.EncounterGameClaimResult.encounter_team_id,
            )
        )
        for row in rows.scalars():
            grouped[row.claim_id].append(row)
        return grouped

    async def replace_results(
        self,
        session: AsyncSession,
        claim: models.EncounterGameClaim,
        rows: Sequence[models.EncounterGameClaimResult],
    ) -> None:
        """A re-filed claim replaces its lines; the claim row keeps its id."""
        await session.execute(
            sa.delete(models.EncounterGameClaimResult).where(models.EncounterGameClaimResult.claim_id == claim.id)
        )
        session.add_all(rows)
        await session.flush()


class EncounterTeamReportRepository(BaseRepository[models.EncounterTeamReport]):
    """``encounter.team_report`` — a participation's report of the WHOLE encounter."""

    def __init__(self) -> None:
        super().__init__(models.EncounterTeamReport)

    async def list_for_encounter(
        self, session: AsyncSession, encounter_id: int
    ) -> Sequence[models.EncounterTeamReport]:
        result = await session.execute(
            self.select()
            .where(models.EncounterTeamReport.encounter_id == encounter_id)
            .order_by(models.EncounterTeamReport.encounter_team_id)
        )
        return result.scalars().all()

    async def results_for_reports(
        self, session: AsyncSession, report_ids: Sequence[int]
    ) -> dict[int, list[models.EncounterTeamReportResult]]:
        """``report_id -> its lines``; every asked-for report gets a key."""
        grouped: dict[int, list[models.EncounterTeamReportResult]] = {report_id: [] for report_id in report_ids}
        if not report_ids:
            return grouped
        rows = await session.execute(
            sa.select(models.EncounterTeamReportResult)
            .where(models.EncounterTeamReportResult.report_id.in_(tuple(report_ids)))
            .order_by(
                models.EncounterTeamReportResult.report_id,
                models.EncounterTeamReportResult.encounter_team_id,
            )
        )
        for row in rows.scalars():
            grouped[row.report_id].append(row)
        return grouped

    async def replace_results(
        self,
        session: AsyncSession,
        report: models.EncounterTeamReport,
        rows: Sequence[models.EncounterTeamReportResult],
    ) -> None:
        """A re-filed report replaces its lines; the report row keeps its id."""
        await session.execute(
            sa.delete(models.EncounterTeamReportResult).where(models.EncounterTeamReportResult.report_id == report.id)
        )
        session.add_all(rows)
        await session.flush()


class EncounterTeamRepository(BaseRepository[models.EncounterTeam]):
    """``encounter.team`` — the participations.

    Append-only by design: there is no reactivate and no delete here. A seat
    changes hands by retiring one row and writing the next, which is what keeps
    the games, claims and journal that point at it answerable afterwards.
    """

    def __init__(self) -> None:
        super().__init__(models.EncounterTeam)

    async def list_active(self, session: AsyncSession, encounter_id: int) -> Sequence[models.EncounterTeam]:
        result = await session.execute(
            self.select()
            .where(models.EncounterTeam.encounter_id == encounter_id, models.EncounterTeam.active.is_(True))
            .order_by(models.EncounterTeam.slot, models.EncounterTeam.id)
        )
        return result.scalars().all()

    async def get_active_slot(self, session: AsyncSession, encounter_id: int, slot: int) -> models.EncounterTeam | None:
        return await self.get_by(session, encounter_id=encounter_id, slot=slot, active=True)


class EncounterTeamMemberRepository(BaseRepository[models.EncounterTeamMember]):
    """``encounter.team_member`` — one participation's snapshotted roster.

    No deactivate: ``team_member.active`` is carried by the participation's
    through ``fk_team_member_team``'s ON UPDATE CASCADE (A2), and a second
    writer of that column could only disagree with the first.
    """

    def __init__(self) -> None:
        super().__init__(models.EncounterTeamMember)

    async def active_team_id(self, session: AsyncSession, encounter_id: int, workspace_member_id: int) -> int | None:
        """The live participation this member is seated on in this encounter, if any."""
        return await session.scalar(
            sa.select(models.EncounterTeamMember.encounter_team_id).where(
                models.EncounterTeamMember.encounter_id == encounter_id,
                models.EncounterTeamMember.workspace_member_id == workspace_member_id,
                models.EncounterTeamMember.active.is_(True),
            )
        )


class EncounterTeamMemberRoleRepository(BaseRepository[models.EncounterTeamMemberRole]):
    """``encounter.team_member_role`` — a roster member's roles, per dimension."""

    def __init__(self) -> None:
        super().__init__(models.EncounterTeamMemberRole)


class EncounterResultAuditRepository(BaseRepository[models.EncounterResultAudit]):
    def __init__(self) -> None:
        super().__init__(models.EncounterResultAudit)

    def add(self, session: AsyncSession, row: models.EncounterResultAudit) -> models.EncounterResultAudit:
        """Stage one journal row. No flush — rides the caller's transaction."""
        session.add(row)
        return row

    async def list_for_encounter(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        limit: int | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.EncounterResultAudit]:
        query = self._apply_options(
            self.select()
            .where(models.EncounterResultAudit.encounter_id == encounter_id)
            .order_by(
                models.EncounterResultAudit.created_at.desc(),
                models.EncounterResultAudit.id.desc(),
            ),
            options,
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def pending_holds_since_last_decision(self, session: AsyncSession, encounter_id: int) -> int:
        """How many ``auto_pending`` rows sit above the last journalled change
        that was not one.

        A hold only says "a report has been filed, the rest are owed"; it moves
        no standing, so a form filled in before it was written is still about
        the same result. Counting from the top of the journal -- rather than
        looking for the last non-hold row -- also holds for an encounter whose
        older versions were never journalled: every version it has above the
        holds is then simply the current one minus the count.
        """
        audit = models.EncounterResultAudit
        last_decision = (
            sa.select(sa.func.coalesce(sa.func.max(audit.result_version), 0))
            .where(audit.encounter_id == encounter_id, audit.action != enums.EncounterResultAuditAction.AUTO_PENDING)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.select(sa.func.count()).where(
                audit.encounter_id == encounter_id,
                audit.action == enums.EncounterResultAuditAction.AUTO_PENDING,
                audit.result_version > last_decision,
            )
        )
        return int(result.scalar_one())

    async def list_with_actor(
        self, session: AsyncSession, encounter_id: int, *, limit: int
    ) -> Sequence[tuple[models.EncounterResultAudit, str | None, int | None]]:
        """The result half of the room journal: newest first, each row with its
        actor's display name and -- for a per-game row -- the series position it
        decided.

        ``actor_user_id`` is a PLAYER identity (``identity.user``), not the auth
        account the room journal names, so the name comes from a different table
        than :meth:`EncounterRoomEventRepository.list_with_actor`'s and the two
        are merged by the reader. Both joins are LEFT OUTER: a series-level row
        has no game, an imported or cascaded one has no actor, and a deleted
        account must not erase what it decided.
        """
        result = await session.execute(
            sa.select(self.model, models.User.name, models.EncounterGame.position)
            .outerjoin(models.User, models.User.id == self.model.actor_user_id)
            .outerjoin(models.EncounterGame, models.EncounterGame.id == self.model.game_id)
            .where(self.model.encounter_id == encounter_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(limit)
        )
        return result.all()


class EncounterRoomEventRepository(BaseRepository[models.EncounterRoomEvent]):
    def __init__(self) -> None:
        super().__init__(models.EncounterRoomEvent)

    def add(self, session: AsyncSession, row: models.EncounterRoomEvent) -> models.EncounterRoomEvent:
        """Stage one journal row. No flush — rides the caller's transaction."""
        session.add(row)
        return row

    async def list_with_actor(
        self, session: AsyncSession, encounter_id: int, *, limit: int
    ) -> Sequence[tuple[models.EncounterRoomEvent, str | None]]:
        """The room half of the journal: newest first, each row with its actor's
        account name. LEFT OUTER -- a clock/engine row has no actor at all."""
        result = await session.execute(
            sa.select(self.model, models.AuthUser.username)
            .outerjoin(models.AuthUser, models.AuthUser.id == self.model.actor_auth_user_id)
            .where(self.model.encounter_id == encounter_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(limit)
        )
        return result.all()

    async def receipts_for_evidence(
        self, session: AsyncSession, encounter_id: int, *, action: str, game_id: int, evidence_id: int
    ) -> Sequence[tuple[int | None, str | None]]:
        """``(revision, event_id)`` of every ``action`` receipt of this evidence on this game.

        A direct, unbounded read of the scoped journal -- deliberately not ``list_with_actor``, whose newest-N
        window would let a busy room push an old receipt out and a stale revision through.
        """
        data = self.model.data
        result = await session.execute(
            sa.select(data["revision"].as_integer(), data["event_id"].as_string()).where(
                self.model.encounter_id == encounter_id,
                self.model.action == action,
                data["game_id"].as_integer() == game_id,
                data["evidence_id"].as_integer() == evidence_id,
            )
        )
        return result.all()


class EncounterReportFormRepository(BaseRepository[models.EncounterReportForm]):
    def __init__(self) -> None:
        super().__init__(models.EncounterReportForm)

    async def get_by_tournament(self, session: AsyncSession, tournament_id: int) -> models.EncounterReportForm | None:
        return await self.get_by(session, tournament_id=tournament_id)


class EncounterSavedViewRepository(BaseRepository[models.EncounterSavedView]):
    def __init__(self) -> None:
        super().__init__(models.EncounterSavedView)

    async def list_for_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> Sequence[models.EncounterSavedView]:
        result = await session.execute(
            self.select()
            .where(
                models.EncounterSavedView.workspace_id == workspace_id,
                models.EncounterSavedView.auth_user_id == auth_user_id,
            )
            .order_by(
                models.EncounterSavedView.sort_order.asc(),
                models.EncounterSavedView.created_at.asc(),
            )
        )
        return result.scalars().all()

    async def get_owned(
        self,
        session: AsyncSession,
        *,
        saved_view_id: int,
        workspace_id: int,
        auth_user_id: int,
    ) -> models.EncounterSavedView | None:
        return await self.get_by(
            session,
            id=saved_view_id,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
        )


class EncounterLinkRepository(BaseRepository[models.EncounterLink]):
    """``encounter_link`` — bracket wiring between a source and a target encounter."""

    def __init__(self) -> None:
        super().__init__(models.EncounterLink)

    async def list_by_source_ids(
        self, session: AsyncSession, source_encounter_ids: Sequence[int]
    ) -> Sequence[models.EncounterLink]:
        if not source_encounter_ids:
            return []
        result = await session.execute(
            self.select().where(models.EncounterLink.source_encounter_id.in_(tuple(source_encounter_ids)))
        )
        return result.scalars().all()


class ScoringRuleRepository(BaseRepository[models.ScoringRule]):
    """``encounter.scoring_rule`` — how an encounter turns games into a standing."""

    def __init__(self) -> None:
        super().__init__(models.ScoringRule)


__all__ = (
    "EncounterGameClaimRepository",
    "EncounterGameRepository",
    "EncounterGameTeamRepository",
    "EncounterLinkRepository",
    "EncounterReportFormRepository",
    "EncounterResultAuditRepository",
    "EncounterRoomEventRepository",
    "EncounterSavedViewRepository",
    "EncounterTeamMemberRepository",
    "EncounterTeamMemberRoleRepository",
    "EncounterTeamReportRepository",
    "EncounterTeamRepository",
    "ScoringRuleRepository",
)

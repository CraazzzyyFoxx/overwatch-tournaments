"""Admin-only emergency role additions during a live draft.

The write lands on the REGISTRATION (``balancer.registration_role``), not on a
draft-local copy: the balancer is the only writer of roles and ranks, so the
draft board, the pool verdict and the balance job all see the edit at once and
cannot disagree about it. The draft's own contribution is the guard (may this
session accept an edit?), the before/after feasibility preview, and the private
audit record.

Validation and the preview are pure and live in ``src.domain.draft.rules``;
this file holds only the orchestration that needs a database session.
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HeroClass
from shared.domain.roster import PlayerRoster
from shared.models.balancer.draft import DraftAuditEvent, DraftPlayer, DraftSession
from shared.models.registration.registration import BalancerRegistrationRole
from shared.repository.draft import DraftAuditEventRepository, DraftPlayerRepository
from shared.repository.registration import BalancerRegistrationRoleRepository
from src.domain.draft import rules
from src.domain.draft.entities import DraftFeasibilityReport, RoleEditPreview, RoleEditResult
from src.services.draft import loaders
from src.services.draft._errors import err as _err
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.rosters import DraftRosterService, draft_rosters

__all__ = ("DraftRoleEditService", "role_edit_service")


class DraftRoleEditService:
    def __init__(
        self,
        *,
        players_repo: DraftPlayerRepository = DraftPlayerRepository(),
        audit_repo: DraftAuditEventRepository = DraftAuditEventRepository(),
        roles_repo: BalancerRegistrationRoleRepository = BalancerRegistrationRoleRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
        rosters: DraftRosterService = draft_rosters,
    ) -> None:
        self.players_repo = players_repo
        self.audit_repo = audit_repo
        self.roles_repo = roles_repo
        self.feasibility = feasibility
        self.rosters = rosters

    def _report_json(self, report: DraftFeasibilityReport) -> dict:
        return {
            "is_feasible": report.is_feasible,
            "total_open_slots": report.total_open_slots,
            "matched_slots": report.matched_slots,
            "unmatched_slots": [
                {"team_id": slot.team_id, "slot_code": slot.slot_code, "ordinal": slot.ordinal}
                for slot in report.unmatched_slots
            ],
            "slot_deficits": [
                {
                    "slot_code": deficit.slot_code,
                    "unmatched_slots": deficit.unmatched_slots,
                    "eligible_players": deficit.eligible_players,
                }
                for deficit in report.slot_deficits
            ],
            "blocking_player_ids": list(report.blocking_player_ids),
            "reason_code": report.reason_code,
        }

    def _roles_json(self, roster: PlayerRoster | None) -> list[dict]:
        if roster is None:
            return []
        return [
            {
                "role": entry.role.slot_code,
                "rank_value": entry.rank,
                "rank_source": entry.source,
                "is_primary": entry.is_primary,
                "priority": entry.priority,
            }
            for entry in roster.roles
        ]

    async def _write_registration_role(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        role: HeroClass,
        rank_value: int,
    ) -> None:
        """Add or re-activate the role on the registration, with its rank.

        Upsert rather than insert: the row may already exist inactive (a sheet
        import whose rank did not parse), which is the common case for a role the
        organizer now has to add by hand.
        """
        existing = await session.scalar(
            sa.select(BalancerRegistrationRole).where(
                BalancerRegistrationRole.registration_id == registration_id,
                BalancerRegistrationRole.role == role.slot_code,
            )
        )
        if existing is not None:
            existing.rank_value = rank_value
            existing.is_active = True
            return
        next_priority = (
            await session.scalar(
                sa.select(sa.func.coalesce(sa.func.max(BalancerRegistrationRole.priority), -1)).where(
                    BalancerRegistrationRole.registration_id == registration_id
                )
            )
        ) + 1
        await self.roles_repo.create(
            session,
            BalancerRegistrationRole(
                registration_id=registration_id,
                role=role.slot_code,
                is_primary=False,
                priority=next_priority,
                rank_value=rank_value,
                is_active=True,
            ),
        )

    async def apply_role_edit(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        player: DraftPlayer,
        roster: PlayerRoster | None,
        *,
        role: HeroClass,
        rank_value: int,
        reason: str,
        actor_auth_user_id: int,
        preview: RoleEditPreview,
    ) -> DraftAuditEvent:
        """Write the registration, bump the seat, and record the private audit row."""

        before_roles = self._roles_json(roster)
        before_version = player.version
        await self._write_registration_role(session, player.registration_id, role=role, rank_value=rank_value)
        # The seat's version is the optimistic token the preview was taken
        # against, so it moves even though the roles now live elsewhere.
        player.version += 1
        await session.flush()
        after_roster = (await self.rosters.load(session, draft_session, [player])).get(player.id)
        audit = DraftAuditEvent(
            session_id=draft_session.id,
            actor_auth_user_id=actor_auth_user_id,
            action="player_role_added",
            entity_type="draft_player",
            entity_id=player.id,
            reason=reason.strip(),
            before_json={
                "player_version": before_version,
                "registration_id": player.registration_id,
                "roles": before_roles,
                "feasibility": self._report_json(preview.before),
            },
            after_json={
                "player_version": player.version,
                "registration_id": player.registration_id,
                "roles": self._roles_json(after_roster),
                "feasibility": self._report_json(preview.after),
            },
        )
        return await self.audit_repo.create(session, audit)

    async def edit_player_role(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        player_id: int,
        role: HeroClass,
        rank_value: int,
        reason: str,
        expected_version: int,
        actor_auth_user_id: int,
        preview_only: bool,
    ) -> RoleEditResult:
        player = await self.players_repo.get_for_update(
            session, player_id, session_id=draft_session.id, options=loaders.player_options()
        )
        if player is None:
            raise _err("player_not_found", "Player is not in this draft session", status_code=404)
        roster = (await self.rosters.load(session, draft_session, [player])).get(player.id)
        normalized_reason = rules.validate_role_edit_request(
            draft_session,
            player,
            roster,
            role=role,
            rank_value=rank_value,
            reason=reason,
            expected_version=expected_version,
        )
        state = await self.feasibility.load_feasibility_state(session, draft_session)
        # Two bipartite matchings (before/after) — pure CPU, run off the event loop.
        preview = await asyncio.to_thread(rules.preview_role_addition, state, player_id=player.id, role=role)
        if preview_only:
            return RoleEditResult(
                player_id=player.id,
                role=role,
                player_version=player.version,
                committed=False,
                preview=preview,
            )
        await self.apply_role_edit(
            session,
            draft_session,
            player,
            roster,
            role=role,
            rank_value=rank_value,
            reason=normalized_reason,
            actor_auth_user_id=actor_auth_user_id,
            preview=preview,
        )
        await session.flush()
        return RoleEditResult(
            player_id=player.id,
            role=role,
            player_version=player.version,
            committed=True,
            preview=preview,
        )


role_edit_service = DraftRoleEditService()

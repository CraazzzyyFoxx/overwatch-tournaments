"""Admin-only emergency role additions for a live-draft player snapshot."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPlayerStatus, DraftRole, DraftStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.models.balancer.draft import (
    DraftAuditEvent,
    DraftPlayer,
    DraftPlayerRole,
    DraftSession,
)
from src.services.draft import feasibility, loaders

_EDITABLE_STATUSES = {
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.PAUSED.value,
}


@dataclass(frozen=True)
class RoleEditPreview:
    before: feasibility.DraftFeasibilityReport
    after: feasibility.DraftFeasibilityReport


@dataclass(frozen=True)
class RoleEditResult:
    player_id: int
    role: DraftRole
    player_version: int
    committed: bool
    preview: RoleEditPreview


def _err(code: str, msg: str, *, status_code: int = 422) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


def validate_role_edit_request(
    draft_session: DraftSession,
    player: DraftPlayer,
    *,
    role: DraftRole,
    rank_value: int | None,
    rank_absence_confirmed: bool,
    reason: str,
    expected_version: int,
) -> str:
    """Validate both preview and commit; return the normalized private reason."""

    if draft_session.status not in _EDITABLE_STATUSES:
        raise _err("role_edit_requires_pause", "Pause the draft before editing a player role", status_code=409)
    if player.session_id != draft_session.id:
        raise _err("player_not_found", "Player is not in this draft session", status_code=404)
    if player.status != DraftPlayerStatus.AVAILABLE.value:
        raise _err("player_not_available", "Only a remaining available player can receive an emergency role")
    if player.version != expected_version:
        raise _err("draft_player_stale", "Player snapshot changed; reload the role-edit preview", status_code=409)
    if any(entry.role == role.value for entry in player.roles):
        raise _err("role_already_exists", f"Player already has the {role.value} role", status_code=409)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise _err("role_edit_reason_required", "A private audit reason is required")
    if rank_value is None and not rank_absence_confirmed:
        raise _err(
            "role_rank_confirmation_required",
            "Provide a role rank or explicitly confirm that it is unavailable",
        )
    return normalized_reason


def preview_role_addition(
    state: feasibility.DraftFeasibilityState,
    *,
    player_id: int,
    role: DraftRole,
) -> RoleEditPreview:
    before = feasibility.analyze_draft_feasibility(
        team_ids=state.team_ids,
        role_targets=state.role_targets,
        players=state.players,
        assignments=state.assignments,
    )
    found = False
    updated_players: list[feasibility.EligiblePlayer] = []
    for player in state.players:
        if player.player_id == player_id:
            found = True
            updated_players.append(
                feasibility.EligiblePlayer(
                    player_id=player.player_id,
                    playable_roles=player.playable_roles | {role},
                )
            )
        else:
            updated_players.append(player)
    if not found:
        raise _err("player_not_available", "Player is not available in the remaining draft pool", status_code=404)
    after = feasibility.analyze_draft_feasibility(
        team_ids=state.team_ids,
        role_targets=state.role_targets,
        players=tuple(updated_players),
        assignments=state.assignments,
    )
    return RoleEditPreview(before=before, after=after)


def _report_json(report: feasibility.DraftFeasibilityReport) -> dict:
    return {
        "is_feasible": report.is_feasible,
        "total_open_slots": report.total_open_slots,
        "matched_slots": report.matched_slots,
        "unmatched_slots": [
            {"team_id": slot.team_id, "role": slot.role.value, "ordinal": slot.ordinal}
            for slot in report.unmatched_slots
        ],
        "role_deficits": [
            {
                "role": deficit.role.value,
                "unmatched_slots": deficit.unmatched_slots,
                "eligible_players": deficit.eligible_players,
            }
            for deficit in report.role_deficits
        ],
        "blocking_player_ids": list(report.blocking_player_ids),
        "reason_code": report.reason_code,
    }


def _roles_json(player: DraftPlayer) -> list[dict]:
    return [
        {
            "role": entry.role,
            "rank_value": entry.rank_value,
            "is_secondary": entry.is_secondary,
            "priority": entry.priority,
        }
        for entry in sorted(player.roles, key=lambda entry: entry.priority)
    ]


def apply_role_edit(
    session: AsyncSession,
    draft_session: DraftSession,
    player: DraftPlayer,
    *,
    role: DraftRole,
    rank_value: int | None,
    reason: str,
    actor_auth_user_id: int,
    preview: RoleEditPreview,
) -> DraftAuditEvent:
    """Mutate only the draft snapshot and add its private audit record."""

    before_roles = _roles_json(player)
    before_version = player.version
    next_priority = max((entry.priority for entry in player.roles), default=-1) + 1
    player.roles.append(
        DraftPlayerRole(
            role=role.value,
            rank_value=rank_value,
            is_secondary=role.value != player.primary_role,
            priority=next_priority,
        )
    )
    player.version += 1
    audit = DraftAuditEvent(
        session_id=draft_session.id,
        actor_auth_user_id=actor_auth_user_id,
        action="player_role_added",
        entity_type="draft_player",
        entity_id=player.id,
        reason=reason.strip(),
        before_json={
            "player_version": before_version,
            "roles": before_roles,
            "feasibility": _report_json(preview.before),
        },
        after_json={
            "player_version": player.version,
            "roles": _roles_json(player),
            "feasibility": _report_json(preview.after),
        },
    )
    session.add(audit)
    return audit


async def edit_player_role(
    session: AsyncSession,
    draft_session: DraftSession,
    *,
    player_id: int,
    role: DraftRole,
    rank_value: int | None,
    rank_absence_confirmed: bool,
    reason: str,
    expected_version: int,
    actor_auth_user_id: int,
    preview_only: bool,
) -> RoleEditResult:
    player = await session.scalar(
        sa.select(DraftPlayer)
        .where(DraftPlayer.id == player_id, DraftPlayer.session_id == draft_session.id)
        .options(*loaders.player_options())
        .with_for_update()
    )
    if player is None:
        raise _err("player_not_found", "Player is not in this draft session", status_code=404)
    normalized_reason = validate_role_edit_request(
        draft_session,
        player,
        role=role,
        rank_value=rank_value,
        rank_absence_confirmed=rank_absence_confirmed,
        reason=reason,
        expected_version=expected_version,
    )
    state = await feasibility.load_feasibility_state(session, draft_session)
    preview = preview_role_addition(state, player_id=player.id, role=role)
    if preview_only:
        return RoleEditResult(
            player_id=player.id,
            role=role,
            player_version=player.version,
            committed=False,
            preview=preview,
        )
    apply_role_edit(
        session,
        draft_session,
        player,
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


__all__ = (
    "RoleEditPreview",
    "RoleEditResult",
    "apply_role_edit",
    "edit_player_role",
    "preview_role_addition",
    "validate_role_edit_request",
)

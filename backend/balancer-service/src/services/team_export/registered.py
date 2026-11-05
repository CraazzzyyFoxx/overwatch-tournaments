"""Synthesize a materialization payload from pre-formed registered teams.

A registered team is turned into the same :class:`MaterializationTeam` payload
the balancer and draft exports produce and handed to the same orchestrator, so
battle-tag resolution, name dedup, newcomer computation and the slot-to-catalog-role
mapping are shared and cannot drift.

Roles and ranks are NOT derived here. They come from ``shared.services.roster``,
the one engine that answers "which roles does this registration play, and at what
rank" for every surface. Two consequences worth stating:

* **Rank.** ``PlayerRoster.rank_on`` returns ``None`` for a role the player has
  no resolved rank on, and that is written as a NULL ``Player.rank`` (rank not
  specified). Raising instead would make the feature unusable for tournaments
  that never collect ranks.
* **Which rank.** On a role shape the rank is the rank *of that slot's role*,
  with no fallback to another role's number: a player placed on ``tank`` with no
  tank rank exports unranked, not at their damage rank. A role-less slot (an
  all-``flex`` shape, a ``flex`` slot, or no slot at all) names no role, so it
  takes the player's best playable rank.

Members are passed with ``workspace_member_id`` already set, so the seam's
"silently skipped because the battle tag did not resolve" branch — the one that
can produce an under-sized roster with no error — is unreachable on this path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.player_sub_roles import workspace_sub_role_slug
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import FLEX_SLOT_CODE, RosterShape
from shared.domain.team_subscription import SUBSCRIPTION_SCOPE_TEAM, team_subscription_is_current
from shared.models.registration.registration import (
    Registration,
    RegistrationEntry,
    RegistrationForm,
    RegistrationTeam,
)
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament import Tournament
from shared.services.roster import registration_load_options, roster_engine
from src.services.team_export.materialization import MaterializationMember, MaterializationTeam

__all__ = (
    "RegisteredExportPayload",
    "SkippedTeam",
    "build_registered_export",
)

#: Statuses that mean a member is not on the roster (their slot was released).
_RELEASED_STATUSES = frozenset({"withdrawn", "rejected"})
#: Only a complete team may be materialized: an incomplete one would produce an
#: under-sized ``tournament.team``, which the bracket then treats as real.
_EXPORTABLE_STATUS = "complete"


@dataclass(frozen=True)
class SkippedTeam:
    """A team the export deliberately left behind, with a machine-readable why."""

    team_id: int
    name: str
    code: str


@dataclass
class RegisteredExportPayload:
    teams: list[MaterializationTeam] = field(default_factory=list)
    #: ``tournament.team`` ids from a previous export of these same registered
    #: teams — deleted and rebuilt, so a re-export is idempotent rather than
    #: additive.
    prior_team_ids: list[int] = field(default_factory=list)
    skipped: list[SkippedTeam] = field(default_factory=list)
    #: The source rows, for the finalize/unlink hooks to stamp.
    source_teams: list[RegistrationTeam] = field(default_factory=list)


def _slot_role(slot_code: str | None, shape: RosterShape) -> str | None:
    """The role a roster slot rates the player on; ``None`` when it rates none.

    A ``flex`` slot, a slot-less member and every slot of an all-``flex`` shape
    all name no role, which is exactly :meth:`PlayerRoster.rank_on`'s ``None``.
    """
    if not shape.has_role_slots or slot_code is None or slot_code == FLEX_SLOT_CODE:
        return None
    return slot_code


def _sub_role_for(roster: PlayerRoster, role: str | None) -> str | None:
    """The sub-role the player declared *for this slot's role*.

    A role-less slot has no role to look up, so it takes the player's lead
    sub-role -- the one their primary role carries.
    """
    entry = roster.primary if role is None else next((entry for entry in roster.roles if entry.role == role), None)
    return workspace_sub_role_slug(entry.role, entry.subrole) if entry is not None and entry.subrole else None


def _member_name(roster: PlayerRoster) -> str:
    return roster.handle or roster.display_name or f"registration-{roster.registration_id}"


async def build_registered_export(
    session: AsyncSession,
    tournament_id: int,
    shape: RosterShape,
    registration_node_ids: Sequence[int],
    *,
    team_ids: Sequence[int] | None = None,
) -> RegisteredExportPayload:
    """Turn the complete registered teams of the given registration nodes into an export payload.

    ``registration_node_ids`` are the registration nodes feeding the exporting formation (its input): the teams of
    any other intake are not this formation's to materialize. ``team_ids`` narrows to a subset (one organizer
    exporting one team); omitted, every complete team is taken. Incomplete and terminal teams are reported in
    ``skipped`` rather than silently dropped: the people in a stuck team must be told.
    """
    payload = RegisteredExportPayload()

    conditions = [
        RegistrationTeam.tournament_id == tournament_id,
        RegistrationTeam.registration_node_id.in_(list(registration_node_ids)),
        RegistrationTeam.deleted_at.is_(None),
    ]
    if team_ids is not None:
        conditions.append(RegistrationTeam.id.in_(list(team_ids)))
    teams = list(
        await session.scalars(sa.select(RegistrationTeam).where(*conditions).order_by(RegistrationTeam.name_normalized))
    )
    if not teams:
        return payload

    # One query for every roster row across every team, carrying everything the
    # roster engine reads: the per-member fan would otherwise be O(members)
    # round-trips, and a lazy load under async raises ``MissingGreenlet``.
    # A member's participation is the entry in the node their team signs up through.
    rows = (
        await session.execute(
            sa.select(Registration, RegistrationEntry)
            .join(RegistrationEntry, RegistrationEntry.registration_id == Registration.id)
            .join(
                RegistrationTeam,
                sa.and_(
                    RegistrationTeam.id == Registration.registration_team_id,
                    RegistrationTeam.registration_node_id == RegistrationEntry.registration_node_id,
                ),
            )
            .where(
                Registration.registration_team_id.in_([team.id for team in teams]),
                Registration.deleted_at.is_(None),
                RegistrationEntry.deleted_at.is_(None),
                RegistrationEntry.status.notin_(_RELEASED_STATUSES),
            )
            .options(*registration_load_options())
        )
    ).all()
    registrations = [registration for registration, _ in rows]
    entries = {registration.id: entry for registration, entry in rows}
    workspace_id = await session.scalar(sa.select(Tournament.workspace_id).where(Tournament.id == tournament_id))
    form = await session.scalar(sa.select(RegistrationForm).where(RegistrationForm.tournament_id == tournament_id))
    team_scope = getattr(form, "subscription_scope", None) or "player"
    rosters = await roster_engine.resolve(
        session, registrations, workspace_id=workspace_id, tournament_id=tournament_id, entries=entries
    )
    members_by_team: dict[int, list[Registration]] = {}
    for registration in registrations:
        members_by_team.setdefault(registration.registration_team_id or 0, []).append(registration)

    # The captain is identified by a player id, not a battle tag, so the seam does
    # not have to resolve a tag that may not exist.
    captain_registration_ids = [team.captain_registration_id for team in teams if team.captain_registration_id]
    captain_player_by_registration: dict[int, int] = {}
    if captain_registration_ids:
        rows = (
            await session.execute(
                sa.select(Registration.id, WorkspaceMember.player_id)
                .join(WorkspaceMember, WorkspaceMember.id == Registration.workspace_member_id)
                .where(Registration.id.in_(captain_registration_ids))
            )
        ).all()
        captain_player_by_registration = dict(rows)

    for team in teams:
        if (getattr(team, "admission", None) or "pending") == "waitlisted":
            payload.skipped.append(SkippedTeam(team_id=team.id, name=team.name, code="team_waitlisted"))
            continue
        if team.status != _EXPORTABLE_STATUS:
            payload.skipped.append(SkippedTeam(team_id=team.id, name=team.name, code="team_incomplete"))
            continue
        team_members = members_by_team.get(team.id, [])
        if not team_members:
            payload.skipped.append(SkippedTeam(team_id=team.id, name=team.name, code="team_empty"))
            continue
        if team_scope == SUBSCRIPTION_SCOPE_TEAM and not team_subscription_is_current(team):
            payload.skipped.append(SkippedTeam(team_id=team.id, name=team.name, code="team_subscription_uncovered"))
            continue

        members: list[MaterializationMember] = []
        for registration in team_members:
            roster = rosters[registration.id]
            role = _slot_role(registration.team_slot_code, shape)
            members.append(
                MaterializationMember(
                    name=_member_name(roster),
                    # ``None`` for a role this player has no resolved rank on: an unranked roster row.
                    rank=roster.rank_on(role),
                    slot_code=registration.team_slot_code,
                    sub_role=_sub_role_for(roster, role),
                    handle=roster.handle,
                    workspace_member_id=registration.workspace_member_id,
                    is_substitute=bool(entries[registration.id].is_substitute),
                    non_rated_roles=tuple(
                        entry.catalog_role
                        for entry in registration.roles
                        if entry.is_active and not entry.catalog_role.dimension.rated
                    ),
                )
            )

        payload.teams.append(
            MaterializationTeam(
                # The registered name IS the balancer name here: there is no
                # captain tag standing in for it. ``create_team`` rejects "#" in a
                # team name precisely because the seam splits on it to derive
                # ``Team.name``.
                balancer_name=team.name,
                members=tuple(members),
                captain_player_id=(
                    captain_player_by_registration.get(team.captain_registration_id)
                    if team.captain_registration_id
                    else None
                ),
            )
        )
        payload.source_teams.append(team)
        if team.exported_team_id is not None:
            payload.prior_team_ids.append(team.exported_team_id)

    return payload

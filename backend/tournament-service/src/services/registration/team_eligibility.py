"""I/O for team eligibility — ranks, identity keys, Discord membership.

The pure rules live in ``shared.domain.team_eligibility``. This module gathers
the facts those rules need. Discord membership goes through ``DiscordClient``
(an RPC to discord-service), the same door the subscription resolver uses. A bot
that cannot be asked means fail-closed (``unreachable``), matching the flag's
"must be in the guild" reading.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.social import SocialProvider
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import FLEX_SLOT_CODE
from shared.domain.team_eligibility import (
    EligibilityIssue,
    StarterRank,
    evaluate_discord_guild,
    evaluate_rank_rules,
    evaluate_unique_identity,
)
from shared.services.discord_client import DiscordClient
from shared.services.discord_errors import DiscordError, MemberNotFound
from shared.services.roster import RosterEngine, registration_load_options, roster_engine

__all__ = ("TeamEligibilityService", "team_eligibility")

_SLOT_RELEASING = frozenset({"withdrawn", "rejected"})


def _slot_role(slot_code: str | None, shape: Any) -> str | None:
    if not getattr(shape, "has_role_slots", False) or slot_code is None or slot_code == FLEX_SLOT_CODE:
        return None
    return slot_code


def _identity_keys(registration: models.Registration, discord_ids: Sequence[str]) -> set[str]:
    keys: set[str] = set()
    nick = next(
        (
            identity.handle_normalized
            for identity in registration.identities
            if identity.provider == SocialProvider.DISCORD and identity.handle_normalized
        ),
        "",
    )
    if nick:
        keys.add(f"discord_handle:{nick}")
    for snowflake in discord_ids:
        if snowflake:
            keys.add(f"discord_id:{snowflake}")
    return keys


async def _discord_ids_by_registration(
    session: AsyncSession,
    registrations: Sequence[models.Registration],
) -> dict[int, list[str]]:
    member_ids = [r.workspace_member_id for r in registrations if r.workspace_member_id]
    if not member_ids:
        return {r.id: [] for r in registrations}
    rows = (
        await session.execute(
            sa.select(
                models.WorkspaceMember.id,
                models.SocialAccount.provider_user_id,
                models.SocialAccount.is_verified,
            )
            .select_from(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .join(models.SocialAccount, models.SocialAccount.user_id == models.User.id)
            .where(
                models.WorkspaceMember.id.in_(member_ids),
                models.SocialAccount.provider == SocialProvider.DISCORD,
                models.SocialAccount.provider_user_id.is_not(None),
            )
        )
    ).all()
    by_member: dict[int, list[str]] = {}
    for member_id, snowflake, verified in rows:
        if not snowflake:
            continue
        if not verified:
            continue
        by_member.setdefault(member_id, []).append(str(snowflake))
    return {r.id: by_member.get(r.workspace_member_id or 0, []) for r in registrations}


async def _identity_keys_by_team(session: AsyncSession, *, tournament_id: int) -> dict[int, set[str]]:
    """Every live team member's identity keys in the tournament, grouped by team."""
    members = list(
        await session.scalars(
            sa.select(models.Registration)
            .where(
                models.Registration.tournament_id == tournament_id,
                models.Registration.registration_team_id.is_not(None),
                models.Registration.deleted_at.is_(None),
                models.Registration.status.notin_(_SLOT_RELEASING),
            )
            # ``_identity_keys`` reads the Discord handle off the identity rows,
            # which are never lazy-loadable in async code.
            .options(selectinload(models.Registration.identities))
        )
    )
    discord_ids = await _discord_ids_by_registration(session, members)
    by_team: dict[int, set[str]] = {}
    for registration in members:
        by_team.setdefault(registration.registration_team_id, set()).update(
            _identity_keys(registration, discord_ids.get(registration.id, []))
        )
    return by_team


def _starter_ranks(
    members: Sequence[models.Registration],
    rosters: dict[int, PlayerRoster],
    shape: Any,
) -> list[StarterRank]:
    starters: list[StarterRank] = []
    for registration in members:
        if registration.is_substitute:
            continue
        roster = rosters.get(registration.id)
        if roster is None:
            starters.append(StarterRank(registration.id, None))
            continue
        role = _slot_role(registration.team_slot_code, shape)
        starters.append(StarterRank(registration.id, roster.rank_on(role)))
    return starters


async def _discord_signals(
    members: Sequence[models.Registration],
    discord_ids: dict[int, list[str]],
    *,
    guild_id: str | None,
    discord: DiscordClient,
) -> dict[int, str | None]:
    guild_id = (guild_id or "").strip()
    if not guild_id:
        return {r.id: None for r in members}

    # One batch to discord-service; the per-member reads below hit its memo.
    try:
        await discord.prefetch(guild_id, [snowflake for ids in discord_ids.values() for snowflake in ids])
    except DiscordError:
        return {r.id: "unreachable" if discord_ids.get(r.id) else "not_linked" for r in members}

    signals: dict[int, str | None] = {}
    for registration in members:
        ids = discord_ids.get(registration.id) or []
        if not ids:
            signals[registration.id] = "not_linked"
            continue
        signal = "not_member"
        for snowflake in ids:
            try:
                await discord.member_roles(guild_id, snowflake)
            except MemberNotFound:
                continue
            except DiscordError:
                signal = "unreachable"
                break
            signal = "member"
            break
        signals[registration.id] = signal
    return signals


class TeamEligibilityService:
    def __init__(self, *, rosters: RosterEngine = roster_engine) -> None:
        self.rosters = rosters

    async def evaluate(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        members: Sequence[models.Registration],
        *,
        form: models.RegistrationForm | None,
        shape: Any,
        workspace: models.Workspace | None,
        discord: DiscordClient,
    ) -> list[EligibilityIssue]:
        """All configured team rules for this roster. Empty when every rule is off."""
        issues = await self.evaluate_many(
            session, [(team, members)], form=form, shape=shape, workspace=workspace, discord=discord
        )
        return issues[team.id]

    async def evaluate_many(
        self,
        session: AsyncSession,
        rosters: Sequence[tuple[models.RegistrationTeam, Sequence[models.Registration]]],
        *,
        form: models.RegistrationForm | None,
        shape: Any,
        workspace: models.Workspace | None,
        discord: DiscordClient,
    ) -> dict[int, list[EligibilityIssue]]:
        """:meth:`evaluate` for several teams of ONE tournament: every read, the rank
        resolve and the Discord batch happen once, not once per team."""
        issues: dict[int, list[EligibilityIssue]] = {team.id: [] for team, _members in rosters}
        if form is None or not rosters:
            return issues
        first = rosters[0][0]
        members = [member for _team, roster in rosters for member in roster]

        ranked = (
            form.team_rank_min is not None or form.team_rank_max is not None or form.team_max_rank_spread is not None
        )
        if ranked and members:
            loaded = list(
                await session.scalars(
                    sa.select(models.Registration)
                    .where(models.Registration.id.in_([m.id for m in members]))
                    .options(*registration_load_options())
                )
            )
            resolved = await self.rosters.resolve(
                session, loaded, workspace_id=first.workspace_id, tournament_id=first.tournament_id
            )
            for team, roster in rosters:
                issues[team.id].extend(
                    evaluate_rank_rules(
                        _starter_ranks(roster, resolved, shape),
                        rank_min=form.team_rank_min,
                        rank_max=form.team_rank_max,
                        max_spread=form.team_max_rank_spread,
                    )
                )

        discord_ids = await _discord_ids_by_registration(session, members)
        if form.team_unique_identity:
            keys_by_team = await _identity_keys_by_team(session, tournament_id=first.tournament_id)
            for team, roster in rosters:
                taken = set().union(*(keys for team_id, keys in keys_by_team.items() if team_id != team.id))
                this_keys = {m.id: _identity_keys(m, discord_ids.get(m.id, [])) for m in roster}
                issues[team.id].extend(evaluate_unique_identity(this_keys=this_keys, taken_keys=taken))

        if form.team_require_discord_guild:
            guild_id = getattr(workspace, "discord_guild_id", None) if workspace is not None else None
            signals = await _discord_signals(members, discord_ids, guild_id=guild_id, discord=discord)
            for team, roster in rosters:
                issues[team.id].extend(
                    evaluate_discord_guild({m.id: signals[m.id] for m in roster}, guild_id=guild_id, require=True)
                )

        return issues


team_eligibility = TeamEligibilityService()

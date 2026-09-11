"""I/O for team eligibility — ranks, identity keys, Discord membership.

The pure rules live in ``shared.domain.team_eligibility``. This module gathers
the facts those rules need. Discord membership reuses the same
``GET /guilds/{guild}/members/{user}`` hop the subscription Discord resolver
already makes; there is no second API. No token means fail-closed
(``unreachable``), matching the flag's "must be in the guild" reading.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

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
from shared.services.roster import registration_load_options, roster_engine
from shared.services.subscriptions.providers.discord_role import (
    DiscordForbidden,
    DiscordNotConfigured,
    DiscordUnavailable,
    MemberNotFound,
)

__all__ = ("evaluate_team_eligibility",)

_SLOT_RELEASING = frozenset({"withdrawn", "rejected"})
_DISCORD_API = "https://discord.com/api/v10"


def _slot_role(slot_code: str | None, shape: Any) -> str | None:
    if not getattr(shape, "has_role_slots", False) or slot_code is None or slot_code == FLEX_SLOT_CODE:
        return None
    return slot_code


def _identity_keys(registration: models.BalancerRegistration, discord_ids: Sequence[str]) -> set[str]:
    keys: set[str] = set()
    nick = (registration.discord_nick or "").strip().casefold()
    if nick:
        keys.add(f"discord_nick:{nick}")
    for snowflake in discord_ids:
        if snowflake:
            keys.add(f"discord_id:{snowflake}")
    return keys


async def _discord_ids_by_registration(
    session: AsyncSession,
    registrations: Sequence[models.BalancerRegistration],
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


async def _taken_identity_keys(
    session: AsyncSession,
    *,
    tournament_id: int,
    exclude_team_id: int,
) -> set[str]:
    others = list(
        await session.scalars(
            sa.select(models.BalancerRegistration).where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.registration_team_id.is_not(None),
                models.BalancerRegistration.registration_team_id != exclude_team_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.status.notin_(_SLOT_RELEASING),
            )
        )
    )
    discord_ids = await _discord_ids_by_registration(session, others)
    taken: set[str] = set()
    for registration in others:
        taken.update(_identity_keys(registration, discord_ids.get(registration.id, [])))
    return taken


def _starter_ranks(
    members: Sequence[models.BalancerRegistration],
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
    members: Sequence[models.BalancerRegistration],
    discord_ids: dict[int, list[str]],
    *,
    guild_id: str | None,
    bot_token: str | None,
) -> dict[int, str | None]:
    if not (guild_id or "").strip():
        return {r.id: None for r in members}

    async def probe(snowflake: str) -> str:
        if not bot_token:
            raise DiscordNotConfigured("discord bot token is not configured")
        headers = {"Authorization": f"Bot {bot_token}"}
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
                response = await client.get(f"{_DISCORD_API}/guilds/{guild_id}/members/{snowflake}")
        except httpx.HTTPError as exc:
            raise DiscordUnavailable(str(exc)) from exc
        if response.status_code == 404:
            raise MemberNotFound("member not found")
        if response.status_code in (401, 403):
            raise DiscordForbidden(f"status {response.status_code}")
        if response.status_code != 200:
            raise DiscordUnavailable(f"status {response.status_code}")
        return "member"

    signals: dict[int, str | None] = {}
    for registration in members:
        ids = discord_ids.get(registration.id) or []
        if not ids:
            signals[registration.id] = "not_linked"
            continue
        if not bot_token:
            signals[registration.id] = "unreachable"
            continue
        found = False
        unreachable = False
        for snowflake in ids:
            try:
                await probe(snowflake)
                found = True
                break
            except MemberNotFound:
                continue
            except (DiscordNotConfigured, DiscordForbidden, DiscordUnavailable):
                unreachable = True
                break
        if found:
            signals[registration.id] = "member"
        elif unreachable:
            signals[registration.id] = "unreachable"
        else:
            signals[registration.id] = "not_member"
    return signals


async def evaluate_team_eligibility(
    session: AsyncSession,
    team: models.BalancerRegistrationTeam,
    members: Sequence[models.BalancerRegistration],
    *,
    form: models.BalancerRegistrationForm | None,
    shape: Any,
    workspace: models.Workspace | None,
    bot_token: str | None,
) -> list[EligibilityIssue]:
    """All configured team rules for this roster. Empty when every rule is off."""
    if form is None:
        return []

    issues: list[EligibilityIssue] = []
    ranked = form.team_rank_min is not None or form.team_rank_max is not None or form.team_max_rank_spread is not None
    if ranked and members:
        loaded = list(
            await session.scalars(
                sa.select(models.BalancerRegistration)
                .where(models.BalancerRegistration.id.in_([m.id for m in members]))
                .options(*registration_load_options())
            )
        )
        rosters = await roster_engine.resolve(
            session, loaded, workspace_id=team.workspace_id, tournament_id=team.tournament_id
        )
        issues.extend(
            evaluate_rank_rules(
                _starter_ranks(members, rosters, shape),
                rank_min=form.team_rank_min,
                rank_max=form.team_rank_max,
                max_spread=form.team_max_rank_spread,
            )
        )

    discord_ids = await _discord_ids_by_registration(session, list(members))
    if form.team_unique_identity:
        this_keys = {m.id: _identity_keys(m, discord_ids.get(m.id, [])) for m in members}
        taken = await _taken_identity_keys(session, tournament_id=team.tournament_id, exclude_team_id=team.id)
        issues.extend(evaluate_unique_identity(this_keys=this_keys, taken_keys=taken))

    if form.team_require_discord_guild:
        guild_id = getattr(workspace, "discord_guild_id", None) if workspace is not None else None
        signals = await _discord_signals(list(members), discord_ids, guild_id=guild_id, bot_token=bot_token)
        issues.extend(evaluate_discord_guild(signals, guild_id=guild_id, require=True))

    return issues

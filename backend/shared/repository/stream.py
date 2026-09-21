"""Read-only data access for stream-svc's Twitch poll targets.

Every column here belongs to ``tournament.*``, ``balancer.*`` or ``players.*`` —
schemas stream-svc owns no table in and writes to none of
(``backend/docs/tournament-service-write-path-inventory.md``). It lives in
``shared`` rather than as a service-local query module because of that: the
tables are shared, so the queries reading them belong next to the other shared
repositories, not duplicated wherever a service happens to need them.

**The visibility JOIN in ``list_verified_channels`` is a privacy control, not a
filter.** A player's Twitch account is public only when a
``social_account_visibility`` row with ``workspace_id IS NULL`` exists (that is
what ``visible_only`` means everywhere else —
``backend/app-service/src/services/user/flows.py``). It is enforced in the
``SELECT`` rather than in a serializer on purpose: a serializer-level check is
one new code path away from being forgotten, and forgetting it publishes a
channel a player deliberately hid from their profile.

Two consented channel sources, deliberately no third:

- **self-declared** — the registrant's ``identity_twitch`` answer (a
  ``registration_identity`` row) behind ``stream_pov``, the
  per-tournament "yes, show my POV" checkbox players already tick;
- **verified** — an OAuth-proven ``social_account`` that is globally visible.

Verified wins a login collision (resolved by the caller): it carries
``provider_user_id``, which survives a channel rename, and a typo'd
self-declared nick must never shadow the proven one.

``list_self_declared_channels``/``list_verified_channels`` and
``list_roster`` all key their output on ``tournament_id``/``user_id`` so a
caller can batch every active tournament into ONE pair of queries instead of
one pair per tournament (see ``stream-service/src/services/targets.py``).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any, NamedTuple

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.social import SocialProvider

__all__ = (
    "SelfDeclaredChannelRow",
    "StreamRosterRow",
    "StreamTargetRepository",
    "TournamentPollTarget",
    "VerifiedChannelRow",
)


class TournamentPollTarget(NamedTuple):
    """A tournament worth polling.

    ``is_hidden`` travels with it because the poller must treat it differently at
    exactly one point — it still polls and still writes Redis, but it must not
    publish to the public ``tournament:{id}:streams`` topic, or an anonymous
    subscriber learns a preview tournament exists.
    """

    tournament_id: int
    workspace_id: int
    is_hidden: bool


class SelfDeclaredChannelRow(NamedTuple):
    """One registrant's self-declared Twitch channel.

    ``twitch_login`` is the ``identity_twitch`` answer verbatim, and never
    ``NULL``: it comes from a ``registration_identity`` row, whose ``handle``
    is NOT NULL, so "no answer" is an absent row rather than an empty one.
    """

    tournament_id: int
    player_id: int
    twitch_login: str


class VerifiedChannelRow(NamedTuple):
    tournament_id: int
    user_id: int
    username: str | None
    username_normalized: str | None
    provider_user_id: str | None


class StreamRosterRow(NamedTuple):
    """One user's name/avatar/team for the batched stream-participant lookup.

    ``roster_id``/``team_id`` are ``None`` in the normal pre-draft state, not an
    error. ``stream_visible`` rides along so the caller can apply the owner's
    veto without a second round-trip.

    ``rosters_formed`` is a property of the TOURNAMENT, not of the row: it is the
    same value on every row and rides along for the same reason ``stream_visible``
    does. It is what lets the caller tell "this player has no team because the
    draft has not happened" from "this player has no team while everyone else
    does" — the first serves, the second is filtered out.
    """

    user_id: int
    name: str
    avatar_url: str | None
    stream_visible: bool
    roster_id: int | None
    is_substitution: bool
    team_id: int | None
    team_name: str | None
    rosters_formed: bool


class StreamTargetRepository:
    """Query facade over ``tournament.*``/``balancer.*``/``players.*`` for the
    Twitch poll target set. Not a ``BaseRepository[Model]``: every method here
    joins several tables and maps to a purpose-built row, not one mapped model.
    """

    async def list_active_tournaments(
        self,
        session: AsyncSession,
        statuses: Sequence[enums.TournamentStatus],
    ) -> Sequence[TournamentPollTarget]:
        """Tournaments in any of ``statuses``, id ascending.

        Only three columns are loaded (not the full ``Tournament`` row): this
        runs on a 30s heartbeat and the poller needs nothing else.
        """
        stmt = (
            sa.select(
                models.Tournament.id,
                models.Tournament.workspace_id,
                models.Tournament.is_hidden,
            )
            .where(models.Tournament.status.in_(statuses))
            .order_by(models.Tournament.id)
        )
        rows = (await session.execute(stmt)).all()
        return [
            TournamentPollTarget(tournament_id=int(tid), workspace_id=int(workspace_id), is_hidden=bool(is_hidden))
            for tid, workspace_id, is_hidden in rows
        ]

    @staticmethod
    def _approved_registration_filters(tournament_ids: Sequence[int]) -> list[Any]:
        """The "this player is actually in one of these tournaments" predicate,
        shared by both channel sources so a change to what counts as
        participation cannot drift between them."""
        registration = models.BalancerRegistration
        return [
            registration.tournament_id.in_(tournament_ids),
            registration.deleted_at.is_(None),
            registration.status == "approved",
        ]

    @staticmethod
    def _stream_veto_filters() -> list[Any]:
        """The owner's "do not broadcast me" veto, shared by both sources for the
        same reason ``_approved_registration_filters`` is: a veto honoured by one
        of the two queries and not the other is not a veto at all.

        Outranks both opt-ins. Requires ``models.User`` to be joined by the
        caller. ``is_(True)`` (not ``isnot(False)``) because the column is NOT
        NULL, so the positive form is equivalent and reads like the flag it tests.
        """
        return [models.User.stream_visible.is_(True)]

    async def list_self_declared_channels(
        self,
        session: AsyncSession,
        tournament_ids: Sequence[int],
    ) -> Sequence[SelfDeclaredChannelRow]:
        if not tournament_ids:
            return []
        registration = models.BalancerRegistration
        identity = models.BalancerRegistrationIdentity
        member = models.WorkspaceMember
        user = models.User
        stmt = (
            sa.select(registration.tournament_id, member.player_id, identity.handle)
            .select_from(registration)
            # The Twitch answer is one row of the registration's identity set;
            # inner-joined on the provider so a registration that answered
            # nothing for Twitch simply has no channel to declare.
            .join(
                identity,
                sa.and_(
                    identity.registration_id == registration.id,
                    identity.provider == SocialProvider.TWITCH,
                ),
            )
            .join(member, registration.workspace_member_id == member.id)
            # PRIVACY: joined only to reach ``stream_visible``. Inner, so a player
            # row that vanished cannot smuggle a channel through on the
            # registration alone.
            .join(user, member.player_id == user.id)
            .where(
                *self._approved_registration_filters(tournament_ids),
                *self._stream_veto_filters(),
                registration.stream_pov.is_(True),
                member.player_id.isnot(None),
            )
            .distinct()
        )
        rows = (await session.execute(stmt)).all()
        return [
            SelfDeclaredChannelRow(tournament_id=int(tid), player_id=int(player_id), twitch_login=login)
            for tid, player_id, login in rows
        ]

    async def list_verified_channels(
        self,
        session: AsyncSession,
        tournament_ids: Sequence[int],
    ) -> Sequence[VerifiedChannelRow]:
        if not tournament_ids:
            return []
        registration = models.BalancerRegistration
        member = models.WorkspaceMember
        user = models.User
        account = models.SocialAccount
        visibility = models.SocialAccountVisibility
        stmt = (
            sa.select(
                registration.tournament_id,
                user.id,
                account.username,
                account.username_normalized,
                account.provider_user_id,
            )
            .select_from(registration)
            .join(member, registration.workspace_member_id == member.id)
            .join(user, member.player_id == user.id)
            .join(account, account.user_id == user.id)
            # PRIVACY: an inner join on the GLOBAL visibility scope. Dropping it,
            # or relaxing it to `workspace_id == tournament workspace`, publishes
            # accounts the player hid from their public profile.
            .join(
                visibility,
                sa.and_(visibility.account_id == account.id, visibility.workspace_id.is_(None)),
            )
            .where(
                *self._approved_registration_filters(tournament_ids),
                *self._stream_veto_filters(),
                account.provider == SocialProvider.TWITCH,
                account.is_verified.is_(True),
            )
            .distinct()
        )
        rows = (await session.execute(stmt)).all()
        return [
            VerifiedChannelRow(
                tournament_id=int(tid),
                user_id=int(user_id),
                username=username,
                username_normalized=username_normalized,
                provider_user_id=str(provider_user_id) if provider_user_id else None,
            )
            for tid, user_id, username, username_normalized, provider_user_id in rows
        ]

    async def list_roster(
        self,
        session: AsyncSession,
        tournament_id: int,
        user_ids: Collection[int],
    ) -> Sequence[StreamRosterRow]:
        """Name, avatar, team and the ``stream_visible`` veto for every user in
        ``user_ids``, in ONE query.

        The team rides along as a LEFT JOIN rather than a second batch — it hangs
        off rows this query already fetches, so one round-trip covers both and
        there is no second statement to keep in step with the first. The
        tournament-wide ``rosters_formed`` flag rides along for the same reason:
        as an uncorrelated ``EXISTS`` it is one InitPlan, not a second round-trip
        on a public, cacheable read.

        The join walks the anchor the roster actually uses. A caller's user id is
        a ``players.user.id``, and ``tournament.player`` no longer carries one
        (``user_id`` was dropped in iwrefac07), so the only path to a roster row
        is through ``workspace_member``.
        """
        if not user_ids:
            return []
        user = models.User
        member = models.WorkspaceMember
        player = models.Player
        team = models.Team
        stmt = (
            sa.select(
                user.id,
                user.name,
                user.avatar_url,
                user.stream_visible,
                player.id.label("roster_id"),
                player.is_substitution,
                team.id.label("team_id"),
                team.name.label("team_name"),
                # Uncorrelated on purpose: "does this tournament have rosters at
                # all", not "does this user have one". ``Player.team_id`` is NOT
                # NULL, so a roster row always carries a team and the existence
                # of any row is exactly "the teams are formed".
                sa.exists().where(models.Player.tournament_id == tournament_id).label("rosters_formed"),
            )
            .select_from(user)
            .outerjoin(member, member.player_id == user.id)
            .outerjoin(player, sa.and_(player.workspace_member_id == member.id, player.tournament_id == tournament_id))
            .outerjoin(team, team.id == player.team_id)
            .where(user.id.in_(user_ids))
        )
        rows = (await session.execute(stmt)).all()
        return [
            StreamRosterRow(
                user_id=int(row.id),
                name=row.name,
                avatar_url=row.avatar_url,
                stream_visible=row.stream_visible,
                roster_id=None if row.roster_id is None else int(row.roster_id),
                is_substitution=bool(row.is_substitution),
                team_id=None if row.team_id is None else int(row.team_id),
                team_name=row.team_name,
                rosters_formed=bool(row.rosters_formed),
            )
            for row in rows
        ]

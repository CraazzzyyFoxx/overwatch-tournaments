"""Issuing and managing invites: offer a slot, extend or revoke an offer, and the
cumulative invite cap with its history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.domain.invite_token import generate_invite_token
from shared.services.notifications import notify
from src.schemas.registration_team import RegistrationTeamInviteHistoryEntry, RegistrationTeamInviteHistoryResponse
from src.services.registration.team_rate_limits import TEAM_INVITE_TOTAL_CAP, assert_invite_attempt_allowed
from src.services.registration.teams._core import TeamServiceBase
from src.services.registration.teams._shared import (
    _SLOT_RELEASING_STATUSES,
    DEFAULT_INVITE_TTL,
    INVITE_PENDING,
    _check_slot,
    _diagnose_dead_invite,
    _fail,
    _withdraw_invite,
)


class InvitesMixin(TeamServiceBase):
    """The issuing side of an invite: captain, managers and organizers."""

    async def _resolve_invite_target(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        registration_id: int,
    ) -> int:
        """The account behind a targeted invite's registration.

        An invite binds to an IDENTITY, not to a registration row: the invitee may
        withdraw and resubmit before answering, and `accept_invite` attaches whatever
        live registration they have at that moment. Binding to the row would strand the
        offer on a dead one.

        Every rejection here is a distinct code because each has a different recourse:
        picked someone from another tournament (impossible from the UI, so a real bug),
        picked someone who joined a team while the dialog was open (pick again), or
        picked a row with no account behind it (an imported player who never signed in —
        only a link invite can reach them).
        """
        registration = await session.scalar(
            self.registration_repo.select()
            .where(
                models.Registration.id == registration_id,
                models.Registration.deleted_at.is_(None),
            )
            .options(selectinload(models.Registration.workspace_member))
        )
        if registration is None or registration.tournament_id != tournament_id:
            # Deliberately 404 rather than 403: confirming that a registration exists
            # elsewhere would answer a question the caller has no business asking.
            raise _fail(404, "registration_not_found", "That registration is not in this tournament")
        if registration.registration_team_id is not None or registration.status in _SLOT_RELEASING_STATUSES:
            # The free-agent list is a snapshot; someone can be recruited between the
            # captain opening the picker and pressing invite.
            raise _fail(409, "player_not_free", "That player is no longer available")

        member = registration.workspace_member
        auth_user_id = (
            await session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == member.player_id))
            if member is not None
            else None
        )
        if auth_user_id is None:
            raise _fail(409, "player_has_no_account", "That player has no site account; send them a link instead")
        return auth_user_id

    async def invite_member(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        slot_code: str,
        is_substitute: bool = False,
        target_registration_id: int | None = None,
        ttl: timedelta | None = DEFAULT_INVITE_TTL,
    ) -> tuple[models.RegistrationTeamInvite, str | None]:
        """Offer one roster slot. Returns the invite and, for a link invite, the raw
        token — which is shown exactly once and never stored.

        Two addressing modes on one entity. ``target_registration_id`` is
        an in-app offer to a free agent already in this tournament; without it the
        invite is a shareable link for someone who has no account yet.

        A targeted invite gets NO token. That is the point: nothing to paste, nothing
        to leak, nothing to forward to the wrong person. Its recipient learns of it from
        their own registration card.
        """
        # Metered BEFORE the row lock: a limiter behind the lock would let a flood
        # serialize on the team row and hold it, turning the throttle into a
        # lock-contention amplifier.
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await assert_invite_attempt_allowed(tournament_id=team.tournament_id, auth_user_id=auth_user.id)

        team = await self._lock_team(session, team_id)
        await self._assert_staff_editable(session, team, auth_user)
        tournament = await self._assert_registration_open(session, team.tournament_id)

        # The slot reservation caps *concurrent* pending invites, but an
        # invite -> revoke -> invite loop stays inside every slot rule. This cumulative
        # ceiling counts every invite ever created for the team, so the loop ends.
        issued = await self.count_invites_against_cap(session, team)
        if issued >= TEAM_INVITE_TOTAL_CAP:
            raise _fail(
                409,
                "invite_cap_reached",
                "This team has issued too many invites; revoke an outstanding one or ask an organizer to reset the cap",
            )

        shape = await self._resolve_shape(session, tournament)
        occupancy = await self._occupancy(
            session, team, shape, max_substitutes=await self._max_substitutes(session, team.tournament_id)
        )
        # ``offering=True``: a pending invite reserves its slot, so a captain cannot
        # hold ten open offers for one place.
        _check_slot(occupancy, slot_code, is_substitute=is_substitute, offering=True)

        raw_token: str | None = None
        token_hash: str | None = None
        target_auth_user_id: int | None = None
        if target_registration_id is None:
            raw_token, token_hash = generate_invite_token()
        else:
            # Resolved INSIDE the lock, after the slot check: the freshness of "this
            # player is unattached" and "this slot is open" must be decided under the
            # same lock that the write commits under, or a concurrent acceptance can
            # invalidate one of them between check and insert.
            target_auth_user_id = await self._resolve_invite_target(
                session, tournament_id=team.tournament_id, registration_id=target_registration_id
            )

        invite = await self.invite_repo.create(
            session,
            models.RegistrationTeamInvite(
                team_id=team.id,
                slot_code=slot_code,
                is_substitute=is_substitute,
                target_auth_user_id=target_auth_user_id,
                token_sha256=token_hash,
                expires_at=datetime.now(UTC) + ttl if ttl is not None else None,
                state=INVITE_PENDING,
                invited_by=auth_user.id,
            ),
        )
        if target_auth_user_id is not None:
            # Only the targeted mode has an addressee. A link invite is a bearer
            # credential whose recipient is whoever the captain sends it to --
            # there is no account to write an inbox row for.
            await notify(
                session,
                kind="team_invite.received",
                recipient_auth_user_id=target_auth_user_id,
                source_workspace_id=team.workspace_id,
                actor_auth_user_id=auth_user.id,
                payload={
                    "team_id": team.id,
                    "team_name": team.name,
                    "tournament_id": team.tournament_id,
                    "tournament_name": tournament.name,
                    "slot_code": slot_code,
                    "is_substitute": is_substitute,
                    "invite_id": invite.id,
                },
            )
        await session.commit()
        return invite, raw_token

    async def count_invites_against_cap(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
    ) -> int:
        """How many invites count toward this team's cumulative ceiling.

        One definition, shared by the check that refuses an invite and the number the
        UI shows. Two copies would produce the worst version of this feature: a captain
        told "12 of 60 used" and refused at the same moment, with no way to tell which
        is wrong.

        Every invite ever created counts, not just live ones — that is the whole point
        of a cumulative cap, since an invite -> revoke -> invite loop stays inside every
        slot rule. ``invite_cap_reset_at`` moves the floor rather than zeroing a
        counter, so the rows behind a forgiven cap remain readable.
        """
        conditions: list[sa.ColumnElement[bool]] = [models.RegistrationTeamInvite.team_id == team.id]
        if team.invite_cap_reset_at is not None:
            conditions.append(models.RegistrationTeamInvite.invited_at > team.invite_cap_reset_at)
        return await self.invite_repo.count(session, filters=conditions)

    async def revoke_invite(
        self,
        session: AsyncSession,
        *,
        invite_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """A captain withdraws their own outstanding offer, releasing its slot."""
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        team = await self._lock_team(session, invite.team_id)
        await self._assert_staff(session, team, auth_user)
        _withdraw_invite(invite, by=auth_user, by_organizer=False)
        await session.commit()

    async def revoke_invite_as_organizer(
        self,
        session: AsyncSession,
        *,
        invite_id: int,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """An organizer withdraws an offer from a team they do not captain.

        The caller owns the workspace-permission check; what this owns is the scope
        one: the invite must belong to a team in ``tournament_id``. Without that an
        organizer of any tournament could pass any invite id and act on another
        tournament's roster, because an invite id is global while their permission is
        not.

        Unlike the captain path this does NOT require the team to be mutable. A
        forming-only rule would make the power useless exactly when it is needed — the
        reason to reach in is usually that something is stuck.
        """
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        team = await self._lock_team(session, invite.team_id)
        if team.tournament_id != tournament_id:
            # 404, not 403: confirming the invite exists elsewhere would answer a
            # question this organizer has no permission to ask.
            raise _fail(404, "invite_not_found", "Invite not found")
        _withdraw_invite(invite, by=auth_user, by_organizer=True)
        await session.commit()

    async def list_invite_history(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        tournament_id: int,
    ) -> RegistrationTeamInviteHistoryResponse:
        """Every invite the team ever issued, newest first, plus its cap standing.

        A separate read from ``describe_team`` on purpose. That one returns only LIVE
        pending invites because occupancy depends on them reserving slots; mixing
        terminal rows in would make a declined offer hold a place. This is also why the
        section is collapsed in the UI: nothing pays for it until someone asks.

        The cap counts every invite ever created, so every one must be visible:
        otherwise an invite -> revoke -> invite cycle burns the ceiling with no cause
        on screen, and a DECLINED offer is indistinguishable from a lapsed link —
        different situations with different next moves.

        ``tournament_id`` is the caller's already-authorized tournament (organizer
        permission checked against it, or the captain's own tournament in the public
        handler) — required and checked against the team's own, like
        ``reset_invite_cap``, so a foreign ``team_id`` 404s instead of leaking another
        tournament's invite history and target handles.
        """
        team = await self.team_repo.get(session, team_id)
        if team is None or team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")

        rows = list(await self.invite_repo.list_for_team(session, team_id))
        tags = await self._handles_by_account(
            session,
            tournament_id=team.tournament_id,
            provider=await self._owner_provider(session, team.tournament_id),
            auth_user_ids={r.target_auth_user_id for r in rows if r.target_auth_user_id is not None},
        )
        now = datetime.now(UTC)
        return RegistrationTeamInviteHistoryResponse(
            items=[
                RegistrationTeamInviteHistoryEntry(
                    id=row.id,
                    slot_code=row.slot_code,
                    is_substitute=bool(row.is_substitute),
                    # `expired` is not a stored state: it is a pending row past its
                    # clock. Computed here for the same reason the link preview computes
                    # it — a lapsed offer and a live one are not the same entry, and the
                    # column cannot tell them apart.
                    state="expired"
                    if row.state == INVITE_PENDING and row.expires_at is not None and row.expires_at <= now
                    else row.state,
                    target_handle=tags.get(row.target_auth_user_id),
                    is_link=row.token_sha256 is not None,
                    invited_at=row.invited_at,
                    expires_at=row.expires_at,
                    answered_at=row.accepted_at or row.revoked_at,
                    # Who ended it, when anyone did. A captain revoking their own offer
                    # and an organizer reaching into the roster are the same state and
                    # very different events.
                    revoked_by_organizer=bool(row.revoked_by_organizer),
                )
                for row in rows
            ],
            cap_used=await self.count_invites_against_cap(session, team),
            cap_limit=TEAM_INVITE_TOTAL_CAP,
            cap_reset_at=team.invite_cap_reset_at,
        )

    async def reset_invite_cap(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Forgive a team's cumulative invite count so its captain can invite again.

        A watermark, not a counter reset: the cap is a COUNT over every invite ever
        created, and clearing it by deleting rows would erase the history that explains
        why the cap was hit. The rows stay; the count starts here.
        """
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        team.invite_cap_reset_at = datetime.now(UTC)
        team.invite_cap_reset_by = auth_user.id
        await session.commit()

    async def extend_invite(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        invite_id: int,
        auth_user: models.AuthUser,
        ttl: timedelta | None = None,
        rotate_token: bool = False,
    ) -> tuple[models.RegistrationTeamInvite, str | None]:
        team = await self._lock_team(session, team_id)
        await self._assert_staff_editable(session, team, auth_user)
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None or invite.team_id != team.id:
            raise _fail(404, "invite_not_found", "Invite not found")
        if invite.state != INVITE_PENDING:
            raise _diagnose_dead_invite(invite)
        invite.expires_at = datetime.now(UTC) + (ttl or DEFAULT_INVITE_TTL)
        raw_token: str | None = None
        if rotate_token:
            if invite.token_sha256 is None:
                raise _fail(409, "invite_not_a_link", "Only a link invite can rotate its token")
            raw_token, token_hash = generate_invite_token()
            invite.token_sha256 = token_hash
        await session.commit()
        return invite, raw_token

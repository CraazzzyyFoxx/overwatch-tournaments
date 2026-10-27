"""Invitee flows: preview a link, accept or decline an offer."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.disciplines import identity_provider
from shared.domain.invite_token import hash_invite_token
from shared.domain.team_eligibility import EligibilityIssue
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from src.schemas.registration import RegistrationSubmit
from src.schemas.registration_team import RegistrationTeamInvitePreview
from src.services.admission import AdmissionStage
from src.services.registration.admission import assert_admitted_at
from src.services.registration.service import TeamPlacement
from src.services.registration.team_rate_limits import assert_accept_attempt_allowed
from src.services.registration.teams._core import TeamServiceBase
from src.services.registration.teams._shared import (
    _SLOT_RELEASING_STATUSES,
    INVITE_ACCEPTED,
    INVITE_DECLINED,
    INVITE_PENDING,
    TEAM_FORMING,
    _apply_occupancy_status,
    _assert_mutable,
    _assert_unlocked,
    _check_slot,
    _diagnose_dead_invite,
    _fail,
    _normalize_invite_token,
)


class InviteeMixin(TeamServiceBase):
    """The answering side of an invite."""

    async def _resolve_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        token: str | None,
        invite_id: int | None,
    ) -> models.RegistrationTeamInvite:
        """Find the invite being redeemed, by token or by id.

        Token lookup is by *hash*, which the partial unique index serves as a single
        indexed read — the raw value is never compared against anything stored.

        By id only a TARGETED invite resolves, and only for its addressee. A link
        invite's credential is its token; its id is a sequential key anybody can
        guess, so a link invite asked for by id is ``invite_not_found``.
        """
        if token is not None:
            invite = await self.invite_repo.get_by_token_hash(
                session, hash_invite_token(_normalize_invite_token(token))
            )
        elif invite_id is not None:
            invite = await self.invite_repo.get(session, invite_id)
            if invite is not None and invite.target_auth_user_id is None:
                invite = None
        else:
            raise _fail(400, "invite_reference_required", "An invite id or token is required")
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        # A targeted invite is addressed to one account; a link invite is bearer.
        if invite.target_auth_user_id is not None and invite.target_auth_user_id != auth_user.id:
            raise _fail(403, "invite_not_for_you", "This invite was sent to a different account")
        return invite

    async def preview_invite(self, session: AsyncSession, *, token: str) -> RegistrationTeamInvitePreview:
        """What a link invite shows before anyone signs in.

        Deliberately anonymous: the whole point of a link invite is that it reaches
        someone with no account yet, and asking them to register before telling them
        what they are joining is the wrong order. The token itself is the credential,
        so holding it is the authorization — and this returns strictly the offer (team,
        tournament, slot), never the roster.

        Unmetered by necessity: with no actor there is nothing to key a limiter on. The
        guessing space is a 256-bit token, and flooding is the gateway's anonymous IP
        budget, not this handler's problem.

        A dead or expired invite is NOT an error here. The landing page needs to say
        *why* a link stopped working, so state travels in the payload and only a token
        matching nothing at all is a 404.
        """
        # Not ``get_by_token_hash``: this read needs the team -> tournament eager-load
        # graph for the preview payload, and that method takes no ``options``.
        invite = await session.scalar(
            self.invite_repo.select()
            # See `_normalize_invite_token`'s docstring for why stripping whitespace
            # here is safe: a real token never contains any.
            .where(models.RegistrationTeamInvite.token_sha256 == hash_invite_token(_normalize_invite_token(token)))
            .options(selectinload(models.RegistrationTeamInvite.team).selectinload(models.RegistrationTeam.tournament))
        )
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")

        team = invite.team
        # Expiry is computed here rather than client-side: the clock this compares
        # against is the one the guarded UPDATE in `accept_invite` uses, not the
        # visitor's. A link that looks live but rejects on submit is the worse bug.
        live = invite.state == INVITE_PENDING and (invite.expires_at is None or invite.expires_at > datetime.now(UTC))
        return RegistrationTeamInvitePreview(
            tournament_id=team.tournament_id,
            tournament_name=team.tournament.name,
            workspace_id=team.workspace_id,
            discipline=team.tournament.discipline,
            team_id=team.id,
            team_name=team.name,
            slot_code=invite.slot_code,
            is_substitute=invite.is_substitute,
            state=invite.state,
            expires_at=invite.expires_at,
            # A team that already exported, or was disbanded, cannot take anyone —
            # regardless of how healthy the invite row looks.
            is_redeemable=live and team.status == TEAM_FORMING and team.exported_team_id is None,
        )

    async def _notify_invite_answered(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        team_name: str,
        tournament_id: int,
        workspace_id: int,
        captain_registration_id: int | None,
        invite_id: int,
        answer: str,
        responder: models.AuthUser,
        responder_name: str,
    ) -> None:
        """Tell the captain how their offer was answered.

        Nobody to tell is not an error: a team whose captain registration was
        hard-deleted, or a captain who is a shadow player
        (``players.user.auth_user_id IS NULL``). The roster change itself stands,
        it just goes unannounced.

        The recipient is derived from the team's own captain row, never from
        anything the answering account supplied.
        """
        if captain_registration_id is None:
            return
        captain_auth_user_id = await session.scalar(
            sa.select(models.User.auth_user_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
            .join(
                models.Registration,
                models.Registration.workspace_member_id == models.WorkspaceMember.id,
            )
            .where(models.Registration.id == captain_registration_id)
        )
        if captain_auth_user_id is None:
            return
        await notify(
            session,
            kind="team_invite.answered",
            recipient_auth_user_id=int(captain_auth_user_id),
            source_workspace_id=workspace_id,
            actor_auth_user_id=responder.id,
            payload={
                "team_id": team_id,
                "team_name": team_name,
                "tournament_id": tournament_id,
                "invite_id": invite_id,
                "answer": answer,
                "responder_name": responder_name,
            },
        )

    async def accept_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        body: RegistrationSubmit | None,
        token: str | None = None,
        invite_id: int | None = None,
    ) -> tuple[models.RegistrationTeam, int, list[EligibilityIssue]]:
        """Redeem an invite: take the offered slot, registering if necessary.

        Returns the team, the id of the registration now holding the slot, and the
        roster's eligibility issues as evaluated under the lock (the caller's team
        read reuses them instead of asking Discord a second time).

        Everything below the team lock happens in one transaction, which is what
        makes the slot check binding. Ordering matters: every rejection that can be
        known up front is raised *before* the invite is consumed, so a failed
        acceptance never burns the invite.

        A redeemer with no registration yet is signing up, so the registration-stage
        admission gate runs first, outside the lock: it asks providers and commits.

        ``body`` is used ONLY when the redeemer has no registration yet. An existing
        one is attached to the team instead — see the comment at the write below.
        """
        # Metered before the token lookup, so a guessing flood is throttled without
        # even reaching the index. Fails OPEN: 256 bits of entropy already make
        # guessing infeasible, so this is defence in depth, not the defence.
        await assert_accept_attempt_allowed(auth_user_id=auth_user.id)

        invite = await self._resolve_invite(session, auth_user=auth_user, token=token, invite_id=invite_id)
        # Advisory, before the admission gate's provider call: a dead link answers with
        # its real reason, for free. ``consume_if_pending`` under the lock stays the
        # authoritative guard against a concurrent redemption.
        if invite.state != INVITE_PENDING or (invite.expires_at is not None and invite.expires_at <= datetime.now(UTC)):
            raise _diagnose_dead_invite(invite)
        tournament_id = await session.scalar(
            sa.select(models.RegistrationTeam.tournament_id).where(
                models.RegistrationTeam.id == invite.team_id,
                models.RegistrationTeam.deleted_at.is_(None),
            )
        )
        gated = False
        if tournament_id is not None and not await self._has_registration(session, tournament_id, auth_user.id):
            await assert_admitted_at(
                session,
                None,
                tournament_id=tournament_id,
                auth_user_id=auth_user.id,
                stage=AdmissionStage.registration,
            )
            gated = True

        team = await self._lock_team(session, invite.team_id)
        _assert_mutable(team)
        _assert_unlocked(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, team.tournament_id)

        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)
        # ``offering=False``: this invite must not block its own acceptance.
        _check_slot(occupancy, invite.slot_code, is_substitute=bool(invite.is_substitute), offering=False)

        # A player who already registered solo is a FREE AGENT, not a duplicate: the
        # partial unique index allows one registration row per player per tournament,
        # so accepting *attaches* the existing row to the team. A second row would be
        # an `already_registered` 409 and, since withdrawal is final, would lock a solo
        # registrant out of every team.
        #
        # The submitted ``body`` is deliberately IGNORED on this path: the player
        # already answered the form, and the invite only decides which slot they
        # occupy. Their recorded roles and ranks stand.
        existing = await self._own_registration(session, team.tournament_id, auth_user.id)
        if existing is not None:
            if existing.status in _SLOT_RELEASING_STATUSES:
                # Withdrawn or rejected. Reviving it here would smuggle a re-entry past
                # the rule that withdrawal is final, which exists because a withdrawal
                # after check-in invalidates a composed roster.
                raise _fail(
                    409,
                    "registration_terminal",
                    "Your registration for this tournament is no longer active",
                )
            # Attach only a row on NO team, decided inside the UPDATE (see
            # ``attach_to_team_if_free``). Before the invite is consumed, so a refusal keeps it.
            if not await self.registration_repo.attach_to_team_if_free(
                session,
                existing.id,
                team_id=team.id,
                slot_code=invite.slot_code,
                is_substitute=bool(invite.is_substitute),
            ):
                raise _fail(409, "already_on_team", "You are already on a team in this tournament")
        elif not gated:
            # The registration seen before the lock is gone, so this accept would sign
            # up without having passed the gate. Rare (a concurrent delete); retrying
            # takes the gated path.
            raise _fail(409, "registration_changed", "Your registration changed; try again")

        # The guard: state and expiry are checked *in the UPDATE*, so two
        # simultaneous redemptions of one link cannot both win. ``consume_if_pending``
        # is that one conditional statement, decided by whether its RETURNING produced
        # a row — never split into a read-then-write.
        consumed = await self.invite_repo.consume_if_pending(
            session,
            invite.id,
            pending_state=INVITE_PENDING,
            accepted_state=INVITE_ACCEPTED,
            accepted_at=datetime.now(UTC),
        )
        if not consumed:
            await session.refresh(invite)
            raise _diagnose_dead_invite(invite)

        registration = existing or await self.registrations.write_public_registration(
            session,
            tournament_id=team.tournament_id,
            auth_user=auth_user,
            body=body,
            team_placement=TeamPlacement(
                registration_team_id=team.id,
                slot_code=invite.slot_code,
                is_substitute=bool(invite.is_substitute),
            ),
            commit=False,
        )
        identity = registration.primary_game_identity(provider=identity_provider(tournament.discipline))
        invite.accepted_registration_id = registration.id
        # Projected, not re-read: the new member's row is already flushed, but
        # computing the post-write status here keeps it inside the lock.
        _apply_occupancy_status(
            team,
            await self._occupancy(session, team, shape, max_substitutes=max_substitutes),
        )
        issues = await self._raise_if_ineligible(session, team, await self._roster_members(session, team.id), shape)
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await self._notify_invite_answered(
            session,
            team_id=team.id,
            team_name=team.name,
            tournament_id=team.tournament_id,
            workspace_id=team.workspace_id,
            captain_registration_id=team.captain_registration_id,
            invite_id=invite.id,
            answer="accepted",
            responder=auth_user,
            responder_name=(identity.handle if identity else None) or auth_user.username,
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            raise _fail(409, "already_registered", "You are already registered for this tournament") from exc
        return team, registration.id, issues

    async def decline_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        token: str | None = None,
        invite_id: int | None = None,
    ) -> None:
        """Refuse an offer, releasing its reserved slot back to the captain."""
        invite = await self._resolve_invite(session, auth_user=auth_user, token=token, invite_id=invite_id)
        if invite.state != INVITE_PENDING:
            raise _diagnose_dead_invite(invite)
        invite.state = INVITE_DECLINED
        # A narrow projection of the team, not a row fetch: the snapshot needs the
        # name the captain reads, the registration that identifies them, and the
        # tenant that owns the resulting notification.
        team_row = (
            await session.execute(
                sa.select(
                    models.RegistrationTeam.name,
                    models.RegistrationTeam.captain_registration_id,
                    models.RegistrationTeam.tournament_id,
                    models.RegistrationTeam.workspace_id,
                ).where(models.RegistrationTeam.id == invite.team_id)
            )
        ).one_or_none()
        if team_row is not None:
            # The game handle the captain picked them by, not the account handle:
            # a targeted invite was chosen off the free-agent list, which shows
            # exactly this. Accepting gets it for free off the registration it
            # just wrote; declining has to read it.
            tags = await self._handles_by_account(
                session,
                tournament_id=team_row.tournament_id,
                provider=await self._owner_provider(session, team_row.tournament_id),
                auth_user_ids={auth_user.id},
            )
            await self._notify_invite_answered(
                session,
                team_id=invite.team_id,
                team_name=team_row.name,
                tournament_id=team_row.tournament_id,
                workspace_id=team_row.workspace_id,
                captain_registration_id=team_row.captain_registration_id,
                invite_id=invite.id,
                answer="declined",
                responder=auth_user,
                responder_name=tags.get(auth_user.id) or auth_user.username,
            )
        await session.commit()

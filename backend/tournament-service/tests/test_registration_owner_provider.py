"""A registration's game identity follows the OWNING tournament's provider (P7 slice 7a).

One registrant types a Riot ID AND a BattleTag. In a League tournament the Riot ID is
their identity everywhere it is read -- the submit response, the free-agent picker, the
team roster, a targeted invite's addressee, the player they are anchored to; in an
Overwatch tournament the same answers read as the BattleTag. Neither game ever shows
the other's handle, and a typed handle cannot take another player's accounts without
ownership proof (``409 game_identity_conflict``).

Real database, like ``test_registration_team_flex_roster.py`` (the occupancy and the
persisted identity are read back out of the tables)::

    uv run pytest tournament-service/tests/test_registration_owner_provider.py -q
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.core.social import SocialProvider, normalize_social_handle  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.domain.team_format import TeamFormat  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    RegistrationForm,
    RegistrationFormVersion,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from shared.services.ontology import project_disciplines  # noqa: E402
from shared.services.social_identity import social_identity_service  # noqa: E402
from shared.services.team_format import save_tournament_format  # noqa: E402
from src.schemas.registration import RegistrationSubmit  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402
from src.services.registration.teams import invitee as invitee_module  # noqa: E402
from src.services.registration.teams import invites as invites_module  # noqa: E402
from src.services.registration.teams import teams_service  # noqa: E402
from tests._lol_grid import seed_lol_grid  # noqa: E402

#: Both game handles are OPTIONAL in the form: which one is required is the owner's business,
#: and that is not what these tests are about.
SCHEMA = FormSchema(
    sections=[
        FormSection(
            key="all",
            fields=[
                FormField(key="identity_riot", kind="builtin"),
                FormField(key="identity_battlenet", kind="builtin"),
            ],
        )
    ]
)

RIOT = SocialProvider.RIOT
BATTLENET = SocialProvider.BATTLENET


async def _seed(session: Any, *, discipline: str) -> SimpleNamespace:
    # The modules' role ontologies reach ``catalog.*`` through ``project_disciplines`` at app-service startup; a
    # fresh test database has none, so the test projects them itself (idempotent) instead of reading ambient state.
    await project_disciplines(session)
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(
        slug=f"ownprov-{suffix}", name=f"Owner provider {suffix}", disciplines_enabled=["overwatch", "lol"]
    )
    session.add(workspace)
    await session.flush()

    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Owner provider {suffix}",
        slug=f"ownprov-{suffix}",
        discipline=discipline,
        status=enums.TournamentStatus.REGISTRATION,
        team_formation="registration",
    )
    session.add(tournament)
    await session.flush()
    if discipline == "lol":
        tournament.division_grid_version_id = await seed_lol_grid(session, workspace_id=workspace.id, suffix=suffix)
        await session.flush()
    await save_tournament_format(
        session, tournament, TeamFormat(discipline=discipline, name="Open three", starter_min=3, starter_max=3)
    )
    now = datetime.now(UTC)
    session.add(
        TournamentPhaseSchedule(
            tournament_id=tournament.id,
            status=enums.TournamentStatus.REGISTRATION,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
        )
    )

    form = RegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id)
    session.add(form)
    await session.flush()
    version = RegistrationFormVersion(form_id=form.id, number=1, schema_json=SCHEMA.model_dump(mode="json"))
    form.current_version = version
    await session.flush()

    users = []
    for index in range(3):
        user = AuthUser(
            email=f"ownprov-{suffix}-{index}@example.com",
            username=f"ownprov_{suffix}_{index}",
            hashed_password="x",
        )
        session.add(user)
        users.append(user)
    await session.flush()
    await session.commit()
    return SimpleNamespace(
        workspace_id=workspace.id,
        tournament_id=tournament.id,
        version_id=version.id,
        captain=users[0],
        agent=users[1],
        auth_user_ids=[user.id for user in users],
    )


async def _drop(session: Any, seeded: SimpleNamespace, *, players: tuple[int, ...] = ()) -> None:
    await session.rollback()
    await session.execute(
        sa.delete(EventOutbox).where(
            sa.or_(
                EventOutbox.payload_json["tournament_id"].as_string() == str(seeded.tournament_id),
                EventOutbox.routing_key == f"cache.invalidated.tournament.{seeded.tournament_id}",
            )
        )
    )
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    # ``players.user`` rows are not workspace-scoped; neither are the auth users.
    await session.execute(sa.delete(models.User).where(models.User.auth_user_id.in_(seeded.auth_user_ids)))
    if players:
        await session.execute(sa.delete(models.User).where(models.User.id.in_(players)))
    await session.execute(sa.delete(AuthUser).where(AuthUser.id.in_(seeded.auth_user_ids)))
    await session.commit()


def _handles(seeded: SimpleNamespace, who: str) -> dict[str, str]:
    tid = seeded.tournament_id
    return {RIOT: f"{who}{tid}#EUW", BATTLENET: f"{who}BN{tid}#1111"}


def _submit(seeded: SimpleNamespace, who: str) -> RegistrationSubmit:
    handles = _handles(seeded, who)
    return RegistrationSubmit(
        form_version_id=seeded.version_id,
        answers={"identity_riot": [handles[RIOT]], "identity_battlenet": [handles[BATTLENET]]},
    )


_OWNERS = [("lol", RIOT), ("overwatch", BATTLENET)]


@pytest.mark.parametrize(("discipline", "provider"), _OWNERS)
def test_every_receiver_names_the_owning_games_handle(db_session, discipline: str, provider: str) -> None:
    """Submit read, free-agent picker, team roster, targeted-invite addressee and the anchored
    player's name all carry the OWNER provider's handle, though both handles were typed."""

    async def _run() -> dict[str, Any]:
        seeded = await _seed(db_session, discipline=discipline)
        try:
            captain_handles = _handles(seeded, "Cap")
            agent_handles = _handles(seeded, "Agent")
            team, captain, _issues = await teams_service.create_team(
                db_session,
                tournament_id=seeded.tournament_id,
                auth_user=seeded.captain,
                name=f"Squad {seeded.tournament_id}",
                slot_code="flex",
                body=_submit(seeded, "Cap"),
            )
            agent_read = await reg_service.registration_service.submit_public_registration(
                db_session, tournament_id=seeded.tournament_id, auth_user=seeded.agent, body=_submit(seeded, "Agent")
            )
            free_agents = await teams_service.list_free_agents(db_session, seeded.tournament_id)
            await teams_service.invite_member(
                db_session,
                team_id=team.id,
                auth_user=seeded.captain,
                slot_code="flex",
                target_registration_id=agent_read.id,
            )
            history = await teams_service.list_invite_history(
                db_session, team_id=team.id, tournament_id=seeded.tournament_id
            )
            described = await teams_service.describe_team(db_session, team)

            registration = (
                await db_session.execute(
                    sa.select(models.Registration)
                    .where(models.Registration.id == captain.id)
                    .options(
                        selectinload(models.Registration.workspace_member).selectinload(models.WorkspaceMember.player)
                    )
                )
            ).scalar_one()
            player = registration.workspace_member.player
            accounts = {
                (account.provider, account.username)
                for account in await social_identity_service.accounts.list_by_user(db_session, player.id)
            }
            return {
                "captain": captain_handles,
                "agent": agent_handles,
                "submit": agent_read.primary_handle,
                "create": captain.primary_game_identity(provider=provider).handle,
                "free_agents": [row.primary_handle for row in free_agents],
                "roster": [member.primary_handle for member in described.members],
                "invite": [entry.target_handle for entry in history.items],
                "player_name": player.name,
                "accounts": accounts,
            }
        finally:
            await _drop(db_session, seeded)

    with (
        patch.object(invites_module, "assert_invite_attempt_allowed", AsyncMock()),
        patch.object(invitee_module, "assert_accept_attempt_allowed", AsyncMock()),
    ):
        got = asyncio.run(_run())

    assert got["create"] == got["captain"][provider]
    assert got["submit"] == got["agent"][provider]
    assert got["free_agents"] == [got["agent"][provider]]
    assert got["roster"] == [got["captain"][provider]]
    assert got["invite"] == [got["agent"][provider]]
    # The new player is named after the owner handle and carries BOTH typed accounts.
    assert got["player_name"] == got["captain"][provider]
    assert got["accounts"] == {(RIOT, got["captain"][RIOT]), (BATTLENET, got["captain"][BATTLENET])}


def test_a_typed_handle_cannot_take_another_players_account(db_session) -> None:
    """A League registrant whose account-owned player does NOT hold the Riot ID verified: the
    shadow player that owns it keeps it, the submission is refused 409, nothing is written."""

    async def _run() -> dict[str, Any]:
        seeded = await _seed(db_session, discipline="lol")
        shadow_id = None
        try:
            riot_id = f"Taken{seeded.tournament_id}#EUW"
            own = models.User(name=f"own-{seeded.tournament_id}", auth_user_id=seeded.captain.id)
            shadow = models.User(name=f"shadow-{seeded.tournament_id}")
            db_session.add_all([own, shadow])
            await db_session.flush()
            shadow_id = shadow.id
            await social_identity_service.upsert(db_session, user_id=shadow.id, provider=RIOT, username=riot_id)
            await db_session.commit()

            with pytest.raises(ApiHTTPException) as refused:
                await reg_service.registration_service.submit_public_registration(
                    db_session,
                    tournament_id=seeded.tournament_id,
                    auth_user=seeded.captain,
                    body=RegistrationSubmit(form_version_id=seeded.version_id, answers={"identity_riot": [riot_id]}),
                )
            await db_session.rollback()

            owner = await social_identity_service.find_by_handle(db_session, provider=RIOT, username=riot_id)
            registrations = await db_session.scalar(
                sa.select(sa.func.count())
                .select_from(models.Registration)
                .where(models.Registration.tournament_id == seeded.tournament_id)
            )
            return {
                "status": refused.value.status_code,
                "code": refused.value.detail[0]["code"],
                "owner": owner.user_id,
                "shadow": shadow_id,
                "registrations": registrations,
                "normalized": normalize_social_handle(RIOT, riot_id),
            }
        finally:
            await _drop(db_session, seeded, players=(shadow_id,) if shadow_id else ())

    got = asyncio.run(_run())

    assert (got["status"], got["code"]) == (409, "game_identity_conflict")
    assert got["owner"] == got["shadow"]
    assert got["registrations"] == 0

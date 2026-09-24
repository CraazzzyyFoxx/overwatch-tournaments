"""Founding and filling a squad on a roster made only of ``flex`` slots.

A battle-royale roster is ``{flex: 3}``: three places, none of which names a
role. That shape reaches ``shared.domain.team_roster._validate_slot`` on every
captain, invite and acceptance, and nothing in the suite had ever driven it end
to end -- the frontend used to hide the "register a team" entry on such a
tournament, so the server side was unreachable and its behaviour unpinned.

This is the contract the UI now depends on: ``flex`` is a slot code like any
other, and a three-flex roster is COMPLETE once the captain and two invitees
hold its three places. It runs against a real database because the occupancy it
asserts is read back out of ``balancer_registration`` rows::

    uv run pytest tournament-service/tests/test_registration_team_flex_roster.py -q

It takes ``db_session`` (``shared.testing``) and SKIPs only when Postgres is
unreachable; it seeds its own workspace and drops it, plus the auth users and
the outbox rows the flows emit, in ``finally``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistrationForm,
    BalancerRegistrationFormVersion,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from src import models  # noqa: E402
from src.schemas.registration import RegistrationSubmit  # noqa: E402
from src.services.registration.teams import TEAM_COMPLETE, TEAM_FORMING, teams_service  # noqa: E402

#: Three places, none of them a role: the squad shape this file exists for.
ALL_FLEX = {"flex": 3}

#: The least a registrant can be asked, so the assertions stay about slots.
SCHEMA = FormSchema(sections=[FormSection(key="all", fields=[FormField(key="battle_tag", kind="builtin", required=True)])])


async def _seed(session: Any) -> SimpleNamespace:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"flexros-{suffix}", name=f"Flex roster {suffix}")
    session.add(workspace)
    await session.flush()

    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Flex roster {suffix}",
        slug=f"flexros-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
        team_formation="registration",
        roster_slots_json=dict(ALL_FLEX),
    )
    session.add(tournament)
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        TournamentPhaseSchedule(
            tournament_id=tournament.id,
            status=enums.TournamentStatus.REGISTRATION,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
        )
    )

    form = BalancerRegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id)
    session.add(form)
    await session.flush()
    version = BalancerRegistrationFormVersion(form_id=form.id, number=1, schema_json=SCHEMA.model_dump(mode="json"))
    form.current_version = version
    await session.flush()

    users = []
    for index in range(3):
        user = AuthUser(
            email=f"flexros-{suffix}-{index}@example.com",
            username=f"flexros_{suffix}_{index}",
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
        members=users[1:],
        auth_user_ids=[user.id for user in users],
    )


async def _drop(session: Any, seeded: SimpleNamespace) -> None:
    await session.rollback()
    # Neither the outbox nor an auth user is workspace-scoped, so the rows the
    # create/invite/accept flows emitted have to be swept by hand.
    await session.execute(
        sa.delete(EventOutbox).where(
            sa.or_(
                EventOutbox.payload_json["tournament_id"].as_string() == str(seeded.tournament_id),
                EventOutbox.routing_key == f"cache.invalidated.tournament.{seeded.tournament_id}",
            )
        )
    )
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    await session.execute(sa.delete(AuthUser).where(AuthUser.id.in_(seeded.auth_user_ids)))
    await session.commit()


def _submit(seeded: SimpleNamespace, battle_tag: str) -> RegistrationSubmit:
    return RegistrationSubmit(form_version_id=seeded.version_id, answers={"battle_tag": battle_tag})


async def _slots_held(session: Any, team_id: int) -> list[str]:
    result = await session.scalars(
        sa.select(models.BalancerRegistration.team_slot_code)
        .where(
            models.BalancerRegistration.registration_team_id == team_id,
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .order_by(models.BalancerRegistration.id)
    )
    return list(result)


def test_a_three_flex_roster_is_founded_and_filled_by_two_invites(db_session) -> None:
    """``flex`` passes the slot gate for all three flows, and the third body
    completes the roster -- there is no role slot left over to keep it forming."""

    async def _run() -> tuple[str, list[str], str, list[str]]:
        seeded = await _seed(db_session)
        try:
            team, _ = await teams_service.create_team(
                db_session,
                tournament_id=seeded.tournament_id,
                auth_user=seeded.captain,
                name=f"Squad {seeded.tournament_id}",
                slot_code="flex",
                body=_submit(seeded, f"Cap{seeded.tournament_id}#1111"),
            )
            after_create = (team.status, await _slots_held(db_session, team.id))

            for index, member in enumerate(seeded.members):
                _, token = await teams_service.invite_member(
                    db_session,
                    team_id=team.id,
                    auth_user=seeded.captain,
                    slot_code="flex",
                )
                assert token is not None
                await teams_service.accept_invite(
                    db_session,
                    auth_user=member,
                    body=_submit(seeded, f"Mate{seeded.tournament_id}#{index}222"),
                    token=token,
                )

            await db_session.refresh(team)
            return (*after_create, team.status, await _slots_held(db_session, team.id))
        finally:
            await _drop(db_session, seeded)

    create_status, create_slots, final_status, final_slots = asyncio.run(_run())

    # One of three places taken: the shape is not satisfied yet.
    assert (create_status, create_slots) == (TEAM_FORMING, ["flex"])
    assert (final_status, final_slots) == (TEAM_COMPLETE, ["flex", "flex", "flex"])

"""Who may join, and what a join may never do — against a real Postgres.

- A link invite redeems by its token only; its sequential id is not a credential.
- Accepting never moves a player who already sits on another team, and a refused
  accept leaves the invite pending.
- A newcomer joining by invite is signing up, so the sign-up admission gate runs;
  a free agent who already registered is not asked again.
- A refusal keeps the fresh verdict and check-log rows it paid a provider for.
- Two writers of one primary game handle are serialized: the second sees the
  first's row and gets 409 instead of both passing the existence check.
- The public team list shows a team's outstanding invites to that team's own
  staff only: never to another captain, a stranger or an anonymous reader.

Real database, like ``test_registration_team_flex_roster.py``::

    uv run pytest tournament-service/tests/test_registration_write_guards_db.py -q
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.core.social import SocialProvider, normalize_social_handle  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection, identity_key  # noqa: E402
from shared.domain.team_format import TeamFormat  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    RegistrationForm,
    RegistrationFormVersion,
)
from shared.models.subscriptions.subscription import (  # noqa: E402
    SubscriptionCheckLog,
    SubscriptionEntitlement,
    SubscriptionProviderConfig,
    WorkspaceSubscriptionRequirement,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from shared.services.subscriptions import SubscriptionVerdict  # noqa: E402
from shared.services.subscriptions.entitlements import SubscriptionResolver  # noqa: E402
from shared.services.subscriptions.wiring import build_log_sink, build_store  # noqa: E402
from shared.services.team_format import save_tournament_format  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402
from src.rpc import _helpers as rpc_helpers  # noqa: E402
from src.rpc import public_rpc  # noqa: E402
from src.schemas.registration import RegistrationSubmit  # noqa: E402
from src.services.admission import AdmissionStage  # noqa: E402
from src.services.registration import admission as admission_module  # noqa: E402
from src.services.registration import teams as teams_module  # noqa: E402
from src.services.registration.service import registration_service  # noqa: E402
from src.services.registration.teams import INVITE_PENDING, teams_service  # noqa: E402
from tests._rpc_fakes import CapturingBroker, make_identity  # noqa: E402

SCHEMA = FormSchema(
    sections=[FormSection(key="all", fields=[FormField(key="identity_battlenet", kind="builtin", required=True)])]
)


class _Refuses:
    """A live provider that answers "not subscribed" for everybody it is asked about."""

    async def resolve_many(self, *, config: dict[str, Any], auth_user_ids: Any) -> dict[int, SubscriptionVerdict]:
        now = datetime.now(UTC)
        verdict = SubscriptionVerdict(
            state="inactive",
            tier_rank=None,
            tier_label=None,
            source="discord_role",
            checked_at=now,
            expires_at=now + timedelta(minutes=15),
            evidence={},
        )
        return dict.fromkeys(auth_user_ids, verdict)


def _refusing_resolver(session: Any, **_: Any) -> SubscriptionResolver:
    return SubscriptionResolver(
        store=build_store(session), strategies={"boosty": _Refuses()}, log_sink=build_log_sink(session)
    )


async def _seed(session: Any, *, require_subscription: bool = False) -> SimpleNamespace:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"wguard-{suffix}", name=f"Write guards {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Write guards {suffix}",
        slug=f"wguard-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
        team_formation="registration",
    )
    session.add(tournament)
    await session.flush()
    await save_tournament_format(
        session, tournament, TeamFormat(discipline="overwatch", name="Open three", starter_min=3, starter_max=3)
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
    form = RegistrationForm(
        tournament_id=tournament.id,
        workspace_id=workspace.id,
        require_subscription=require_subscription,
        subscription_stage=enums.SubscriptionEnforcementStage.registration.value,
    )
    session.add(form)
    await session.flush()
    version = RegistrationFormVersion(form_id=form.id, number=1, schema_json=SCHEMA.model_dump(mode="json"))
    form.current_version = version
    if require_subscription:
        session.add_all(
            [
                SubscriptionProviderConfig(
                    workspace_id=workspace.id,
                    provider="boosty",
                    enabled=True,
                    config_json={"verification_method": "live"},
                ),
                WorkspaceSubscriptionRequirement(
                    workspace_id=workspace.id,
                    name="default",
                    is_default=True,
                    requirement_json={"mode": "all", "requirements": [{"provider": "boosty"}]},
                ),
            ]
        )
    users = [
        AuthUser(
            email=f"wguard-{suffix}-{index}@example.com",
            username=f"wguard_{suffix}_{index}",
            hashed_password="x",
        )
        for index in range(4)
    ]
    session.add_all(users)
    await session.flush()
    await session.commit()
    return SimpleNamespace(
        suffix=suffix,
        workspace_id=workspace.id,
        tournament_id=tournament.id,
        version_id=version.id,
        users=users,
        auth_user_ids=[user.id for user in users],
    )


async def _drop(session: Any, seeded: SimpleNamespace) -> None:
    await session.rollback()
    await session.execute(
        sa.delete(EventOutbox).where(
            sa.or_(
                EventOutbox.payload_json["tournament_id"].as_string() == str(seeded.tournament_id),
                EventOutbox.routing_key == f"cache.invalidated.tournament.{seeded.tournament_id}",
            )
        )
    )
    await session.execute(
        sa.delete(SubscriptionCheckLog).where(SubscriptionCheckLog.workspace_id == seeded.workspace_id)
    )
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    await session.execute(sa.delete(AuthUser).where(AuthUser.id.in_(seeded.auth_user_ids)))
    await session.commit()


def _submit(seeded: SimpleNamespace, who: int) -> RegistrationSubmit:
    # A BattleTag name is 2-12 characters: 8 hex of the run's suffix keeps it unique and valid.
    return RegistrationSubmit(
        form_version_id=seeded.version_id,
        answers={"identity_battlenet": [f"P{seeded.suffix[:8]}{who}#{1000 + who}"]},
    )


async def _found_team(session: Any, seeded: SimpleNamespace, captain: int, name: str) -> Any:
    team, _registration, _issues = await teams_service.create_team(
        session,
        tournament_id=seeded.tournament_id,
        auth_user=seeded.users[captain],
        name=f"{name} {seeded.suffix}",
        slot_code="flex",
        body=_submit(seeded, captain),
    )
    return team


async def _invite_state(session: Any, invite_id: int) -> str:
    return await session.scalar(
        sa.select(models.RegistrationTeamInvite.state).where(models.RegistrationTeamInvite.id == invite_id)
    )


async def _team_of(session: Any, seeded: SimpleNamespace, who: int) -> int | None:
    return await session.scalar(
        sa.select(models.Registration.registration_team_id).where(
            models.Registration.tournament_id == seeded.tournament_id,
            models.Registration.workspace_member.has(
                models.WorkspaceMember.player.has(models.User.auth_user_id == seeded.auth_user_ids[who])
            ),
        )
    )


def _run(body: Any, *, require_subscription: bool = False) -> Any:
    async def _main() -> Any:
        async with _db_sessions() as Session:
            async with Session() as session:
                seeded = await _seed(session, require_subscription=require_subscription)
                try:
                    return await body(Session, session, seeded)
                finally:
                    await _drop(session, seeded)

    with (
        patch.object(teams_module, "assert_invite_attempt_allowed", AsyncMock()),
        patch.object(teams_module, "assert_accept_attempt_allowed", AsyncMock()),
    ):
        return asyncio.run(_main())


def _code(exc: BaseAPIException) -> str | None:
    detail = exc.detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        return first.get("code") if isinstance(first, dict) else getattr(first, "code", None)
    return None


def test_a_link_invite_does_not_redeem_by_its_id() -> None:
    async def body(_Session: Any, session: Any, seeded: SimpleNamespace) -> tuple[Any, ...]:
        team = await _found_team(session, seeded, 0, "Link")
        invite, token = await teams_service.invite_member(
            session, team_id=team.id, auth_user=seeded.users[0], slot_code="flex"
        )
        assert token is not None
        # Plain ids: a rollback expires every instance, and an expired one would lazy-load.
        invite_id = invite.id
        attempts = (
            lambda: teams_service.accept_invite(
                session, auth_user=seeded.users[1], body=_submit(seeded, 1), invite_id=invite_id
            ),
            lambda: teams_service.decline_invite(session, auth_user=seeded.users[1], invite_id=invite_id),
        )
        refused = []
        for attempt in attempts:
            with pytest.raises(BaseAPIException) as caught:
                await attempt()
            await session.rollback()
            refused.append((caught.value.status_code, _code(caught.value)))
        return tuple(refused), await _invite_state(session, invite_id)

    refused, state = _run(body)
    assert refused == ((404, "invite_not_found"), (404, "invite_not_found"))
    assert state == INVITE_PENDING


def test_accepting_never_moves_a_player_off_another_team() -> None:
    async def body(_Session: Any, session: Any, seeded: SimpleNamespace) -> tuple[Any, ...]:
        home = await _found_team(session, seeded, 0, "Home")
        away = await _found_team(session, seeded, 1, "Away")
        invite, token = await teams_service.invite_member(
            session, team_id=away.id, auth_user=seeded.users[1], slot_code="flex"
        )
        # Plain ids: a rollback expires every instance, and an expired one would lazy-load.
        home_id, invite_id = home.id, invite.id
        with pytest.raises(BaseAPIException) as caught:
            await teams_service.accept_invite(session, auth_user=seeded.users[0], body=None, token=token)
        await session.rollback()
        return (
            caught.value.status_code,
            _code(caught.value),
            await _team_of(session, seeded, 0) == home_id,
            await _invite_state(session, invite_id),
        )

    status, code, still_home, state = _run(body)
    assert (status, code) == (409, "already_on_team")
    assert still_home
    assert state == INVITE_PENDING


def test_a_newcomer_is_gated_and_a_free_agent_is_not() -> None:
    async def body(_Session: Any, session: Any, seeded: SimpleNamespace) -> tuple[Any, ...]:
        team = await _found_team(session, seeded, 0, "Gate")
        invite, token = await teams_service.invite_member(
            session, team_id=team.id, auth_user=seeded.users[0], slot_code="flex"
        )
        team_id, invite_id = team.id, invite.id
        with patch.object(admission_module, "subscription_resolver", side_effect=_refusing_resolver):
            with pytest.raises(BaseAPIException) as caught:
                await teams_service.accept_invite(
                    session, auth_user=seeded.users[1], body=_submit(seeded, 1), token=token
                )
            await session.rollback()
            newcomer = (
                caught.value.status_code,
                await _team_of(session, seeded, 1),
                await _invite_state(session, invite_id),
            )

            # Registered solo first (that path's gate lives in its handler), then joins:
            # the refusing provider is never asked, so the accept goes through.
            await registration_service.submit_public_registration(
                session, tournament_id=seeded.tournament_id, auth_user=seeded.users[2], body=_submit(seeded, 2)
            )
            await teams_service.accept_invite(session, auth_user=seeded.users[2], body=None, token=token)
        return newcomer, await _team_of(session, seeded, 2) == team_id

    newcomer, free_agent_joined = _run(body, require_subscription=True)
    assert newcomer == (400, None, INVITE_PENDING)
    assert free_agent_joined


def test_a_dead_invite_answers_its_reason_before_the_admission_gate() -> None:
    """A revoked link costs no provider call and says why it is dead, even for a
    newcomer whose admission would have been refused."""

    async def body(_Session: Any, session: Any, seeded: SimpleNamespace) -> tuple[Any, ...]:
        team = await _found_team(session, seeded, 0, "Dead")
        invite, token = await teams_service.invite_member(
            session, team_id=team.id, auth_user=seeded.users[0], slot_code="flex"
        )
        await teams_service.revoke_invite(session, invite_id=invite.id, auth_user=seeded.users[0])
        resolver = Mock(side_effect=_refusing_resolver)
        with patch.object(admission_module, "subscription_resolver", resolver):
            with pytest.raises(BaseAPIException) as caught:
                await teams_service.accept_invite(
                    session, auth_user=seeded.users[1], body=_submit(seeded, 1), token=token
                )
        await session.rollback()
        return caught.value.status_code, _code(caught.value), resolver.call_count

    status, code, provider_asked = _run(body, require_subscription=True)
    assert (status, code) == (409, "invite_revoked")
    assert provider_asked == 0


def test_a_refusal_keeps_the_verdict_it_paid_for() -> None:
    async def body(Session: Any, session: Any, seeded: SimpleNamespace) -> tuple[Any, ...]:
        subject = seeded.auth_user_ids[3]
        with patch.object(admission_module, "subscription_resolver", side_effect=_refusing_resolver):
            with pytest.raises(BaseAPIException):
                await admission_module.assert_admitted_at(
                    session,
                    None,
                    tournament_id=seeded.tournament_id,
                    auth_user_id=subject,
                    stage=AdmissionStage.registration,
                )
        # What ``_run`` does with a raising handler: the session ends without a commit.
        await session.rollback()
        async with Session() as fresh:
            state = await fresh.scalar(
                sa.select(SubscriptionEntitlement.state).where(
                    SubscriptionEntitlement.workspace_id == seeded.workspace_id,
                    SubscriptionEntitlement.auth_user_id == subject,
                    SubscriptionEntitlement.provider == "boosty",
                )
            )
            logged = await fresh.scalar(
                sa.select(sa.func.count()).where(
                    SubscriptionCheckLog.workspace_id == seeded.workspace_id,
                    SubscriptionCheckLog.auth_user_id == subject,
                )
            )
        return state, logged

    state, logged = _run(body, require_subscription=True)
    assert state == "inactive"
    assert logged == 1


def test_two_writers_of_one_primary_handle_are_serialized() -> None:
    """The guard alone, so nothing else in the write path (a unique player name, a
    role seed) can be what makes the second writer wait."""

    async def body(Session: Any, _session: Any, seeded: SimpleNamespace) -> tuple[Any, ...]:
        tag = f"Dup{seeded.suffix}#1234"
        values = {identity_key(SocialProvider.BATTLENET): [tag]}
        guard = registration_service.ensure_unique_primary_game_handles
        async with Session() as first, Session() as second:
            await guard(first, tournament_id=seeded.tournament_id, values=values)
            first.add(
                models.Registration(
                    tournament_id=seeded.tournament_id,
                    status="pending",
                    submitted_at=datetime.now(UTC),
                    identities=[
                        models.RegistrationIdentity(
                            provider=SocialProvider.BATTLENET,
                            position=0,
                            handle=tag,
                            handle_normalized=normalize_social_handle(SocialProvider.BATTLENET, tag),
                        )
                    ],
                )
            )
            await first.flush()
            contender = asyncio.create_task(guard(second, tournament_id=seeded.tournament_id, values=values))
            await asyncio.sleep(0.5)
            waited = not contender.done()
            await first.commit()
            with pytest.raises(BaseAPIException) as caught:
                await contender
            await second.rollback()
        return waited, caught.value.status_code

    waited, status = _run(body)
    assert waited, "the second writer passed the existence check while the first's row was uncommitted"
    assert status == 409


def test_the_public_team_list_shows_invites_only_to_that_teams_staff() -> None:
    """Through the real ``regteam_list_public`` handler: each captain has one link
    invite out; a reader sees invites only on a team they captain."""

    async def body(Session: Any, session: Any, seeded: SimpleNamespace) -> dict[str, dict[str, int]]:
        teams = {}
        for captain, name in ((0, "Alpha"), (1, "Bravo")):
            team = await _found_team(session, seeded, captain, name)
            await teams_service.invite_member(
                session, team_id=team.id, auth_user=seeded.users[captain], slot_code="flex"
            )
            teams[team.id] = name
        broker = CapturingBroker()
        public_rpc.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        readers = {
            "alpha_captain": seeded.auth_user_ids[0],
            "stranger": seeded.auth_user_ids[2],
            "anonymous": None,
        }
        seen: dict[str, dict[str, int]] = {}
        with patch.object(rpc_helpers.db, "async_session_maker", Session):
            for reader, auth_user_id in readers.items():
                data: dict[str, Any] = {"tournament_id": seeded.tournament_id}
                if auth_user_id is not None:
                    data["identity"] = make_identity(user_id=auth_user_id)
                envelope = await broker.handlers["rpc.tournament.regteam_list_public"](data, None)
                assert envelope["ok"], envelope
                seen[reader] = {teams[item["id"]]: len(item["invites"]) for item in envelope["data"]["items"]}
        return seen

    seen = _run(body)
    assert seen == {
        "alpha_captain": {"Alpha": 1, "Bravo": 0},
        "stranger": {"Alpha": 0, "Bravo": 0},
        "anonymous": {"Alpha": 0, "Bravo": 0},
    }

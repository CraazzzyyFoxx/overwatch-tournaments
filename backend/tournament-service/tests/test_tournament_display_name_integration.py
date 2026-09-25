"""``tournament_display_name`` precedence, on real Postgres.

The name chat shows for somebody inside a tournament must be the handle the
rest of that tournament shows (the registered BattleTag), not whatever handle
their account was created from. Skips when Postgres is unreachable::

    uv run pytest tournament-service/tests/test_tournament_display_name_integration.py -v
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.core.social import SocialProvider  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.social import SocialAccount  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.registration.registration import BalancerRegistration  # noqa: E402
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.services.tournament.display_name import tournament_display_name  # noqa: E402


def test_registered_tag_then_linked_battletag_then_site_name(db_session) -> None:
    async def _run() -> tuple[str, str, str, str]:
        suffix = uuid.uuid4().hex[:12]
        workspace = Workspace(slug=f"dname-{suffix}", name=f"Display name {suffix}")
        db_session.add(workspace)
        await db_session.flush()
        this, other = (
            Tournament(
                workspace_id=workspace.id,
                name=f"{label} {suffix}",
                slug=f"dname-{label}-{suffix}",
                status=enums.TournamentStatus.REGISTRATION,
            )
            for label in ("this", "other")
        )
        db_session.add_all([this, other])
        # Signed up through Discord: the site name is the Discord one.
        player_auth = AuthUser(email=f"p-{suffix}@example.com", username=f"discord_{suffix}")
        staff_auth = AuthUser(email=f"s-{suffix}@example.com", username=f"staff_{suffix}")
        db_session.add_all([player_auth, staff_auth])
        await db_session.flush()
        player = User(name=f"discord_{suffix}", auth_user_id=player_auth.id)
        db_session.add(player)
        await db_session.flush()
        member = WorkspaceMember(workspace_id=workspace.id, player_id=player.id)
        db_session.add_all(
            [
                member,
                SocialAccount(user_id=player.id, provider=SocialProvider.BATTLENET, username=f"Main#{suffix[:4]}"),
            ]
        )
        await db_session.flush()
        db_session.add_all(
            [
                # Registered for THIS tournament on a smurf.
                BalancerRegistration(tournament_id=this.id, workspace_member_id=member.id, battle_tag="Smurf#2222"),
                # A withdrawn entry elsewhere names nobody.
                BalancerRegistration(
                    tournament_id=other.id,
                    workspace_member_id=member.id,
                    battle_tag="Old#3333",
                    deleted_at=datetime.now(UTC),
                ),
            ]
        )
        await db_session.commit()
        # Captured now: the rollback in ``finally`` expires every instance.
        workspace_id, player_id, auth_ids = workspace.id, player.id, [player_auth.id, staff_auth.id]
        try:
            return (
                await tournament_display_name(db_session, auth_user=player_auth, tournament_id=this.id),
                await tournament_display_name(db_session, auth_user=player_auth, tournament_id=other.id),
                await tournament_display_name(db_session, auth_user=staff_auth, tournament_id=this.id),
                suffix,
            )
        finally:
            await db_session.rollback()
            await db_session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
            await db_session.execute(sa.delete(User).where(User.id == player_id))
            await db_session.execute(sa.delete(AuthUser).where(AuthUser.id.in_(auth_ids)))
            await db_session.commit()

    in_this, in_other, staff, suffix = asyncio.run(_run())
    assert in_this == "Smurf#2222"
    assert in_other == f"Main#{suffix[:4]}"
    # Staff need not play: the site name is the floor.
    assert staff == f"staff_{suffix}"

"""A user's balancer rank history is ONE game's (P7 slice UI-bal, fix round 1).

One workspace runs Overwatch and League, and the same person has a ranked ``support`` in both
(OW's role, LoL's position -- the code collides). The "Load from history" preview names its game,
so a League preview never offers the Overwatch ``support`` rank, and the entries carry the named
game's own rated dimension.

Real database::

    uv run pytest tournament-service/tests/test_registration_rank_history_discipline.py -q
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.repository import CatalogRoleRepository  # noqa: E402
from shared.services.ontology import project_disciplines  # noqa: E402
from src.services.registration.rank_sources import rank_sources_service  # noqa: E402

OW_SUPPORT_RANK = 1500
LOL_SUPPORT_RANK = 2500


async def _seed(session: Any) -> SimpleNamespace:
    await project_disciplines(session)
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"hist-{suffix}", name=f"History {suffix}", disciplines_enabled=["overwatch", "lol"])
    session.add(workspace)
    player = models.User(name=f"hist-{suffix}")
    session.add(player)
    await session.flush()
    member = models.WorkspaceMember(workspace_id=workspace.id, player_id=player.id)
    session.add(member)
    await session.flush()

    roles = CatalogRoleRepository()
    tournaments: dict[str, int] = {}
    for discipline, rank in (("overwatch", OW_SUPPORT_RANK), ("lol", LOL_SUPPORT_RANK)):
        tournament = Tournament(
            workspace_id=workspace.id,
            name=f"{discipline} {suffix}",
            slug=f"hist-{discipline}-{suffix}",
            discipline=discipline,
            status=enums.TournamentStatus.LIVE,
        )
        session.add(tournament)
        await session.flush()
        support = await roles.resolve(session, discipline=discipline, workspace_id=None, dimension=None, code="support")
        registration = models.Registration(tournament_id=tournament.id, workspace_member_id=member.id)
        registration.roles = [
            models.RegistrationRole(
                catalog_role=support, dimension_id=support.dimension_id, priority=0, rank_value=rank
            )
        ]
        session.add(registration)
        tournaments[discipline] = tournament.id
    await session.commit()
    return SimpleNamespace(
        workspace_id=workspace.id, player_id=player.id, tournaments=tournaments, workspace_name=workspace.name
    )


async def _drop(session: Any, seeded: SimpleNamespace) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    await session.execute(sa.delete(models.User).where(models.User.id == seeded.player_id))
    await session.commit()


def test_history_of_one_game_never_carries_the_others_rank_under_the_same_role_code(db_session) -> None:
    async def _run() -> dict[str, Any]:
        seeded = await _seed(db_session)
        try:
            read = {}
            for discipline in ("overwatch", "lol"):
                read[discipline] = await rank_sources_service.load_user_balancer_rank_history(
                    db_session, user_id=seeded.player_id, workspace_id=seeded.workspace_id, discipline_code=discipline
                )
            return {"read": read, "tournaments": seeded.tournaments}
        finally:
            await _drop(db_session, seeded)

    got = asyncio.run(_run())

    overwatch = got["read"]["overwatch"]
    assert [(row["tournament_id"], row["rank_value"]) for row in overwatch] == [
        (got["tournaments"]["overwatch"], OW_SUPPORT_RANK)
    ]
    assert overwatch[0]["role"] == {"dimension": "player_role", "role": "support", "parent": None}

    lol = got["read"]["lol"]
    assert [(row["tournament_id"], row["rank_value"]) for row in lol] == [(got["tournaments"]["lol"], LOL_SUPPORT_RANK)]
    # The League entry is a League position: its own rated dimension, not Overwatch's `player_role`.
    assert lol[0]["role"]["dimension"] == "position"
    assert lol[0]["role"]["role"] == "support"

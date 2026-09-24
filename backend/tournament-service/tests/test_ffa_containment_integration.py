"""FFA lobbies must stay out of every duel-shaped read, on real Postgres.

The series list, the name search, the overview KPIs and the read schemas are
all built for a duel (a home side, an away side, a score). A lobby has none of
those, so it must not appear in any of them unless the caller asks for
``format=ffa`` explicitly. These assert that against a live database with one
duel and one lobby seeded in the same tournament::

    uv run pytest tournament-service/tests/test_ffa_containment_integration.py -v

They take ``db_session`` (``shared.testing``) and SKIP only when Postgres is
unreachable; each test seeds its own workspace and drops it again.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.core.enums import PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.domain.encounter_format import ensure_format  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Encounter, Team, Tournament  # noqa: E402
from src import schemas  # noqa: E402
from src.services.admin.encounter import encounter_service as admin_encounter_service  # noqa: E402
from src.services.challonge.sync import sync_service  # noqa: E402
from src.services.encounter import flows  # noqa: E402
from src.services.encounter.captain import captain_service  # noqa: E402
from src.services.encounter.games import encounter_game_service  # noqa: E402
from src.services.encounter.map_report import map_report_service  # noqa: E402
from src.services.encounter.pick_ban_session import pick_ban_session_service  # noqa: E402
from src.services.encounter.service import encounter_service  # noqa: E402


async def _seed(session: Any) -> tuple[int, int, int, int]:
    """One tournament holding one duel ("Alpha vs Beta") and one lobby ("Alpha Lobby").

    Both names share the "Alpha" prefix so a name search hits them equally --
    only the format filter may tell them apart.
    """

    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"ffac-{suffix}", name=f"FFA containment {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"FFA containment {suffix}",
        slug=f"ffac-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    teams = [
        Team(tournament_id=tournament.id, name=f"Team {index} {suffix}", balancer_name=f"team-{index}-{suffix}")
        for index in range(2)
    ]
    session.add_all(teams)
    await session.flush()
    # Both encounters sit in a stage: an admin edit resolves the stage refs of
    # the row it writes, and refuses one that is linked to none.
    stage_id = (
        await session.execute(
            sa.text(
                'insert into tournament.stage (tournament_id, name, stage_type, "order") '
                "values (:t, 'Group', 'round_robin', 1) returning id"
            ),
            {"t": tournament.id},
        )
    ).scalar_one()

    duel_id = (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, home_team_id, away_team_id, home_score, away_score, "
                "round, best_of, tournament_id, stage_id, status, result_status) "
                "values ('Alpha vs Beta', :h, :a, 0, 0, 1, 3, :t, :s, 'OPEN', 'none') returning id"
            ),
            {"h": teams[0].id, "a": teams[1].id, "t": tournament.id, "s": stage_id},
        )
    ).scalar_one()
    lobby_id = (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, format, home_score, away_score, round, best_of, "
                "tournament_id, stage_id, status, result_status) values ('Alpha Lobby', 'ffa', 0, 0, 1, 3, :t, "
                ":s, 'OPEN', 'none') returning id"
            ),
            {"t": tournament.id, "s": stage_id},
        )
    ).scalar_one()
    await session.commit()
    return workspace.id, tournament.id, duel_id, lobby_id


async def _drop(session: Any, workspace_id: int) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_default_encounter_list_is_duels_only(db_session) -> None:
    async def _run() -> tuple[list[int], int]:
        workspace_id, tournament_id, duel_id, _ = await _seed(db_session)
        try:
            rows, total = await encounter_service.get_all_encounters(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id),
            )
            assert [row.id for row in rows] == [duel_id]
            return [row.id for row in rows], total
        finally:
            await _drop(db_session, workspace_id)

    ids, total = asyncio.run(_run())
    assert len(ids) == 1
    assert total == 1


def test_format_ffa_lists_only_lobbies(db_session) -> None:
    async def _run() -> tuple[list[int], int, int]:
        workspace_id, tournament_id, _, lobby_id = await _seed(db_session)
        try:
            rows, total = await encounter_service.get_all_encounters(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id, format=enums.EncounterFormat.FFA),
            )
            return [row.id for row in rows], total, lobby_id
        finally:
            await _drop(db_session, workspace_id)

    ids, total, lobby_id = asyncio.run(_run())
    assert ids == [lobby_id]
    assert total == 1


def test_search_by_name_never_returns_a_lobby(db_session) -> None:
    """The lobby's name matches the query just as well as the duel's."""

    async def _run() -> tuple[list[int], int]:
        workspace_id, tournament_id, duel_id, _ = await _seed(db_session)
        try:
            rows, total = await encounter_service.get_all_encounters(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id, query="Alpha", fields=["name"]),
            )
            return [row.id for row in rows], total
        finally:
            await _drop(db_session, workspace_id)

    ids, total = asyncio.run(_run())
    assert len(ids) == 1
    assert total == 1


def test_overview_kpis_ignore_lobbies(db_session) -> None:
    async def _run() -> tuple[int, int]:
        workspace_id, tournament_id, _, _ = await _seed(db_session)
        try:
            data = await encounter_service.get_overview_data(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id),
            )
            return data["total"], data["preset_counts"]["all"]
        finally:
            await _drop(db_session, workspace_id)

    total, preset_all = asyncio.run(_run())
    assert total == 1
    assert preset_all == 1


def test_reads_carry_the_encounter_format(db_session) -> None:
    """The frontend routes on it: a lobby page is not a series page."""

    async def _run() -> tuple[str, str, str]:
        workspace_id, _, duel_id, lobby_id = await _seed(db_session)
        try:
            duel = await encounter_service.get_encounter(db_session, duel_id, [])
            lobby = await encounter_service.get_encounter(db_session, lobby_id, [])
            assert duel is not None and lobby is not None
            duel_read = await flows.flows_service.to_pydantic(db_session, duel, [])
            lobby_read = await flows.flows_service.to_pydantic(db_session, lobby, [])
            return duel_read.format, lobby_read.format, flows.to_summary(lobby).format
        finally:
            await _drop(db_session, workspace_id)

    duel_format, lobby_format, summary_format = asyncio.run(_run())
    assert duel_format == enums.EncounterFormat.DUEL
    assert lobby_format == enums.EncounterFormat.FFA
    assert summary_format == enums.EncounterFormat.FFA


# ── the duel-only entry points ───────────────────────────────────────────────


async def _submit_captain_report(session: Any, lobby: Encounter, duel_id: int) -> None:
    await captain_service.submit_captain_report(session, None, lobby.id, home_score=2, away_score=0, closeness=None)


async def _set_encounter_result(session: Any, lobby: Encounter, duel_id: int) -> None:
    await captain_service.set_encounter_result(session, lobby.id, actor_user_id=None)


async def _submit_map_report(session: Any, lobby: Encounter, duel_id: int) -> None:
    await map_report_service.submit_map_report(
        session, lobby, game_id=0, side="home", reporter_user_id=None, home_score=1, away_score=0
    )


async def _ensure_freeplay_game(session: Any, lobby: Encounter, duel_id: int) -> None:
    await encounter_game_service.ensure_freeplay_game(session, lobby)


async def _swap_slots(session: Any, lobby: Encounter, duel_id: int) -> None:
    await admin_encounter_service.swap_slots(
        session,
        lobby.id,
        schemas.EncounterSwapSlotInput(slot="home", target_encounter_id=duel_id, target_slot="home"),
    )


async def _push_single_result(session: Any, lobby: Encounter, duel_id: int) -> None:
    tournament = await session.get(Tournament, lobby.tournament_id)
    await sync_service.push_single_result(session, tournament, lobby)


@pytest.mark.parametrize(
    "call",
    [
        _submit_captain_report,
        _set_encounter_result,
        _submit_map_report,
        _ensure_freeplay_game,
        _swap_slots,
        _push_single_result,
    ],
    ids=lambda call: call.__name__.lstrip("_"),
)
def test_duel_only_actions_refuse_a_lobby(db_session, call) -> None:
    """Every feature built on home/away answers the same way: 409 ``encounter_not_duel``."""

    async def _run() -> tuple[int, list[str]]:
        workspace_id, _, duel_id, lobby_id = await _seed(db_session)
        try:
            lobby = await db_session.get(Encounter, lobby_id)
            with pytest.raises(BaseAPIException) as raised:
                await call(db_session, lobby, duel_id)
            return raised.value.status_code, [item.code for item in raised.value.detail]
        finally:
            await _drop(db_session, workspace_id)

    status_code, codes = asyncio.run(_run())
    assert status_code == 409
    assert codes == ["encounter_not_duel"]


def test_admin_update_refuses_a_duel_only_field_on_a_lobby(db_session) -> None:
    """A lobby is renameable and reschedulable; it has no side to re-team."""

    async def _run() -> tuple[int, list[str]]:
        workspace_id, _, _, lobby_id = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as raised:
                await admin_encounter_service.update_encounter(
                    db_session, lobby_id, schemas.EncounterUpdate(home_team_id=1)
                )
            return raised.value.status_code, [item.code for item in raised.value.detail]
        finally:
            await _drop(db_session, workspace_id)

    status_code, codes = asyncio.run(_run())
    assert status_code == 422
    assert codes == ["ffa_field_not_editable"]


def test_admin_update_still_renames_a_lobby(db_session) -> None:
    async def _run() -> str:
        workspace_id, _, _, lobby_id = await _seed(db_session)
        try:
            updated = await admin_encounter_service.update_encounter(
                db_session, lobby_id, schemas.EncounterUpdate(name="Renamed Lobby")
            )
            return updated.name
        finally:
            await _drop(db_session, workspace_id)

    assert asyncio.run(_run()) == "Renamed Lobby"


def test_pick_ban_session_is_never_started_for_a_lobby(db_session) -> None:
    """Not an error: the veto is simply absent, which is what the room asks."""

    async def _run() -> object:
        workspace_id, _, _, lobby_id = await _seed(db_session)
        try:
            lobby = await db_session.get(Encounter, lobby_id)
            return await pick_ban_session_service.ensure_pick_ban_session(db_session, lobby, PickBanKind.MAP)
        finally:
            await _drop(db_session, workspace_id)

    assert asyncio.run(_run()) is None


def test_ensure_format_accepts_an_encounter_whose_default_is_not_written_yet() -> None:
    """``Encounter.format`` is filled by the column default at flush; before that
    it is ``None``, and every duel writer creates rows that way."""
    ensure_format(Encounter(), enums.EncounterFormat.DUEL)

    with pytest.raises(BaseAPIException) as raised:
        ensure_format(Encounter(format=enums.EncounterFormat.FFA), enums.EncounterFormat.DUEL)
    assert raised.value.status_code == 409
    assert [item.code for item in raised.value.detail] == ["encounter_not_duel"]

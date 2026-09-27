"""Recording, correcting, cancelling and completing FFA lobby games, on real Postgres.

Every rule here is enforced by rows the database actually holds -- a confirmed
game with no duel score, a partial unique index that frees a cancelled
position, an audit CHECK that demands the FFA snapshot -- so these run against
a live database instead of mocks::

    uv run pytest tournament-service/tests/test_ffa_results_integration.py -v

They take ``db_session`` (``shared.testing``) and SKIP only when Postgres is
unreachable; each test seeds its own workspace (and drops it, plus the outbox
rows the completion emits) in ``finally``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.domain.ffa_scoring import FfaGameLine  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import (  # noqa: E402
    Encounter,
    EncounterGame,
    EncounterResultAudit,
    Stage,
    StageItem,
    StageItemInput,
    Standing,
    Team,
    Tournament,
    TournamentComputationJob,
)
from shared.services.chat import ChatRoom  # noqa: E402
from src import schemas  # noqa: E402
from src.rpc import _helpers as rpc_helpers  # noqa: E402
from src.services.admin.stage import stage_service  # noqa: E402
from src.services.encounter.chat_access import EncounterChatAccess  # noqa: E402
from src.services.encounter.ffa import ffa_encounter_service, public_view  # noqa: E402
from src.services.standings.service import standings_service  # noqa: E402
from tests._rpc_fakes import FakeSessionMaker  # noqa: E402

#: One "score" column, no placement points: places derive from the scoreboard.
SCORE_COLUMN = [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}]
SCORING = {"ffa_columns": SCORE_COLUMN, "ffa_formula": "score"}
#: Battle-royale style: 1st place pays 10, 2nd 6, 3rd 4, plus a point per score.
PLACEMENT_SCORING = {
    "ffa_placement_points": [10, 6, 4],
    "ffa_columns": SCORE_COLUMN,
    "ffa_formula": "place_pts + score",
}
#: Two columns, one of them hidden from viewers, and a formula over both.
KILLS_DEATHS = {
    "ffa_columns": [
        {"key": "kills", "label": "Kills", "public": True, "better": "higher"},
        {"key": "deaths", "label": "Deaths", "public": False, "better": "lower"},
    ],
    "ffa_formula": "kills * 2 - deaths",
}


async def _seed(session: Any, *, games: int = 2, regulation: dict | None = None) -> SimpleNamespace:
    """One ffa_league stage with a three-team lobby, and a duel to contrast it."""
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"ffares-{suffix}", name=f"FFA results {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"FFA results {suffix}",
        slug=f"ffares-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    teams = [
        Team(tournament_id=tournament.id, name=f"Team {index} {suffix}", balancer_name=f"team-{index}-{suffix}")
        for index in range(3)
    ]
    session.add_all(teams)
    await session.flush()
    stage = Stage(
        tournament_id=tournament.id,
        name="Lobbies",
        stage_type=enums.StageType.FFA_LEAGUE,
        order=1,
        **(regulation if regulation is not None else SCORING),
    )
    session.add(stage)
    await session.flush()
    item = StageItem(stage_id=stage.id, name="Group A", type=enums.StageItemType.GROUP, order=0)
    session.add(item)
    await session.flush()

    team_ids = [team.id for team in teams]
    lobby = await ffa_encounter_service.create_lobby(session, stage, item, team_ids, games=games)
    duel_id = (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, home_team_id, away_team_id, home_score, away_score, "
                "round, best_of, tournament_id, stage_id, status, result_status) "
                "values ('Duel', :h, :a, 0, 0, 1, 3, :t, :s, 'OPEN', 'none') returning id"
            ),
            {"h": team_ids[0], "a": team_ids[1], "t": tournament.id, "s": stage.id},
        )
    ).scalar_one()
    await session.commit()
    return SimpleNamespace(
        workspace_id=workspace.id,
        tournament_id=tournament.id,
        stage_id=stage.id,
        item_id=item.id,
        lobby_id=lobby.id,
        duel_id=duel_id,
        team_ids=team_ids,
    )


async def _drop(session: Any, seeded: SimpleNamespace) -> None:
    await session.rollback()
    # The outbox is not workspace-scoped, so the completion and invalidation
    # rows this tournament emitted have to be swept by hand -- including the
    # ones that carry only the id of a computation job the workspace delete
    # cascades away.
    job_ids = (
        await session.scalars(
            sa.select(TournamentComputationJob.id).where(TournamentComputationJob.tournament_id == seeded.tournament_id)
        )
    ).all()
    if job_ids:
        await session.execute(
            sa.delete(EventOutbox).where(EventOutbox.payload_json["job_id"].as_integer().in_(job_ids))
        )
    await session.execute(
        sa.delete(EventOutbox).where(
            sa.or_(
                EventOutbox.payload_json["tournament_id"].as_string() == str(seeded.tournament_id),
                EventOutbox.routing_key == f"cache.invalidated.tournament.{seeded.tournament_id}",
            )
        )
    )
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    await session.commit()


def _lines(team_ids: list[int], scores: list[int], placements: list[int | None] | None = None) -> list[FfaGameLine]:
    places = placements or [None] * len(team_ids)
    return [
        FfaGameLine(team_id=team_id, placement=place, stats={"score": score})
        for team_id, place, score in zip(team_ids, places, scores, strict=True)
    ]


def _stat_lines(team_ids: list[int], stats: list[dict[str, float]]) -> list[FfaGameLine]:
    return [
        FfaGameLine(team_id=team_id, placement=None, stats=values)
        for team_id, values in zip(team_ids, stats, strict=True)
    ]


async def _games(session: Any, lobby_id: int) -> list[EncounterGame]:
    result = await session.execute(
        sa.select(EncounterGame).where(EncounterGame.encounter_id == lobby_id).order_by(EncounterGame.id)
    )
    return list(result.scalars().all())


async def _audit(session: Any, lobby_id: int) -> list[EncounterResultAudit]:
    result = await session.execute(
        sa.select(EncounterResultAudit)
        .where(EncounterResultAudit.encounter_id == lobby_id)
        .order_by(EncounterResultAudit.id)
    )
    return list(result.scalars().all())


async def _completed_events(session: Any, lobby_id: int) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(EventOutbox)
            .where(
                EventOutbox.routing_key == "tournament.encounter.completed",
                EventOutbox.payload_json["encounter_id"].as_string() == str(lobby_id),
            )
        )
    ) or 0


async def _reload(session: Any, lobby_id: int) -> Encounter:
    lobby = await session.get(Encounter, lobby_id)
    await session.refresh(lobby)
    return lobby


async def _reload_stage(session: Any, stage_id: int) -> Stage:
    stage = await session.get(Stage, stage_id)
    await session.refresh(stage)
    return stage


async def _standings(session: Any, tournament_id: int) -> list[tuple]:
    result = await session.execute(
        sa.select(Standing)
        .where(Standing.tournament_id == tournament_id)
        .order_by(Standing.stage_item_id, Standing.position)
    )
    return [
        (row.stage_item_id, row.position, row.team_id, row.matches, row.points, row.win, row.buchholz)
        for row in result.scalars()
    ]


# ── recording games ──────────────────────────────────────────────────────────


def test_the_first_game_opens_the_lobby_and_the_last_one_completes_it(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [10, 6, 2]), actor_user_id=None, reason=None
            )
            lobby = await _reload(db_session, seeded.lobby_id)
            after_first = (lobby.status, lobby.result_status, lobby.started_at is not None)

            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 2, _lines(seeded.team_ids, [3, 9, 5]), actor_user_id=None, reason=None
            )
            lobby = await _reload(db_session, seeded.lobby_id)
            after_last = (
                lobby.status,
                lobby.result_status,
                lobby.confirmed_at is not None,
                lobby.ended_at is not None,
            )
            actions = [row.action for row in await _audit(db_session, seeded.lobby_id)]
            return after_first, after_last, actions, await _completed_events(db_session, seeded.lobby_id)
        finally:
            await _drop(db_session, seeded)

    after_first, after_last, actions, events = asyncio.run(_run())
    assert after_first == (enums.EncounterStatus.OPEN, enums.EncounterResultStatus.NONE, True)
    assert after_last == (enums.EncounterStatus.COMPLETED, enums.EncounterResultStatus.CONFIRMED, True, True)
    assert actions == [
        enums.EncounterResultAuditAction.GAME_CONFIRM,
        enums.EncounterResultAuditAction.GAME_CONFIRM,
        enums.EncounterResultAuditAction.CONFIRM,
    ]
    assert events == 1


def test_a_recorded_game_stores_one_row_per_participant_and_no_derived_place(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [10, 7, 7]), actor_user_id=None, reason=None
            )
            rows = (
                await db_session.execute(
                    sa.text(
                        "select team_id, placement, stats from tournament.encounter_game_result "
                        "where encounter_id = :e order by team_id"
                    ),
                    {"e": seeded.lobby_id},
                )
            ).all()
            game = (await _games(db_session, seeded.lobby_id))[0]
            lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            return (
                [tuple(row) for row in rows],
                (game.state, game.format, game.result_version),
                {row.team_id: row.games[0].placement for row in lobby.rows},
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    rows, game_shape, places, team_ids = asyncio.run(_run())
    # Nobody entered a place, so nothing stores one: the column is the manual
    # entry, and a derived place belongs to whichever formula is current.
    assert rows == [
        (team_ids[0], None, {"score": 10}),
        (team_ids[1], None, {"score": 7}),
        (team_ids[2], None, {"score": 7}),
    ]
    # 10, 7, 7 -> 1st, joint 2nd; a lobby game never carries a duel score.
    assert places == {team_ids[0]: 1, team_ids[1]: 2, team_ids[2]: 2}
    assert game_shape == (enums.EncounterGameState.CONFIRMED, "ffa", 1)


# ── corrections ──────────────────────────────────────────────────────────────


def test_correcting_a_confirmed_game_needs_a_reason(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [10, 6, 2]), actor_user_id=None, reason=None
            )
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_game_results(
                    db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [1, 2, 3]), actor_user_id=None, reason=None
                )
            await db_session.rollback()
            refused = (raised.value.status_code, [item.code for item in raised.value.detail])

            await ffa_encounter_service.set_game_results(
                db_session,
                seeded.lobby_id,
                1,
                _lines(seeded.team_ids, [4, 8, 1]),
                actor_user_id=None,
                reason="scoreboard misread",
            )
            games = await _games(db_session, seeded.lobby_id)
            audit = await _audit(db_session, seeded.lobby_id)
            correction = audit[-1]
            return (
                refused,
                len(games),
                games[0].result_version,
                correction.action,
                correction.reason,
                correction.game_id == games[0].id,
                correction.game_result_version,
                (correction.home_score_before, correction.away_score_before),
                (correction.home_score_after, correction.away_score_after),
                correction.ffa_results_json,
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    (
        refused,
        game_count,
        version,
        action,
        reason,
        same_game,
        audited_version,
        before_scores,
        after_scores,
        snapshot,
        team_ids,
    ) = asyncio.run(_run())
    assert refused == (422, ["ffa_reason_required"])
    assert (game_count, version) == (1, 2)
    assert (action, reason, same_game, audited_version) == (
        enums.EncounterResultAuditAction.GAME_CORRECT,
        "scoreboard misread",
        True,
        2,
    )
    assert before_scores == (None, None)
    assert after_scores == (None, None)
    # The journal records what was ENTERED: no place was, so none is snapshotted.
    assert snapshot["before"] == [
        {"team_id": team_ids[0], "placement": None, "stats": {"score": 10}},
        {"team_id": team_ids[1], "placement": None, "stats": {"score": 6}},
        {"team_id": team_ids[2], "placement": None, "stats": {"score": 2}},
    ]
    assert snapshot["after"] == [
        {"team_id": team_ids[1], "placement": None, "stats": {"score": 8}},
        {"team_id": team_ids[0], "placement": None, "stats": {"score": 4}},
        {"team_id": team_ids[2], "placement": None, "stats": {"score": 1}},
    ]


# ── cancellation ─────────────────────────────────────────────────────────────


def test_cancelling_a_game_reopens_the_lobby_and_frees_the_position(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            for position, scores in ((1, [10, 6, 2]), (2, [2, 6, 10])):
                await ffa_encounter_service.set_game_results(
                    db_session,
                    seeded.lobby_id,
                    position,
                    _lines(seeded.team_ids, scores),
                    actor_user_id=None,
                    reason=None,
                )
            cancelled_id = [game.id for game in await _games(db_session, seeded.lobby_id) if game.position == 2][0]

            await ffa_encounter_service.cancel_game(
                db_session, seeded.lobby_id, 2, actor_user_id=None, reason="lobby crashed"
            )
            lobby = await _reload(db_session, seeded.lobby_id)
            reopened = (lobby.status, lobby.result_status, lobby.confirmed_at, lobby.ended_at)
            actions_after_cancel = [row.action for row in await _audit(db_session, seeded.lobby_id)][-2:]

            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 2, _lines(seeded.team_ids, [7, 1, 1]), actor_user_id=None, reason=None
            )
            lobby = await _reload(db_session, seeded.lobby_id)
            games = await _games(db_session, seeded.lobby_id)
            position_two = [(game.id, game.state) for game in games if game.position == 2]
            return (
                reopened,
                actions_after_cancel,
                [state for _, state in position_two],
                cancelled_id in [game_id for game_id, _ in position_two],
                len(position_two),
                lobby.status,
                await _completed_events(db_session, seeded.lobby_id),
            )
        finally:
            await _drop(db_session, seeded)

    reopened, actions, states, kept_old, position_rows, status_now, events = asyncio.run(_run())
    assert reopened == (enums.EncounterStatus.OPEN, enums.EncounterResultStatus.NONE, None, None)
    assert actions == [
        enums.EncounterResultAuditAction.GAME_CANCEL,
        enums.EncounterResultAuditAction.REOPEN,
    ]
    # The cancelled row stays as history; the replacement is a NEW game.
    assert (position_rows, kept_old) == (2, True)
    assert sorted(states, key=str) == sorted(
        [enums.EncounterGameState.CANCELLED, enums.EncounterGameState.CONFIRMED], key=str
    )
    assert status_now == enums.EncounterStatus.COMPLETED
    assert events == 2


def test_cancelling_needs_a_reason_and_refuses_an_unplayed_position(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [10, 6, 2]), actor_user_id=None, reason=None
            )
            with pytest.raises(BaseAPIException) as no_reason:
                await ffa_encounter_service.cancel_game(db_session, seeded.lobby_id, 1, actor_user_id=None, reason="")
            await db_session.rollback()
            with pytest.raises(BaseAPIException) as missing:
                await ffa_encounter_service.cancel_game(
                    db_session, seeded.lobby_id, 2, actor_user_id=None, reason="never played"
                )
            await db_session.rollback()
            return (
                (no_reason.value.status_code, [item.code for item in no_reason.value.detail]),
                (missing.value.status_code, [item.code for item in missing.value.detail]),
            )
        finally:
            await _drop(db_session, seeded)

    no_reason, missing = asyncio.run(_run())
    assert no_reason == (422, ["ffa_reason_required"])
    assert missing == (404, ["ffa_game_not_found"])


# ── how many games the lobby plays ───────────────────────────────────────────


def test_the_games_count_can_never_drop_below_what_was_played(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            for position, scores in ((1, [10, 6, 2]), (2, [2, 6, 10])):
                await ffa_encounter_service.set_game_results(
                    db_session,
                    seeded.lobby_id,
                    position,
                    _lines(seeded.team_ids, scores),
                    actor_user_id=None,
                    reason=None,
                )
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_games_count(db_session, seeded.lobby_id, 1, actor_user_id=None)
            await db_session.rollback()
            refused = (raised.value.status_code, [item.code for item in raised.value.detail])

            await ffa_encounter_service.set_games_count(db_session, seeded.lobby_id, 3, actor_user_id=None)
            lobby = await _reload(db_session, seeded.lobby_id)
            grown = (lobby.best_of, lobby.status, lobby.result_status)
            last_action = (await _audit(db_session, seeded.lobby_id))[-1].action

            await ffa_encounter_service.set_games_count(db_session, seeded.lobby_id, 2, actor_user_id=None)
            lobby = await _reload(db_session, seeded.lobby_id)
            return refused, grown, last_action, (lobby.best_of, lobby.status, lobby.result_status)
        finally:
            await _drop(db_session, seeded)

    refused, grown, last_action, shrunk = asyncio.run(_run())
    assert refused == (422, ["ffa_games_below_played"])
    assert grown == (3, enums.EncounterStatus.OPEN, enums.EncounterResultStatus.NONE)
    assert last_action == enums.EncounterResultAuditAction.REOPEN
    assert shrunk == (2, enums.EncounterStatus.COMPLETED, enums.EncounterResultStatus.CONFIRMED)


def test_a_lobby_always_plays_at_least_one_game(db_session) -> None:
    """Zero would make an untouched lobby instantly "complete" with no result."""

    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_games_count(db_session, seeded.lobby_id, 0, actor_user_id=None)
            await db_session.rollback()
            lobby = await _reload(db_session, seeded.lobby_id)
            return (
                raised.value.status_code,
                [item.code for item in raised.value.detail],
                (lobby.best_of, lobby.status),
            )
        finally:
            await _drop(db_session, seeded)

    status_code, codes, unchanged = asyncio.run(_run())
    assert (status_code, codes) == (422, ["ffa_games_below_played"])
    assert unchanged == (2, enums.EncounterStatus.OPEN)


def test_shrinking_the_stage_best_of_completes_a_lobby_that_already_played_enough(db_session) -> None:
    """Ruling R10: the stage-wide apply-best-of must settle lobbies, not just rewrite a number."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=3, regulation=dict(SCORING, best_of_default=2))
        try:
            for position, scores in ((1, [10, 6, 2]), (2, [2, 6, 10])):
                await ffa_encounter_service.set_game_results(
                    db_session,
                    seeded.lobby_id,
                    position,
                    _lines(seeded.team_ids, scores),
                    actor_user_id=None,
                    reason=None,
                )
            lobby = await _reload(db_session, seeded.lobby_id)
            before = (lobby.best_of, lobby.status)

            changed = await stage_service.apply_best_of_to_existing(db_session, seeded.stage_id)
            lobby = await _reload(db_session, seeded.lobby_id)
            return (
                before,
                changed,
                (lobby.best_of, lobby.status, lobby.result_status),
                await _completed_events(db_session, seeded.lobby_id),
            )
        finally:
            await _drop(db_session, seeded)

    before, changed, after, events = asyncio.run(_run())
    assert before == (3, enums.EncounterStatus.OPEN)
    assert changed == 2  # the lobby and the duel seeded next to it
    assert after == (2, enums.EncounterStatus.COMPLETED, enums.EncounterResultStatus.CONFIRMED)
    assert events == 1


# ── refusals ─────────────────────────────────────────────────────────────────


def test_a_position_past_the_planned_games_is_refused(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_game_results(
                    db_session, seeded.lobby_id, 3, _lines(seeded.team_ids, [1, 2, 3]), actor_user_id=None, reason=None
                )
            await db_session.rollback()
            return raised.value.status_code, [item.code for item in raised.value.detail]
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == (422, ["ffa_game_out_of_range"])


@pytest.mark.parametrize(
    ("regulation", "build", "code"),
    [
        (
            SCORING,
            lambda ids: [FfaGameLine(team_id=ids[0], placement=None, stats={"score": 1})],
            "ffa_result_missing_team",
        ),
        (
            SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=None, stats={"score": 1}) for team_id in [*ids, ids[0]]
            ],
            "ffa_result_duplicate_team",
        ),
        (
            SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=None, stats={"score": 1}) for team_id in [*ids[:2], -1]
            ],
            "ffa_result_unknown_team",
        ),
        (
            SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, stats={"score": -1}) for team_id in ids],
            "ffa_result_invalid_stat",
        ),
        (
            SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=None, stats={"score": 1, "kills": 2}) for team_id in ids
            ],
            "ffa_result_unknown_stat",
        ),
        (
            SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, stats={}) for team_id in ids],
            "ffa_result_missing_stat",
        ),
        (
            SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=place, stats={"score": 1})
                for team_id, place in zip(ids, [1, None, None], strict=True)
            ],
            "ffa_result_mixed_placement",
        ),
        (
            PLACEMENT_SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, stats={"score": 1}) for team_id in ids],
            "ffa_result_placement_required",
        ),
        (
            PLACEMENT_SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=place, stats={"score": 1})
                for team_id, place in zip(ids, [1, 1, 2], strict=True)
            ],
            "ffa_result_invalid_placement",
        ),
    ],
)
def test_an_invalid_result_is_refused_with_its_own_code(db_session, regulation, build, code) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session, regulation=regulation)
        try:
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_game_results(
                    db_session, seeded.lobby_id, 1, build(seeded.team_ids), actor_user_id=None, reason=None
                )
            await db_session.rollback()
            return (
                raised.value.status_code,
                [item.code for item in raised.value.detail],
                len(await _games(db_session, seeded.lobby_id)),
            )
        finally:
            await _drop(db_session, seeded)

    status_code, codes, games = asyncio.run(_run())
    assert (status_code, codes) == (422, [code])
    assert games == 0  # a refused result never opens a position


def test_a_refusal_carries_its_code_through_the_rpc_envelope(db_session) -> None:
    """Raising the code is half the contract; the envelope has to carry it out.

    The FFA sites raise ``BaseAPIException`` with ``ApiExc`` *models*, not the
    dicts ``ApiHTTPException`` dumps, and ``http_error`` used to keep dict items
    only -- so this refusal reached the client as ``{"code": "unprocessable",
    "message": "error"}`` with nothing to branch on.
    """

    async def _case() -> dict:
        seeded = await _seed(db_session, regulation=PLACEMENT_SCORING)
        try:
            with patch.object(rpc_helpers.db, "async_session_maker", FakeSessionMaker(db_session)):
                envelope = await rpc_helpers._run(
                    logging.getLogger(__name__),
                    lambda session: ffa_encounter_service.set_game_results(
                        session,
                        seeded.lobby_id,
                        1,
                        _lines(seeded.team_ids, [1, 1, 1], [1, 1, 2]),
                        actor_user_id=None,
                        reason=None,
                    ),
                )
            await db_session.rollback()
            return envelope
        finally:
            await _drop(db_session, seeded)

    envelope = asyncio.run(_case())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "unprocessable"
    assert [field["code"] for field in envelope["error"]["details"]["fields"]] == ["ffa_result_invalid_placement"]
    assert envelope["error"]["message"] != "error"


def test_recording_a_game_into_a_duel_is_refused(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_game_results(
                    db_session, seeded.duel_id, 1, _lines(seeded.team_ids, [1, 2, 3]), actor_user_id=None, reason=None
                )
            await db_session.rollback()
            return raised.value.status_code, [item.code for item in raised.value.detail]
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == (409, ["encounter_not_ffa"])


def test_an_unknown_lobby_is_a_404(db_session) -> None:
    async def _run() -> int:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_game_results(
                    db_session, -1, 1, _lines(seeded.team_ids, [1, 2, 3]), actor_user_id=None, reason=None
                )
            await db_session.rollback()
            return raised.value.status_code
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == 404


# ── the read the standings build on ──────────────────────────────────────────


def test_stage_results_group_confirmed_games_by_lobby_group(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            for position, scores in ((1, [10, 6, 2]), (2, [2, 6, 10])):
                await ffa_encounter_service.set_game_results(
                    db_session,
                    seeded.lobby_id,
                    position,
                    _lines(seeded.team_ids, scores),
                    actor_user_id=None,
                    reason=None,
                )
            await ffa_encounter_service.cancel_game(
                db_session, seeded.lobby_id, 2, actor_user_id=None, reason="restarted"
            )
            results = await ffa_encounter_service.load_stage_results(db_session, seeded.stage_id)
            return (
                results.participant_ids(seeded.item_id),
                [
                    [(line.team_id, line.placement, line.stats) for line in game]
                    for game in results.games(seeded.item_id)
                ],
                results.participant_ids(-1),
                results.games(-1),
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    participants, games, unknown_participants, unknown_games, team_ids = asyncio.run(_run())
    assert participants == team_ids
    # The cancelled second game is gone from the read the standings sum.
    assert games == [[(team_ids[0], 1, {"score": 10}), (team_ids[1], 2, {"score": 6}), (team_ids[2], 3, {"score": 2})]]
    assert (unknown_participants, unknown_games) == ([], [])


# ── ranking a league and seeding the bracket behind it ───────────────────────


async def _seed_league(session: Any) -> SimpleNamespace:
    """Two ffa groups of three, with a single-elimination bracket behind them."""
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"ffaleague-{suffix}", name=f"FFA league {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"FFA league {suffix}",
        slug=f"ffaleague-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    teams = [
        Team(tournament_id=tournament.id, name=f"Team {index} {suffix}", balancer_name=f"team-{index}-{suffix}")
        for index in range(6)
    ]
    session.add_all(teams)
    await session.flush()
    team_ids = [team.id for team in teams]

    league = Stage(
        tournament_id=tournament.id,
        name="League",
        stage_type=enums.StageType.FFA_LEAGUE,
        order=1,
        **SCORING,
    )
    bracket_stage = Stage(
        tournament_id=tournament.id,
        name="Playoffs",
        stage_type=enums.StageType.SINGLE_ELIMINATION,
        order=2,
    )
    session.add_all([league, bracket_stage])
    await session.flush()

    groups = []
    lobbies = []
    for index, name in enumerate(("Group A", "Group B")):
        group = StageItem(stage_id=league.id, name=name, type=enums.StageItemType.GROUP, order=index)
        session.add(group)
        await session.flush()
        seats = team_ids[index * 3 : index * 3 + 3]
        for slot, team_id in enumerate(seats, 1):
            session.add(
                StageItemInput(
                    stage_item_id=group.id,
                    slot=slot,
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=team_id,
                )
            )
        lobbies.append(await ffa_encounter_service.create_lobby(session, league, group, seats, games=1))
        groups.append(group)

    bracket = StageItem(stage_id=bracket_stage.id, name="Playoffs", type=enums.StageItemType.SINGLE_BRACKET, order=0)
    session.add(bracket)
    await session.commit()
    return SimpleNamespace(
        workspace_id=workspace.id,
        tournament_id=tournament.id,
        stage_id=league.id,
        bracket_stage_id=bracket_stage.id,
        group_ids=[group.id for group in groups],
        lobby_ids=[lobby.id for lobby in lobbies],
        team_ids=team_ids,
    )


def test_a_finished_league_ranks_its_groups_and_seeds_the_bracket(db_session) -> None:
    """The whole handover: games -> Standing rows -> stage done -> bracket teams.

    ``activate_stage`` is untouched by FFA -- it resolves TENTATIVE inputs from
    ``Standing.position`` of the source group, so an ffa league qualifies the
    next stage exactly like a round robin does.
    """

    async def _run() -> tuple:
        seeded = await _seed_league(db_session)
        try:
            await stage_service.wire_from_groups(
                db_session, seeded.bracket_stage_id, seeded.stage_id, top=2, commit=True
            )
            # Group A: teams 0 > 1 > 2. Group B the other way round: 5 > 4 > 3.
            for lobby_id, seats, scores in (
                (seeded.lobby_ids[0], seeded.team_ids[:3], [10, 6, 2]),
                (seeded.lobby_ids[1], seeded.team_ids[3:], [2, 6, 10]),
            ):
                await ffa_encounter_service.set_game_results(
                    db_session, lobby_id, 1, _lines(seats, scores), actor_user_id=None, reason=None
                )
            await db_session.commit()

            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            league = await _reload_stage(db_session, seeded.stage_id)
            table = await _standings(db_session, seeded.tournament_id)

            bracket_stage = await stage_service.activate_stage(db_session, seeded.bracket_stage_id)
            wired = sorted(
                (inp.source_stage_item_id, inp.source_position, inp.team_id, inp.input_type)
                for item in bracket_stage.items
                for inp in item.inputs
            )
            return league.is_completed, table, wired, seeded.group_ids, seeded.team_ids
        finally:
            await _drop(db_session, seeded)

    completed, table, wired, group_ids, team_ids = asyncio.run(_run())
    group_a, group_b = group_ids

    assert completed is True
    # Six group rows, ranked inside each group, every one a GROUP row.
    assert table == [
        (group_a, 1, team_ids[0], 1, 10.0, 1, 0.0),
        (group_a, 2, team_ids[1], 1, 6.0, 0, 0.0),
        (group_a, 3, team_ids[2], 1, 2.0, 0, 0.0),
        (group_b, 1, team_ids[5], 1, 10.0, 1, 0.0),
        (group_b, 2, team_ids[4], 1, 6.0, 0, 0.0),
        (group_b, 3, team_ids[3], 1, 2.0, 0, 0.0),
    ]
    # Every tentative slot became a real team: the top two of each group.
    assert wired == sorted(
        [
            (group_a, 1, team_ids[0], enums.StageItemInputType.FINAL),
            (group_a, 2, team_ids[1], enums.StageItemInputType.FINAL),
            (group_b, 1, team_ids[5], enums.StageItemInputType.FINAL),
            (group_b, 2, team_ids[4], enums.StageItemInputType.FINAL),
        ]
    )


# ── the reads the lobby table is drawn from ──────────────────────────────────

#: Placement pays, and the organizer named the single column.
LABELLED_SCORING = {
    "ffa_placement_points": [10, 6, 4],
    "ffa_columns": [{"key": "score", "label": "Kills", "public": True, "better": "higher"}],
    "ffa_formula": "place_pts + score",
}


def test_the_lobby_read_carries_rules_rows_and_one_cell_per_planned_game(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session, games=2, regulation=LABELLED_SCORING)
        try:
            await ffa_encounter_service.set_game_results(
                db_session,
                seeded.lobby_id,
                1,
                # Placement pays here, so the organizer gives every place.
                _lines(seeded.team_ids, [5, 3, 1], [1, 2, 3]),
                actor_user_id=None,
                reason=None,
            )
            return await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id), seeded
        finally:
            await _drop(db_session, seeded)

    lobby, seeded = asyncio.run(_run())
    team_ids = seeded.team_ids
    assert (lobby.encounter_id, lobby.tournament_id, lobby.stage_id, lobby.stage_item_id) == (
        seeded.lobby_id,
        seeded.tournament_id,
        seeded.stage_id,
        seeded.item_id,
    )
    assert (lobby.name, lobby.best_of, lobby.advance_count) == ("Group A", 2, None)
    assert (lobby.status, lobby.result_status) == (enums.EncounterStatus.OPEN, enums.EncounterResultStatus.NONE)
    assert (lobby.rules.placement_points, lobby.rules.formula, lobby.rules.requires_placement) == (
        [10.0, 6.0, 4.0],
        "place_pts + score",
        True,
    )
    assert [(c.key, c.label, c.public, c.better) for c in lobby.rules.columns] == [("score", "Kills", True, "higher")]
    # Nothing has ranked the group yet, so the read says so instead of inventing
    # a place -- and unranked rows fall back to seat order.
    assert [(row.team_id, row.slot, row.position, row.tie_group) for row in lobby.rows] == [
        (team_ids[0], 1, None, None),
        (team_ids[1], 2, None, None),
        (team_ids[2], 3, None, None),
    ]
    assert [(row.points, row.games_played, row.wins, row.stats) for row in lobby.rows] == [
        (15.0, 1, 1, {"score": 5}),
        (9.0, 1, 0, {"score": 3}),
        (5.0, 1, 0, {"score": 1}),
    ]
    assert lobby.rows[0].team_name.startswith("Team 0 ")
    # One cell per PLANNED game: the unplayed second one is a hole, not a zero.
    assert [(cell.position, cell.state, cell.placement, cell.stats, cell.points) for cell in lobby.rows[0].games] == [
        (1, enums.EncounterGameState.CONFIRMED, 1, {"score": 5}, 15.0),
        (2, None, None, None, None),
    ]


def test_a_cancelled_game_leaves_its_cell_free_again(db_session) -> None:
    """Cancelling frees the position (the partial unique index says so), so the
    cell must read as unplayed rather than showing the void numbers."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1)
        try:
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [5, 3, 1]), actor_user_id=None, reason=None
            )
            await ffa_encounter_service.cancel_game(
                db_session, seeded.lobby_id, 1, actor_user_id=None, reason="restarted"
            )
            lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            return [(cell.state, cell.points) for cell in lobby.rows[0].games], [row.points for row in lobby.rows]
        finally:
            await _drop(db_session, seeded)

    cells, points = asyncio.run(_run())
    assert cells == [(None, None)]
    assert points == [0.0, 0.0, 0.0]


def test_lobby_row_points_and_positions_are_the_standing_the_bracket_reads(db_session) -> None:
    """The table the organizer sees and the table advancement reads are one row set."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1)
        try:
            # The last seat wins, so seat order and rank order disagree.
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [1, 3, 5]), actor_user_id=None, reason=None
            )
            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            rows = await db_session.execute(sa.select(Standing).where(Standing.stage_item_id == seeded.item_id))
            table = {row.team_id: (row.position, row.points, row.tie_group) for row in rows.scalars()}
            return (
                [(row.team_id, row.slot, row.position, row.points, row.tie_group) for row in lobby.rows],
                table,
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    rows, table, team_ids = asyncio.run(_run())
    assert [row[0] for row in rows] == [team_ids[2], team_ids[1], team_ids[0]]
    # Sorted by position, NOT by seat: the seats come back 3, 2, 1.
    assert [row[1] for row in rows] == [3, 2, 1]
    assert [row[2] for row in rows] == [1, 2, 3]
    for team_id, _slot, position, points, tie_group in rows:
        assert (position, points, tie_group) == table[team_id]


def test_the_stage_read_lists_every_lobby_in_group_order(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed_league(db_session)
        try:
            # Group A: teams 0 > 1 > 2. Group B the other way round: 5 > 4 > 3.
            for lobby_id, seats, scores in (
                (seeded.lobby_ids[0], seeded.team_ids[:3], [10, 6, 2]),
                (seeded.lobby_ids[1], seeded.team_ids[3:], [2, 6, 10]),
            ):
                await ffa_encounter_service.set_game_results(
                    db_session, lobby_id, 1, _lines(seats, scores), actor_user_id=None, reason=None
                )
            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            lobbies = await ffa_encounter_service.load_stage_lobbies(
                db_session, seeded.stage_id, tournament_id=seeded.tournament_id
            )
            with pytest.raises(BaseAPIException) as raised:
                # A stage of another tournament must not be readable through this
                # tournament's (visibility-gated) path.
                await ffa_encounter_service.load_stage_lobbies(db_session, seeded.stage_id, tournament_id=-1)
            return lobbies, raised.value.status_code, seeded
        finally:
            await _drop(db_session, seeded)

    lobbies, mismatch, seeded = asyncio.run(_run())
    team_ids = seeded.team_ids
    assert [lobby.encounter_id for lobby in lobbies] == seeded.lobby_ids
    assert [lobby.stage_item_id for lobby in lobbies] == seeded.group_ids
    assert [[row.team_id for row in lobby.rows] for lobby in lobbies] == [
        [team_ids[0], team_ids[1], team_ids[2]],
        [team_ids[5], team_ids[4], team_ids[3]],
    ]
    assert [[row.position for row in lobby.rows] for lobby in lobbies] == [[1, 2, 3], [1, 2, 3]]
    assert all(lobby.status == enums.EncounterStatus.COMPLETED for lobby in lobbies)
    assert mismatch == 404


def test_the_lobby_read_refuses_a_duel_and_an_unknown_encounter(db_session) -> None:
    async def _run() -> tuple[int, int]:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as duel:
                await ffa_encounter_service.load_lobby(db_session, seeded.duel_id)
            with pytest.raises(BaseAPIException) as missing:
                await ffa_encounter_service.load_lobby(db_session, -1)
            return duel.value.status_code, missing.value.status_code
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == (409, 404)


def test_a_public_read_carries_no_value_of_a_hidden_column(db_session) -> None:
    """A hidden column is hidden from the API, not merely from the table: not in
    ``rules.columns``, not in a row total, not in a game cell (plan §7.3)."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1, regulation=KILLS_DEATHS)
        try:
            await ffa_encounter_service.set_game_results(
                db_session,
                seeded.lobby_id,
                1,
                _stat_lines(
                    seeded.team_ids,
                    [{"kills": 6, "deaths": 1}, {"kills": 3, "deaths": 2}, {"kills": 1, "deaths": 4}],
                ),
                actor_user_id=None,
                reason=None,
            )
            full = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            return full, public_view(full)
        finally:
            await _drop(db_session, seeded)

    full, public = asyncio.run(_run())
    assert [column.key for column in full.rules.columns] == ["kills", "deaths"]
    assert [column.key for column in public.rules.columns] == ["kills"]
    # The rule itself stays readable, hidden key and all: it is a rule, not data.
    assert public.rules.formula == "kills * 2 - deaths"
    assert [row.stats for row in public.rows] == [{"kills": 6}, {"kills": 3}, {"kills": 1}]
    assert [row.stats for row in full.rows] == [
        {"kills": 6, "deaths": 1},
        {"kills": 3, "deaths": 2},
        {"kills": 1, "deaths": 4},
    ]
    assert [cell.stats for cell in public.rows[0].games] == [{"kills": 6}]
    assert [cell.stats for cell in full.rows[0].games] == [{"kills": 6, "deaths": 1}]
    # Points are computed from every column, hidden ones included.
    assert [row.points for row in public.rows] == [11.0, 4.0, -2.0]


def test_points_and_places_come_from_the_formula(db_session) -> None:
    """No placement points, no places entered: the formula decides the points and
    the points decide the places, ties shared (plan §5.2)."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1, regulation=KILLS_DEATHS)
        try:
            await ffa_encounter_service.set_game_results(
                db_session,
                seeded.lobby_id,
                1,
                _stat_lines(
                    seeded.team_ids,
                    [{"kills": 2, "deaths": 0}, {"kills": 3, "deaths": 2}, {"kills": 5, "deaths": 4}],
                ),
                actor_user_id=None,
                reason=None,
            )
            lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            return (
                [(row.team_id, row.points) for row in lobby.rows],
                [(cell.placement, cell.points) for row in lobby.rows for cell in row.games],
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    totals, cells, team_ids = asyncio.run(_run())
    # kills * 2 - deaths -> 4, 4, 6: the third team wins, the first two share 2nd.
    assert dict(totals) == {team_ids[0]: 4.0, team_ids[1]: 4.0, team_ids[2]: 6.0}
    assert sorted(cells) == [(1, 6.0), (2, 4.0), (2, 4.0)]


def test_a_game_is_refused_when_the_formula_needs_a_place(db_session) -> None:
    """``requires_placement`` is not a flag the organizer sets, it is what the
    formula reads -- and the read says so to the dialog."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1, regulation=PLACEMENT_SCORING)
        try:
            lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            with pytest.raises(BaseAPIException) as raised:
                await ffa_encounter_service.set_game_results(
                    db_session,
                    seeded.lobby_id,
                    1,
                    _lines(seeded.team_ids, [3, 2, 1]),
                    actor_user_id=None,
                    reason=None,
                )
            await db_session.rollback()
            return lobby.rules.requires_placement, [item.code for item in raised.value.detail]
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == (True, ["ffa_result_placement_required"])


# ── who may talk in a lobby's room ───────────────────────────────────────────


async def _seed_account(session: Any, name: str) -> tuple[int, int, str]:
    """An auth account with a linked player: ``(auth_user_id, player_id, username)``.

    No BattleTag and no registration, so inside a tournament the account goes
    by its site name (``tournament_display_name``'s floor).
    """
    suffix = uuid.uuid4().hex[:12]
    auth_user = AuthUser(email=f"{name}-{suffix}@example.com", username=f"{name}-{suffix}")
    session.add(auth_user)
    await session.flush()
    player = User(name=f"{name} {suffix}", auth_user_id=auth_user.id)
    session.add(player)
    await session.flush()
    return auth_user.id, player.id, auth_user.username


async def _caller(session: Any, auth_user_id: int) -> AuthUser:
    """The account as the gateway hands it over: no roles, no permissions, so
    nothing but captaincy can let it write (staff is a separate branch)."""
    auth_user = await session.get(AuthUser, auth_user_id)
    auth_user.set_rbac_cache([], [], [], {})
    return auth_user


def test_a_lobby_participant_captain_writes_in_its_chat_and_an_outsider_watches(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        players: list[int] = []
        auths: list[int] = []
        try:
            captain_auth_id, captain_player_id, captain_name = await _seed_account(db_session, "captain")
            outsider_auth_id, outsider_player_id, _ = await _seed_account(db_session, "outsider")
            players = [captain_player_id, outsider_player_id]
            auths = [captain_auth_id, outsider_auth_id]
            # The captain of a SEATED team -- and the lobby has no sides at all,
            # so only the participant rows can answer this.
            await db_session.execute(
                sa.update(Team).where(Team.id == seeded.team_ids[1]).values(captain_id=captain_player_id)
            )
            await db_session.commit()
            access = EncounterChatAccess()
            room = ChatRoom.encounter(seeded.lobby_id)
            mine = await access.resolve(db_session, await _caller(db_session, captain_auth_id), room)
            theirs = await access.resolve(db_session, await _caller(db_session, outsider_auth_id), room)
            return (
                (mine.role, mine.can_write, mine.can_moderate, mine.display_name),
                (theirs.role, theirs.can_write),
                captain_name,
            )
        finally:
            await _drop(db_session, seeded)
            # Accounts are not workspace-scoped, so the cascade leaves them behind.
            await db_session.execute(sa.delete(User).where(User.id.in_(players)))
            await db_session.execute(sa.delete(AuthUser).where(AuthUser.id.in_(auths)))
            await db_session.commit()

    mine, theirs, captain_name = asyncio.run(_run())
    assert mine == ("captain", True, False, captain_name)
    assert theirs == ("spectator", False)


# ── editing the scoring of a stage that is already being played ──────────────


async def _jobs(session: Any, tournament_id: int) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(TournamentComputationJob)
            .where(TournamentComputationJob.tournament_id == tournament_id)
        )
    ) or 0


def _scoring(**overrides: Any) -> dict:
    block = {
        "columns": [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}],
        "placement_points": [],
        "formula": "score",
    }
    block.update(overrides)
    return block


async def _start_the_playoff(session: Any, seeded: SimpleNamespace) -> None:
    """Seed the bracket off the league and play a match in it: from here on the
    league's places are frozen into a playoff nobody can re-seed."""
    await stage_service.wire_from_groups(session, seeded.bracket_stage_id, seeded.stage_id, top=2, commit=True)
    for lobby_id, seats, scores in (
        (seeded.lobby_ids[0], seeded.team_ids[:3], [10, 6, 2]),
        (seeded.lobby_ids[1], seeded.team_ids[3:], [2, 6, 10]),
    ):
        await ffa_encounter_service.set_game_results(
            session, lobby_id, 1, _lines(seats, scores), actor_user_id=None, reason=None
        )
    await standings_service.recalculate_for_tournament(session, seeded.tournament_id)
    bracket_stage = await stage_service.activate_stage(session, seeded.bracket_stage_id)
    session.add(
        Encounter(
            name="Semifinal",
            home_team_id=seeded.team_ids[0],
            away_team_id=seeded.team_ids[5],
            home_score=2,
            away_score=1,
            round=1,
            tournament_id=seeded.tournament_id,
            stage_id=seeded.bracket_stage_id,
            stage_item_id=bracket_stage.items[0].id,
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
        )
    )
    await session.commit()


def test_rewriting_the_formula_after_the_playoff_started_is_refused(db_session) -> None:
    """The edit would re-rank the groups the playoff was seeded from, and there
    is nowhere to put the new order (plan §6)."""

    async def _run() -> tuple:
        seeded = await _seed_league(db_session)
        try:
            await _start_the_playoff(db_session, seeded)
            with pytest.raises(BaseAPIException) as raised:
                await stage_service.update_stage(
                    db_session,
                    seeded.stage_id,
                    schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
                )
            await db_session.rollback()
            stage = await _reload_stage(db_session, seeded.stage_id)
            return raised.value.status_code, str(raised.value.detail), stage.ffa_formula
        finally:
            await _drop(db_session, seeded)

    status_code, detail, formula = asyncio.run(_run())
    assert status_code == 409
    assert "downstream stage already in progress" in detail
    assert formula == "score"


def test_relabelling_a_column_after_the_playoff_started_is_allowed(db_session) -> None:
    """A label moves nobody: it is editable for as long as the stage exists."""

    async def _run() -> tuple:
        seeded = await _seed_league(db_session)
        try:
            await _start_the_playoff(db_session, seeded)
            await stage_service.update_stage(
                db_session,
                seeded.stage_id,
                schemas.StageUpdate(
                    ffa_scoring=_scoring(
                        columns=[{"key": "score", "label": "Kills", "public": False, "better": "higher"}]
                    )
                ),
            )
            stage = await _reload_stage(db_session, seeded.stage_id)
            return stage.ffa_columns, stage.ffa_formula
        finally:
            await _drop(db_session, seeded)

    columns, formula = asyncio.run(_run())
    assert columns == [{"key": "score", "label": "Kills", "public": False, "better": "higher"}]
    assert formula == "score"


def test_dropping_a_column_the_games_hold_values_for_is_refused(db_session) -> None:
    """Values are the record of the tournament; losing them would go unnoticed
    until somebody disputed a place (plan §6)."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1, regulation=KILLS_DEATHS)
        try:
            await ffa_encounter_service.set_game_results(
                db_session,
                seeded.lobby_id,
                1,
                _stat_lines(
                    seeded.team_ids,
                    [{"kills": 6, "deaths": 1}, {"kills": 3, "deaths": 2}, {"kills": 1, "deaths": 4}],
                ),
                actor_user_id=None,
                reason=None,
            )
            with pytest.raises(BaseAPIException) as raised:
                await stage_service.update_stage(
                    db_session,
                    seeded.stage_id,
                    schemas.StageUpdate(
                        ffa_scoring=_scoring(
                            columns=[{"key": "kills", "label": "Kills", "public": True, "better": "higher"}],
                            formula="kills * 2",
                        )
                    ),
                )
            await db_session.rollback()
            stage = await _reload_stage(db_session, seeded.stage_id)
            return (
                raised.value.status_code,
                [item.code for item in raised.value.detail],
                [column["key"] for column in stage.ffa_columns],
            )
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == (422, ["ffa_column_in_use"], ["kills", "deaths"])


def test_an_accepted_scoring_edit_queues_the_recalculation(db_session) -> None:
    """Points, places and the public table are all derived from the rules, so a
    rules edit has to re-run the standings -- nothing else would."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1)
        try:
            before = await _jobs(db_session, seeded.tournament_id)
            await stage_service.update_stage(
                db_session,
                seeded.stage_id,
                schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
            )
            after = await _jobs(db_session, seeded.tournament_id)
            # The same block again is not an edit and must not queue anything.
            await stage_service.update_stage(
                db_session,
                seeded.stage_id,
                schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
            )
            return before, after, await _jobs(db_session, seeded.tournament_id)
        finally:
            await _drop(db_session, seeded)

    before, after, again = asyncio.run(_run())
    assert after == before + 1
    assert again == after


def test_a_formula_edit_moves_the_derived_places_with_the_points(db_session) -> None:
    """Spec acceptance 3: after a scoring edit the places of a placement-less
    lobby follow the NEW formula, not the one they were recorded under.

    Nothing re-derives a stored place, so the place must not be stored: a cell
    reading "1st, -7 pts" next to a team with fewer points, and an advancement
    ranked by ``ffa_game_wins`` off the retired rule, are the same bug.
    """

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=2, regulation=KILLS_DEATHS)
        try:
            for position, stats in enumerate(
                (
                    [{"kills": 2, "deaths": 0}, {"kills": 3, "deaths": 2}, {"kills": 5, "deaths": 4}],
                    [{"kills": 1, "deaths": 0}, {"kills": 0, "deaths": 0}, {"kills": 4, "deaths": 3}],
                ),
                1,
            ):
                await ffa_encounter_service.set_game_results(
                    db_session,
                    seeded.lobby_id,
                    position,
                    _stat_lines(seeded.team_ids, stats),
                    actor_user_id=None,
                    reason=None,
                )
            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            # kills * 2 - deaths made the third team win both games.
            before = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)

            await stage_service.update_stage(
                db_session,
                seeded.stage_id,
                schemas.StageUpdate(
                    ffa_scoring=_scoring(columns=KILLS_DEATHS["ffa_columns"], formula="kills - deaths * 3")
                ),
            )
            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            after = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            rows = await db_session.execute(sa.select(Standing).where(Standing.stage_item_id == seeded.item_id))
            table = {row.team_id: (row.position, row.points, row.win) for row in rows.scalars()}
            return (
                {row.team_id: (row.points, row.wins) for row in before.rows},
                {row.team_id: (row.points, row.wins) for row in after.rows},
                {row.team_id: [(cell.placement, cell.points) for cell in row.games] for row in after.rows},
                table,
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    before, after, cells, table, team_ids = asyncio.run(_run())
    first, second, third = team_ids
    assert before == {first: (6.0, 0), second: (4.0, 0), third: (11.0, 2)}
    # kills - deaths * 3: 2/-3/-7 and 1/0/-5, so the first team now wins both.
    assert cells == {
        first: [(1, 2.0), (1, 1.0)],
        second: [(2, -3.0), (2, 0.0)],
        third: [(3, -7.0), (3, -5.0)],
    }
    assert after == {first: (3.0, 2), second: (-3.0, 0), third: (-12.0, 0)}
    assert table == {first: (1, 3.0, 2), second: (2, -3.0, 0), third: (3, -12.0, 0)}


def test_a_formula_edit_leaves_the_places_the_organizer_entered_alone(db_session) -> None:
    """A score-only lobby MAY carry hand-entered places (plan §5.2). Those are a
    decision, not a derivation: re-scoring the games must not move them."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=1)
        try:
            # Places deliberately against the scoreboard: the lowest score is 1st.
            await ffa_encounter_service.set_game_results(
                db_session,
                seeded.lobby_id,
                1,
                _lines(seeded.team_ids, [1, 3, 5], [1, 2, 3]),
                actor_user_id=None,
                reason=None,
            )
            await stage_service.update_stage(
                db_session,
                seeded.stage_id,
                schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
            )
            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
            return (
                {row.team_id: ([(cell.placement, cell.points) for cell in row.games], row.wins) for row in lobby.rows},
                seeded.team_ids,
            )
        finally:
            await _drop(db_session, seeded)

    rows, team_ids = asyncio.run(_run())
    first, second, third = team_ids
    assert rows == {first: ([(1, 2.0)], 1), second: ([(2, 6.0)], 0), third: ([(3, 10.0)], 0)}

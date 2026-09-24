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
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.domain.ffa_scoring import FfaGameLine  # noqa: E402
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
)
from src.services.admin.stage import stage_service  # noqa: E402
from src.services.encounter.ffa import ffa_encounter_service  # noqa: E402
from src.services.standings.service import standings_service  # noqa: E402

#: Score-only: a point per elimination, places derived from the scoreboard.
SCORING = {"ffa_scoring": {"score_points": 1}}
#: Battle-royale style: 1st place pays 10, 2nd 6, 3rd 4, plus a point per score.
PLACEMENT_SCORING = {"ffa_scoring": {"placement_points": [10, 6, 4], "score_points": 1}}


async def _seed(session: Any, *, games: int = 2, settings: dict | None = None) -> SimpleNamespace:
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
        settings_json=dict(settings if settings is not None else SCORING),
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
    # rows this tournament emitted have to be swept by hand.
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
        FfaGameLine(team_id=team_id, placement=place, score=score)
        for team_id, place, score in zip(team_ids, places, scores, strict=True)
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


def test_a_recorded_game_stores_one_row_per_participant_with_derived_places(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await ffa_encounter_service.set_game_results(
                db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [10, 7, 7]), actor_user_id=None, reason=None
            )
            rows = (
                await db_session.execute(
                    sa.text(
                        "select team_id, placement, score from tournament.encounter_game_result "
                        "where encounter_id = :e order by placement, team_id"
                    ),
                    {"e": seeded.lobby_id},
                )
            ).all()
            game = (await _games(db_session, seeded.lobby_id))[0]
            return [tuple(row) for row in rows], (game.state, game.format, game.result_version), seeded.team_ids
        finally:
            await _drop(db_session, seeded)

    rows, game_shape, team_ids = asyncio.run(_run())
    # 10, 7, 7 -> 1st, joint 2nd; a lobby game never carries a duel score.
    assert rows == [(team_ids[0], 1, 10), (team_ids[1], 2, 7), (team_ids[2], 2, 7)]
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
    assert snapshot["before"] == [
        {"team_id": team_ids[0], "placement": 1, "score": 10},
        {"team_id": team_ids[1], "placement": 2, "score": 6},
        {"team_id": team_ids[2], "placement": 3, "score": 2},
    ]
    assert snapshot["after"] == [
        {"team_id": team_ids[1], "placement": 1, "score": 8},
        {"team_id": team_ids[0], "placement": 2, "score": 4},
        {"team_id": team_ids[2], "placement": 3, "score": 1},
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


def test_shrinking_the_stage_best_of_completes_a_lobby_that_already_played_enough(db_session) -> None:
    """Ruling R10: the stage-wide apply-best-of must settle lobbies, not just rewrite a number."""

    async def _run() -> tuple:
        seeded = await _seed(db_session, games=3, settings=dict(SCORING, best_of={"default": 2}))
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
    ("settings", "build", "code"),
    [
        (SCORING, lambda ids: [FfaGameLine(team_id=ids[0], placement=None, score=1)], "ffa_result_missing_team"),
        (
            SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, score=1) for team_id in [*ids, ids[0]]],
            "ffa_result_duplicate_team",
        ),
        (
            SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, score=1) for team_id in [*ids[:2], -1]],
            "ffa_result_unknown_team",
        ),
        (
            SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, score=-1) for team_id in ids],
            "ffa_result_invalid_score",
        ),
        (
            SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=place, score=1)
                for team_id, place in zip(ids, [1, None, None], strict=True)
            ],
            "ffa_result_mixed_placement",
        ),
        (
            PLACEMENT_SCORING,
            lambda ids: [FfaGameLine(team_id=team_id, placement=None, score=1) for team_id in ids],
            "ffa_result_placement_required",
        ),
        (
            PLACEMENT_SCORING,
            lambda ids: [
                FfaGameLine(team_id=team_id, placement=place, score=1)
                for team_id, place in zip(ids, [1, 1, 2], strict=True)
            ],
            "ffa_result_invalid_placement",
        ),
    ],
)
def test_an_invalid_result_is_refused_with_its_own_code(db_session, settings, build, code) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session, settings=settings)
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
                    [(line.team_id, line.placement, line.score) for line in game]
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
    assert games == [[(team_ids[0], 1, 10), (team_ids[1], 2, 6), (team_ids[2], 3, 2)]]
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
        settings_json=dict(SCORING),
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

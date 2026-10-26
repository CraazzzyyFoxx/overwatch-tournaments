"""FFA lobbies: an encounter with more than two seats.

A lobby is an ``Encounter`` whose ``slot_count`` is N and whose
``scoring_rule`` is a ``points`` preset: the teams sit in ``encounter.team``
like a duel's two do, and each game keeps one ``encounter.game_team`` row per
seat with its placement and the organizer's columns.

A lobby's truth is its games: ``best_of`` is how many it plans to play, and
completion is DERIVED -- the rule's end formula (``games >= best_of``) is asked
by the single result writer after every game, so recording, correcting,
cancelling a game and changing the planned count all settle completion the same
way, and a reopen is impossible to forget.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.enums import EncounterGameResultSource, EncounterGameState, EncounterResultStatus
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_scoring import (
    FFA_MAX_LOBBY_SIZE,
    GameLine,
    ScoringRules,
    game_points,
    resolve_placements,
    team_totals,
)
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.game import EncounterGame, EncounterGameTeam
from shared.models.encounter.team import EncounterTeam
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.repository import BracketEncounterRepository, EncounterRepository, StageRepository
from shared.services.encounter.events import enqueue_encounter_completed
from shared.services.encounter.participants import MemberSnapshot, place_team
from shared.services.encounter.result import lock_encounter
from src.schemas.ffa import (
    FfaColumnRead,
    FfaGameCellRead,
    FfaLobbyRead,
    FfaLobbyRowRead,
    FfaRulesRead,
)
from src.services.bracket import advancement
from src.services.encounter.games import (
    EncounterGameService,
    GameResultIn,
    encounter_game_service,
)
from src.services.encounter.settle import enqueue_challonge_push, settle_confirmed
from src.services.tournament.events import enqueue_tournament_recalculation

__all__ = ("FfaEncounterService", "FfaStageResults", "ffa_encounter_service", "public_view", "require_lobby")


def require_lobby(encounter: Encounter) -> None:
    """409 unless ``encounter`` is a lobby. How it is SCORED says lobby from duel (``Encounter.scoring_preset``), not
    how many seats it has: a two-seat lobby is still a lobby, and a duel has no lobby table, games count or per-game
    placements to write."""
    if encounter.scoring_preset != "points":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[ApiExc(code="ffa_not_a_lobby", msg=f"Encounter {encounter.id} is a duel, not an FFA lobby")],
        )


@dataclass(frozen=True, slots=True)
class FfaStageResults:
    """Every confirmed lobby result of one stage, grouped by group (stage item).

    The standings build a table per group, not per lobby, so both reads are
    keyed by ``stage_item_id``: the roster (a team with no games still has a
    row) and the games, oldest first.
    """

    participants: dict[int, list[int]] = field(default_factory=dict)
    games_by_item: dict[int, list[tuple[GameLine, ...]]] = field(default_factory=dict)

    def participant_ids(self, stage_item_id: int) -> list[int]:
        return list(self.participants.get(stage_item_id, ()))

    def games(self, stage_item_id: int) -> list[tuple[GameLine, ...]]:
        return list(self.games_by_item.get(stage_item_id, ()))


class FfaEncounterService:
    """Lobbies end to end: seating, per-game results, completion, reads."""

    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
        stage_repo: StageRepository = StageRepository(),
        games: EncounterGameService = encounter_game_service,
    ) -> None:
        self.encounter_repo = encounter_repo
        self.bracket_encounter_repo = bracket_encounter_repo
        self.stage_repo = stage_repo
        self.games = games

    async def get_encounter(self, session: AsyncSession, encounter_id: int) -> Encounter | None:
        """The bare encounter row, lobby or duel alike; ``None`` when missing."""
        return await self.encounter_repo.get(session, encounter_id)

    async def create_lobby(
        self,
        session: AsyncSession,
        stage: models.Stage,
        item: models.StageItem,
        team_ids: Sequence[int],
        *,
        games: int,
        rosters: dict[int, Sequence[MemberSnapshot]] | None = None,
        names: dict[int, str] | None = None,
    ) -> Encounter:
        """Seat ``team_ids`` (already in seed order) in a new lobby for ``item``."""
        if not 2 <= len(team_ids) <= FFA_MAX_LOBBY_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=[
                    ApiExc(
                        code="ffa_lobby_size",
                        msg=f"A lobby seats 2..{FFA_MAX_LOBBY_SIZE} participants; {item.name!r} has {len(team_ids)}",
                    )
                ],
            )
        tournament = await session.get_one(models.Tournament, stage.tournament_id)
        lobby = await self.encounter_repo.create(
            session,
            Encounter(
                workspace_id=tournament.workspace_id,
                discipline=tournament.discipline,
                tournament_id=stage.tournament_id,
                scoring_rule_id=stage.scoring_rule_id,
                name=item.name,
                slot_count=len(team_ids),
                best_of=games,
            ),
        )
        await self.bracket_encounter_repo.create(
            session,
            BracketEncounter(
                encounter_id=lobby.id,
                tournament_id=stage.tournament_id,
                stage_id=stage.id,
                stage_item_id=item.id,
                round=1,
            ),
        )
        for slot, team_id in enumerate(team_ids, 1):
            await place_team(
                session,
                lobby,
                slot=slot,
                team_id=team_id,
                name=(names or {}).get(team_id, f"Team {team_id}"),
                # ``team_ids`` arrives in seed order, so the slot IS the seed.
                seed=slot,
                members=(rosters or {}).get(team_id, ()),
            )
        await session.flush()
        return lobby

    # -- commands ----------------------------------------------------------
    async def record_lobby_game(
        self,
        session: AsyncSession,
        encounter_id: int,
        position: int,
        results: Sequence[GameResultIn],
        *,
        actor_user_id: int | None,
        reason: str | None,
    ) -> Encounter:
        """Record (or correct) one game of a lobby and settle its completion.

        Commits: the game's rows, its state, the lobby's standing and the
        journal row are one decision, and half of it is worse than none of it.
        """
        lobby = await lock_encounter(session, encounter_id)
        if not 1 <= position <= lobby.best_of:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="ffa_game_out_of_range", msg=f"This lobby plays games 1..{lobby.best_of}")],
            )
        game = await self._live_game(session, lobby, position)
        if game.state == EncounterGameState.CONFIRMED and not (reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="ffa_reason_required", msg="Correcting a confirmed game needs a reason")],
            )
        await self.games.record_result(
            session,
            lobby,
            game,
            results=results,
            source=EncounterGameResultSource.ADMIN,
            actor_user_id=actor_user_id,
            reason=reason,
        )
        await enqueue_tournament_recalculation(session, lobby.tournament_id)
        if lobby.result_status == EncounterResultStatus.CONFIRMED:
            await enqueue_challonge_push(session, lobby)
        await session.commit()
        return lobby

    async def cancel_game(
        self,
        session: AsyncSession,
        encounter_id: int,
        position: int,
        *,
        actor_user_id: int | None,
        reason: str,
    ) -> Encounter:
        """Retire one game as history, freeing its position for a replay.

        The partial unique index on ``(encounter_id, position)`` skips cancelled
        rows, so the next result for this position is a NEW game -- the void one
        stays readable instead of being overwritten. Commits.
        """
        lobby = await lock_encounter(session, encounter_id)
        if not (reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="ffa_reason_required", msg="Cancelling a game needs a reason")],
            )
        game = next((row for row in await self.games.list_games(session, lobby.id) if row.position == position), None)
        if game is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="ffa_game_not_found", msg=f"This lobby has no live game {position}")],
            )
        was_confirmed = lobby.result_status == EncounterResultStatus.CONFIRMED
        await self.games.cancel_games(session, lobby, [game], actor_user_id=actor_user_id, reason=reason)
        # Voiding a played game can take a finished lobby back below its card.
        await self._settle_transition(session, lobby, was_confirmed=was_confirmed, actor_user_id=actor_user_id)
        # Last, like every result writer: the recalculation state row is locked
        # only after every downstream encounter the transition locked.
        await enqueue_tournament_recalculation(session, lobby.tournament_id)
        await session.commit()
        return lobby

    async def set_games_count(
        self,
        session: AsyncSession,
        encounter_id: int,
        games: int,
        *,
        actor_user_id: int | None,
    ) -> Encounter:
        """Change how many games THIS lobby plays. Commits.

        Never below what it already played: the games are the record, so a
        smaller number would silently drop confirmed results from the table.
        """
        lobby = await lock_encounter(session, encounter_id)
        confirmed = sum(
            row.state == EncounterGameState.CONFIRMED for row in await self.games.list_games(session, lobby.id)
        )
        # A lobby that plays no games at all is not a lobby, hence the floor of 1.
        if games < max(confirmed, 1):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    ApiExc(
                        code="ffa_games_below_played",
                        msg=(
                            f"This lobby has already played {confirmed} games"
                            if confirmed
                            else "A lobby plays at least one game"
                        ),
                    )
                ],
            )
        lobby.best_of = games
        await session.flush()
        # The end formula reads ``best_of``: raising the count reopens a lobby
        # that was complete, lowering it can finish one, and the single result
        # writer settles both without a second copy of the rule here.
        await self.refresh_completion(session, lobby, actor_user_id=actor_user_id)
        # Last, as in ``cancel_game``: encounters before the recalculation state.
        await enqueue_tournament_recalculation(session, lobby.tournament_id)
        await session.commit()
        return lobby

    async def refresh_completion(
        self, session: AsyncSession, encounter: Encounter, *, actor_user_id: int | None
    ) -> None:
        """Settle "is this lobby finished?" from its live games, and run what
        that move owes (:meth:`_settle_transition`). No commit."""
        from shared.core.enums import EncounterResultAuditAction  # noqa: PLC0415 - local to this one call
        from shared.services.encounter.result import refresh_from_games  # noqa: PLC0415 - avoids a cycle

        was_confirmed = encounter.result_status == EncounterResultStatus.CONFIRMED
        await refresh_from_games(
            session,
            encounter,
            action=EncounterResultAuditAction.CONFIRM,
            audit_source="admin" if actor_user_id is not None else "system",
            actor_user_id=actor_user_id,
        )
        await self._settle_transition(session, encounter, was_confirmed=was_confirmed, actor_user_id=actor_user_id)

    @staticmethod
    async def _settle_transition(
        session: AsyncSession, encounter: Encounter, *, was_confirmed: bool, actor_user_id: int | None
    ) -> None:
        """What a lobby's result crossing CONFIRMED owes, once the single result
        writer moved it -- for every lobby write that is not a game's own result
        (a games count, a voided game). No commit.

        Turned CONFIRMED: what the game that finishes one owes
        (``EncounterGameService.record_result``, :meth:`record_lobby_game`) --
        the completed event, the bracket and standings, the Challonge push, last
        since it carries the result version. Turned back: what
        ``reopen_encounter_result`` owes -- every seat its old result filled
        downstream is unwound, and the standings follow.
        """
        confirmed = encounter.result_status == EncounterResultStatus.CONFIRMED
        if not was_confirmed and confirmed:
            await enqueue_encounter_completed(session, encounter, source_service="tournament-service")
            await settle_confirmed(session, encounter)
            await enqueue_challonge_push(session, encounter)
        elif was_confirmed and not confirmed:
            await advancement.reset_downstream(session, encounter, actor_user_id=actor_user_id)
            await enqueue_tournament_recalculation(session, encounter.tournament_id)

    # -- reads -------------------------------------------------------------
    async def load_stage_results(self, session: AsyncSession, stage_id: int) -> FfaStageResults:
        """One stage's rosters and confirmed games, grouped for the standings.

        Two queries for the whole stage, not two per lobby: the standings job
        rebuilds every group at once.
        """
        participants: dict[int, list[int]] = {}
        seats = (
            (
                await session.execute(
                    sa.select(EncounterTeam, BracketEncounter.stage_item_id)
                    .join(BracketEncounter, BracketEncounter.encounter_id == EncounterTeam.encounter_id)
                    .where(BracketEncounter.stage_id == stage_id, EncounterTeam.active.is_(True))
                    .order_by(EncounterTeam.encounter_id, EncounterTeam.slot)
                )
            )
            .tuples()
            .all()
        )
        for seat, stage_item_id in seats:
            if stage_item_id is None or seat.team_id is None:
                continue
            bucket = participants.setdefault(stage_item_id, [])
            # A team seated in two lobbies of one group is still one competitor.
            if seat.team_id not in bucket:
                bucket.append(seat.team_id)

        team_by_participation = {seat.id: seat.team_id for seat, _item in seats}
        grouped: dict[int, list[list[GameLine]]] = {}
        current: tuple[int, int] | None = None
        rows = (
            (
                await session.execute(
                    sa.select(EncounterGameTeam, EncounterGame.position, BracketEncounter.stage_item_id)
                    .join(EncounterGame, EncounterGame.id == EncounterGameTeam.game_id)
                    .join(BracketEncounter, BracketEncounter.encounter_id == EncounterGame.encounter_id)
                    .where(
                        BracketEncounter.stage_id == stage_id,
                        EncounterGame.state == EncounterGameState.CONFIRMED,
                    )
                    .order_by(EncounterGame.encounter_id, EncounterGame.position, EncounterGameTeam.encounter_team_id)
                )
            )
            .tuples()
            .all()
        )
        for line, position, stage_item_id in rows:
            if stage_item_id is None or line.encounter_team_id not in team_by_participation:
                continue
            bucket = grouped.setdefault(stage_item_id, [])
            key = (line.encounter_id, position)
            if key != current:
                current = key
                bucket.append([])
            bucket[-1].append(
                GameLine(
                    # Keyed by the SOURCE team: the standings rank competitors
                    # across a group's lobbies, not seats of one of them.
                    encounter_team_id=team_by_participation[line.encounter_team_id],
                    score=line.score,
                    placement=line.placement,
                    values=dict(line.column_values or {}),
                )
            )
        return FfaStageResults(
            participants=participants,
            # The stored lines, not a frozen ranking: a game with no entered
            # places is placed by the CURRENT formula wherever it is read.
            games_by_item={item_id: [tuple(game) for game in bucket] for item_id, bucket in grouped.items()},
        )

    async def load_lobby(self, session: AsyncSession, encounter_id: int) -> FfaLobbyRead:
        """One lobby as the table it is: rules, seats, game cells, standing. 409 for a duel (:func:`require_lobby`)."""
        lobby = await self.encounter_repo.get(session, encounter_id)
        if lobby is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="encounter_not_found", msg=f"Encounter {encounter_id} not found")],
            )
        require_lobby(lobby)
        return (await self._read_lobbies(session, [lobby]))[0]

    async def load_stage_lobbies(
        self, session: AsyncSession, stage_id: int, *, tournament_id: int
    ) -> list[FfaLobbyRead]:
        """Every lobby of one stage, in group order.

        ``tournament_id`` is the one the caller was cleared to see: a stage of
        another tournament reads as absent, or a hidden tournament's lobbies
        would be reachable through a public tournament's path.
        """
        stage = await self.stage_repo.get(session, stage_id)
        if stage is None or stage.tournament_id != tournament_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="stage_not_found", msg=f"Stage {stage_id} not found")],
            )
        rows = await session.execute(
            sa.select(Encounter)
            .join(BracketEncounter, BracketEncounter.encounter_id == Encounter.id)
            .outerjoin(models.StageItem, models.StageItem.id == BracketEncounter.stage_item_id)
            .where(BracketEncounter.stage_id == stage_id, Encounter.scoring_preset == "points")
            .order_by(models.StageItem.order.nulls_last(), Encounter.id)
        )
        return await self._read_lobbies(session, list(rows.scalars()))

    async def is_participant_captain(
        self, session: AsyncSession, auth_user: models.AuthUser, encounter: Encounter
    ) -> bool:
        """Does this account captain a team SEATED in this encounter?"""
        return bool(
            await session.scalar(
                sa.select(
                    sa.exists()
                    .where(EncounterTeam.encounter_id == encounter.id)
                    .where(EncounterTeam.active.is_(True))
                    .where(models.Team.id == EncounterTeam.team_id)
                    .where(models.User.id == models.Team.captain_id)
                    .where(models.User.auth_user_id == auth_user.id)
                )
            )
        )

    async def _read_lobbies(self, session: AsyncSession, lobbies: Sequence[Encounter]) -> list[FfaLobbyRead]:
        """Build the read model for a whole stage in a fixed number of queries."""
        if not lobbies:
            return []
        lobby_ids = [lobby.id for lobby in lobbies]

        seats: dict[int, list[EncounterTeam]] = {lobby_id: [] for lobby_id in lobby_ids}
        for seat in (
            await session.execute(
                sa.select(EncounterTeam)
                .where(EncounterTeam.encounter_id.in_(lobby_ids), EncounterTeam.active.is_(True))
                .order_by(EncounterTeam.encounter_id, EncounterTeam.slot)
            )
        ).scalars():
            seats[seat.encounter_id].append(seat)

        # Cancelled games are history: the position they held is free again, so
        # the cell must read as unplayed.
        games: dict[int, list[EncounterGame]] = {lobby_id: [] for lobby_id in lobby_ids}
        for game in (
            await session.execute(
                sa.select(EncounterGame)
                .where(
                    EncounterGame.encounter_id.in_(lobby_ids),
                    EncounterGame.state != EncounterGameState.CANCELLED,
                )
                .order_by(EncounterGame.encounter_id, EncounterGame.position)
            )
        ).scalars():
            games[game.encounter_id].append(game)

        game_ids = [game.id for rows in games.values() for game in rows]
        lines: dict[int, dict[int, GameLine]] = {game_id: {} for game_id in game_ids}
        if game_ids:
            for row in (
                await session.execute(sa.select(EncounterGameTeam).where(EncounterGameTeam.game_id.in_(game_ids)))
            ).scalars():
                lines[row.game_id][row.encounter_team_id] = GameLine(
                    encounter_team_id=row.encounter_team_id,
                    score=row.score,
                    placement=row.placement,
                    values=dict(row.column_values or {}),
                )

        team_ids = [seat.team_id for rows in seats.values() for seat in rows if seat.team_id is not None]
        teams = {
            row.id: row
            for row in (
                await session.execute(
                    sa.select(models.Team.id, models.Team.name, models.Team.image_url).where(
                        models.Team.id.in_(team_ids)
                    )
                )
            ).all()
        }
        positions = {
            row.encounter_id: row
            for row in (
                await session.execute(sa.select(BracketEncounter).where(BracketEncounter.encounter_id.in_(lobby_ids)))
            ).scalars()
        }
        item_ids = [row.stage_item_id for row in positions.values() if row.stage_item_id is not None]
        ranked = {
            (row.stage_item_id, row.team_id): row
            for row in (
                await session.execute(
                    sa.select(
                        models.Standing.stage_item_id,
                        models.Standing.team_id,
                        models.Standing.position,
                        models.Standing.tie_group,
                        models.Standing.is_pinned,
                    ).where(models.Standing.stage_item_id.in_(item_ids), models.Standing.team_id.in_(team_ids))
                )
            ).all()
        }
        advance = {
            row.id: row.advance_count
            for row in (
                await session.execute(
                    sa.select(models.StageItem.id, models.StageItem.advance_count).where(
                        models.StageItem.id.in_(item_ids)
                    )
                )
            ).all()
        }
        stage_ids = {row.stage_id for row in positions.values() if row.stage_id is not None}
        stage_advance = {
            row.id: row.advance_count
            for row in (
                await session.execute(
                    sa.select(models.Stage.id, models.Stage.advance_count).where(models.Stage.id.in_(stage_ids))
                )
            ).all()
        }

        out = []
        for lobby in lobbies:
            rules = await self.games.rules(session, lobby)
            out.append(
                self._read_lobby(
                    lobby,
                    seats[lobby.id],
                    games[lobby.id],
                    lines,
                    teams,
                    ranked,
                    advance,
                    stage_advance,
                    positions.get(lobby.id),
                    rules,
                )
            )
        return out

    def _read_lobby(
        self,
        lobby: Encounter,
        seats: Sequence[EncounterTeam],
        games: Sequence[EncounterGame],
        lines: dict[int, dict[int, GameLine]],
        teams: dict[int, sa.Row],
        ranked: dict[tuple[int, int], sa.Row],
        advance: dict[int, int | None],
        stage_advance: dict[int, int | None],
        position_row: BracketEncounter | None,
        rules: ScoringRules,
    ) -> FfaLobbyRead:
        by_position = {game.position: game for game in games}
        # Normally 1..best_of, but a lowered games count must never hide a
        # result that was already recorded past the new end.
        last = max([lobby.best_of, *by_position], default=lobby.best_of)
        # One placing and one payout per game of THIS lobby (``lines`` holds the
        # whole stage's): a game with no entered places is placed once, here,
        # by the current formula.
        placements = {game.id: resolve_placements(rules, list(lines[game.id].values())) for game in games}
        points = {game.id: game_points(rules, list(lines[game.id].values())) for game in games}
        totals = team_totals(
            [seat.id for seat in seats],
            [
                tuple(sorted(lines[game.id].values(), key=_line_order))
                for game in games
                if game.state == EncounterGameState.CONFIRMED
            ],
            rules,
        )
        stage_item_id = position_row.stage_item_id if position_row is not None else None
        stage_id = position_row.stage_id if position_row is not None else None
        item_advance = advance.get(stage_item_id) if stage_item_id is not None else None
        rows = []
        for seat in seats:
            total = totals[seat.id]
            team = teams.get(seat.team_id) if seat.team_id is not None else None
            standing = ranked.get((stage_item_id, seat.team_id))
            rows.append(
                FfaLobbyRowRead(
                    team_id=seat.team_id,
                    team_name=team.name if team is not None else seat.name,
                    team_image_url=team.image_url if team is not None else None,
                    slot=seat.slot,
                    position=standing.position if standing is not None else None,
                    tie_group=standing.tie_group if standing is not None else None,
                    is_pinned=standing.is_pinned if standing is not None else False,
                    points=total.points,
                    games_played=total.games,
                    wins=total.wins,
                    stats=dict(total.stats),
                    games=[
                        self._read_cell(position, by_position.get(position), lines, placements, points, seat.id)
                        for position in range(1, last + 1)
                    ],
                )
            )
        # Rank order, then seat order for whatever the standings have not ranked.
        rows.sort(key=lambda row: (row.position is None, row.position or 0, row.slot))
        return FfaLobbyRead(
            encounter_id=lobby.id,
            tournament_id=lobby.tournament_id,
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            name=lobby.name,
            status=lobby.status,
            result_status=lobby.result_status,
            best_of=lobby.best_of,
            scheduled_at=lobby.scheduled_at,
            advance_count=item_advance if item_advance is not None else stage_advance.get(stage_id),
            rules=FfaRulesRead(
                columns=[
                    FfaColumnRead(key=column.key, label=column.label, public=column.public, better=column.better)
                    for column in rules.columns
                ],
                placement_points=list(rules.placement_points),
                formula=rules.game_formula.source,
                requires_placement=rules.requires_placement,
            ),
            rows=rows,
        )

    @staticmethod
    def _read_cell(
        position: int,
        game: EncounterGame | None,
        lines: dict[int, dict[int, GameLine]],
        placements: dict[int, dict[int, int]],
        points: dict[int, dict[int, float]],
        encounter_team_id: int,
    ) -> FfaGameCellRead:
        game_lines = lines.get(game.id, {}) if game is not None else {}
        line = game_lines.get(encounter_team_id)
        placed = placements.get(game.id, {}) if game is not None else {}
        # ``teams`` is a variable of the formula, so the points were paid over
        # the lines THIS game holds, not the lobby's seat count.
        paid = points.get(game.id, {}) if game is not None else {}
        return FfaGameCellRead(
            position=position,
            state=game.state if game is not None else None,
            placement=placed.get(encounter_team_id),
            points=paid.get(encounter_team_id),
            stats=dict(line.values) if line is not None else None,
        )

    # -- internals ---------------------------------------------------------
    async def _live_game(self, session: AsyncSession, lobby: Encounter, position: int) -> EncounterGame:
        """The live game of ``position``, opening it if this is its first result."""
        game = next((row for row in await self.games.list_games(session, lobby.id) if row.position == position), None)
        if game is not None:
            return game
        return await self.games.open_game(session, lobby, position=position)


def _line_order(line: GameLine) -> tuple[int, int]:
    """Best place first, ties by participation -- the read-back order."""
    return (line.placement or 0, line.encounter_team_id)


def public_view(lobby: FfaLobbyRead) -> FfaLobbyRead:
    """The same table with every non-public column removed.

    The service builds ONE lobby read, with every column on it, and the public
    endpoints trim it here -- so a hidden column cannot leak through a read
    nobody remembered to filter, and the admin endpoints need no second builder.

    The formula is NOT trimmed: it is the rule the table is computed by, so a
    viewer may see a hidden key's NAME there.
    """
    public_keys = {column.key for column in lobby.rules.columns if column.public}
    if len(public_keys) == len(lobby.rules.columns):
        return lobby

    def _keep(stats: dict[str, float] | None) -> dict[str, float] | None:
        if stats is None:
            return None
        return {key: value for key, value in stats.items() if key in public_keys}

    return lobby.model_copy(
        update={
            "rules": lobby.rules.model_copy(
                update={"columns": [column for column in lobby.rules.columns if column.public]}
            ),
            "rows": [
                row.model_copy(
                    update={
                        "stats": _keep(row.stats),
                        "games": [cell.model_copy(update={"stats": _keep(cell.stats)}) for cell in row.games],
                    }
                )
                for row in lobby.rows
            ],
        }
    )


ffa_encounter_service = FfaEncounterService()

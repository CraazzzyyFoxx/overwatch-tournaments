"""The organizer's tournament-wide list of pre-game rooms.

Answers "which room needs me right now" for a whole tournament: one row per
encounter that plays a pick-ban room, carrying the phase it sits in, the open
step of each kind and the handful of attention flags staff act on (a dispute,
an expired timer, a match that started with a captain still not ready).

STRICTLY read-only, and that is a hard requirement rather than a preference:
the room's own read (``pick_ban_action.get_pick_ban_state``) lazily CREATES
sessions, opens freeplay positions and settles expired steps. Running that for
every encounter of a tournament would turn opening a dashboard into dozens of
writes -- so nothing here calls ``ensure_pick_ban_session``, ``get_pick_ban_state``
or ``_settle``, nothing commits and nothing emits. What it does instead is read
the same rows in BULK (a constant number of queries, never one per encounter)
and feed them to the very same pure functions the room uses:
``pick_ban_rules.current_step``/``step_progress`` for the cursor,
``pick_ban_config.pick_config`` for the config cascade,
``unavailable_reason_for`` for a room that cannot open, and
``PickBanActionService.step_deadline`` for the timer.

Phase/attention ranking lives in the two pure functions at the bottom, where it
can be exercised without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import (
    EncounterFormat,
    EncounterGameState,
    EncounterResultStatus,
    EncounterStatus,
    MapPoolEntryStatus,
    MapVetoSessionStatus,
    PickBanKind,
)
from shared.domain import pick_ban_rules as pbr
from shared.domain.pick_ban_config import has_pool, pick_config
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.pick_ban import (
    EncounterReadiness,
    PickBanConfig,
    PickBanEntry,
    PickBanSession,
    PickBanSubmission,
)
from shared.models.tournament.stage import Stage
from shared.models.tournament.team import Team
from shared.repository.pick_ban import CONFIG_POOL_LOAD
from src.schemas import pregame_rooms as schemas
from src.services.encounter.pick_ban_action import PickBanActionService
from src.services.encounter.pick_ban_session import (
    resolved_steps,
    unavailable_reason_for,
)

__all__ = ("PregameRoomsService", "derive_attention", "derive_phase", "pregame_rooms_service")

_KINDS = (PickBanKind.MAP, PickBanKind.HERO)


async def _rows(session: AsyncSession, statement: Any) -> list[Any]:
    """Every row of one bulk read. Each query below is a flat
    ``SELECT ... WHERE ... IN (...)`` whose result is indexed in memory."""
    return list((await session.execute(statement)).scalars().all())


class PregameRoomsService:
    async def list_rooms(self, session: AsyncSession, tournament_id: int) -> schemas.PregameRoomsRead:
        """Every pre-game room of one tournament, in bracket reading order.

        At most nine queries whatever the tournament's size: encounters, stages,
        teams, pick-ban configs, readiness rows, sessions and -- only when a
        session exists -- their submissions (the cursor's only input) and the
        settled map count a hero room waits on, plus the series' games.
        """
        now = datetime.now(UTC)
        encounters = await _rows(
            session,
            select(Encounter).where(
                Encounter.tournament_id == tournament_id,
                # A lobby has no two sides to pick or ban between.
                Encounter.format != EncounterFormat.FFA.value,
            ),
        )
        if not encounters:
            return schemas.PregameRoomsRead(tournament_id=tournament_id, generated_at=now, rooms=[])

        encounter_ids = [encounter.id for encounter in encounters]
        stages = {
            stage.id: stage for stage in await _rows(session, select(Stage).where(Stage.tournament_id == tournament_id))
        }
        team_ids = sorted(
            {
                team_id
                for encounter in encounters
                for team_id in (encounter.home_team_id, encounter.away_team_id)
                if team_id is not None
            }
        )
        teams = {team.id: team for team in await _rows(session, select(Team).where(Team.id.in_(team_ids)))}
        # The whole cascade of both kinds in hand: `pick_config` ranks it per
        # encounter in memory, which is what keeps this at one config query.
        configs = await _rows(
            session,
            select(PickBanConfig).where(PickBanConfig.tournament_id == tournament_id).options(*CONFIG_POOL_LOAD),
        )
        configs_by_kind = {kind: [config for config in configs if config.kind == kind] for kind in _KINDS}

        ready_sides: dict[int, set[str]] = {}
        for row in await _rows(
            session, select(EncounterReadiness).where(EncounterReadiness.encounter_id.in_(encounter_ids))
        ):
            ready_sides.setdefault(row.encounter_id, set()).add(row.side)

        sessions_by_key: dict[tuple[int, str], PickBanSession] = {}
        for pick_ban in await _rows(
            session, select(PickBanSession).where(PickBanSession.encounter_id.in_(encounter_ids))
        ):
            sessions_by_key[(pick_ban.encounter_id, str(pick_ban.kind))] = pick_ban

        session_ids = [pick_ban.id for pick_ban in sessions_by_key.values()]
        submissions: dict[int, list[PickBanSubmission]] = {}
        picked_per_session: dict[int, int] = {}
        if session_ids:
            for row in await _rows(
                session, select(PickBanSubmission).where(PickBanSubmission.session_id.in_(session_ids))
            ):
                submissions.setdefault(row.session_id, []).append(row)
            # How many maps each map session has settled -- the gate a hero room
            # waits behind. A count of decided entries IS the highest settled
            # round (see ``settled_map_rounds``), here for every session at once.
            for settled_session_id in await _rows(
                session,
                select(PickBanEntry.session_id).where(
                    PickBanEntry.session_id.in_(session_ids),
                    PickBanEntry.status == MapPoolEntryStatus.PICKED,
                ),
            ):
                picked_per_session[settled_session_id] = picked_per_session.get(settled_session_id, 0) + 1

        games_by_encounter: dict[int, list[EncounterGame]] = {}
        for game in await _rows(session, select(EncounterGame).where(EncounterGame.encounter_id.in_(encounter_ids))):
            games_by_encounter.setdefault(game.encounter_id, []).append(game)

        rows: list[schemas.PregameRoomRow] = []
        for encounter in encounters:
            stage = stages.get(encounter.stage_id) if encounter.stage_id is not None else None
            # ``is_encounter_live`` semantics without its per-encounter query: a
            # scrim/stage-less encounter is always live, and a stage row that is
            # missing (or not yet published) answers exactly as it does there.
            live = stage is None or bool(stage.is_published)
            row = self._row(
                encounter,
                stage=stage,
                teams=teams,
                configs_by_kind=configs_by_kind,
                sessions_by_key=sessions_by_key,
                submissions=submissions,
                picked_per_session=picked_per_session,
                ready=ready_sides.get(encounter.id, set()),
                games=games_by_encounter.get(encounter.id, []),
                live=live,
                now=now,
            )
            if row is not None:
                rows.append(row)

        rows.sort(
            key=lambda row: (
                stages[row.stage_id].order if row.stage_id is not None and row.stage_id in stages else -1,
                row.round,
                row.encounter_id,
            )
        )
        return schemas.PregameRoomsRead(tournament_id=tournament_id, generated_at=now, rooms=rows)

    def _row(
        self,
        encounter: Encounter,
        *,
        stage: Stage | None,
        teams: dict[int, Team],
        configs_by_kind: dict[PickBanKind, list[PickBanConfig]],
        sessions_by_key: dict[tuple[int, str], PickBanSession],
        submissions: dict[int, list[PickBanSubmission]],
        picked_per_session: dict[int, int],
        ready: set[str],
        games: list[EncounterGame],
        live: bool,
        now: datetime,
    ) -> schemas.PregameRoomRow | None:
        """One encounter's row, or ``None`` when it has no room to show.

        No room means: no kind resolves to a config with a pool AND no session
        exists -- or the encounter belongs to a preview bracket nobody can act
        in yet (a session there would have had to be created before the stage
        was unpublished, so one existing keeps the row).
        """
        readiness = {"home": "home" in ready, "away": "away" in ready}
        both_ready = readiness["home"] and readiness["away"]
        # The cascade, resolved once per kind for this encounter's coordinate.
        resolved = {
            kind: pick_config(configs_by_kind.get(kind, ()), stage_id=encounter.stage_id, round=encounter.round)
            for kind in _KINDS
        }
        map_config = resolved[PickBanKind.MAP]
        map_session = sessions_by_key.get((encounter.id, PickBanKind.MAP.value))
        if map_config is None or not has_pool(map_config):
            # Nothing to wait for: an encounter with no map room plays whatever
            # map the captains name, so round 1 is "settled" from the start.
            map_settled = True
        else:
            map_settled = map_session is not None and picked_per_session.get(map_session.id, 0) >= 1

        summaries: dict[PickBanKind, schemas.PregameKindSummary | None] = {}
        for kind in _KINDS:
            summaries[kind] = self._kind_summary(
                encounter,
                kind,
                config=resolved[kind],
                pick_ban=sessions_by_key.get((encounter.id, kind.value)),
                submissions=submissions,
                live=live,
                both_ready=both_ready,
                map_round_one_settled=map_settled,
            )
        map_summary, hero_summary = summaries[PickBanKind.MAP], summaries[PickBanKind.HERO]
        any_session = any(sessions_by_key.get((encounter.id, kind.value)) is not None for kind in _KINDS)
        if map_summary is None and hero_summary is None:
            return None
        if not live and not any_session:
            return None

        live_games = [game for game in games if str(game.state) != EncounterGameState.CANCELLED]
        games_summary = schemas.PregameGamesSummary(
            total=len(live_games),
            confirmed=sum(1 for game in live_games if str(game.state) == EncounterGameState.CONFIRMED),
            disputed=sum(1 for game in live_games if str(game.state) == EncounterGameState.DISPUTED),
            awaiting_result=sum(1 for game in live_games if str(game.state) == EncounterGameState.AWAITING_RESULT),
        )
        phase = derive_phase(
            teams_known=encounter.home_team_id is not None and encounter.away_team_id is not None,
            done=(
                str(encounter.status) == EncounterStatus.COMPLETED
                or str(encounter.result_status) == EncounterResultStatus.CONFIRMED
            ),
            any_session=any_session,
            readiness_complete=both_ready,
            map_open=_kind_open(map_summary),
            hero_open=_kind_open(hero_summary),
            report_pending=bool(games_summary.awaiting_result or games_summary.disputed),
        )
        deadlines = [
            summary.deadline_at
            for summary in (map_summary, hero_summary)
            if summary is not None and summary.step_index is not None and summary.deadline_at is not None
        ]
        home_team = teams.get(encounter.home_team_id) if encounter.home_team_id is not None else None
        away_team = teams.get(encounter.away_team_id) if encounter.away_team_id is not None else None
        return schemas.PregameRoomRow(
            encounter_id=encounter.id,
            name=encounter.name,
            stage_id=encounter.stage_id,
            stage_name=stage.name if stage is not None else None,
            round=encounter.round,
            best_of=encounter.best_of,
            scheduled_at=encounter.scheduled_at,
            status=str(encounter.status),
            result_status=str(encounter.result_status) if encounter.result_status is not None else None,
            home_team=schemas.PregameRoomTeam(id=home_team.id, name=home_team.name) if home_team else None,
            away_team=schemas.PregameRoomTeam(id=away_team.id, name=away_team.name) if away_team else None,
            home_score=encounter.home_score,
            away_score=encounter.away_score,
            readiness=readiness,
            phase=phase,
            map=map_summary,
            hero=hero_summary,
            games=games_summary,
            attention=derive_attention(
                phase=phase,
                result_disputed=str(encounter.result_status) == EncounterResultStatus.DISPUTED,
                game_disputed=bool(games_summary.disputed),
                awaiting_choice=any(
                    summary is not None and summary.awaiting_choice for summary in (map_summary, hero_summary)
                ),
                overdue=any(deadline < now for deadline in deadlines),
                scheduled_at=encounter.scheduled_at,
                now=now,
            ),
        )

    def _kind_summary(
        self,
        encounter: Encounter,
        kind: PickBanKind,
        *,
        config: PickBanConfig | None,
        pick_ban: PickBanSession | None,
        submissions: dict[int, list[PickBanSubmission]],
        live: bool,
        both_ready: bool,
        map_round_one_settled: bool,
    ) -> schemas.PregameKindSummary | None:
        """One kind's room. ``None`` when the encounter plays no room of this
        kind at all; a summary with ``status=None`` is a configured room that
        has not opened, carrying the same reason the room itself would show."""
        if pick_ban is None:
            if config is None or not has_pool(config):
                return None
            return schemas.PregameKindSummary(
                reason=unavailable_reason_for(
                    encounter,
                    kind,
                    config,
                    live=live,
                    both_ready=both_ready,
                    map_round_one_settled=map_round_one_settled,
                )
            )
        rows = submissions.get(pick_ban.id, [])
        steps = resolved_steps(pick_ban)
        # A cancelled session's cursor is meaningless -- the step it stopped on
        # is never going to be taken -- so the board shows it as open nothing.
        cancelled = str(pick_ban.status) == MapVetoSessionStatus.CANCELLED
        step = pbr.current_step(steps, rows) if not cancelled else None
        acting: list[str] = []
        if step is not None:
            progress = pbr.step_progress(step, rows)
            acting = [side for side in step.acting_sides if not progress[side]["locked"]]
        return schemas.PregameKindSummary(
            status=str(pick_ban.status),
            # The round a step is open in. Without an open step the session is
            # either complete or holding for an opener choice, and the overview
            # says so through `status`/`awaiting_choice` rather than guessing a
            # round from the board (which would cost an entries read per room).
            current_round=step.round if step is not None else None,
            step_index=step.index if step is not None else None,
            step_count=len(steps),
            step_action=str(step.action) if step is not None else None,
            step_blind=bool(step.blind) if step is not None else False,
            acting_sides=acting,
            step_started_at=pick_ban.current_step_started_at,
            deadline_at=PickBanActionService.step_deadline(pick_ban, step) if step is not None else None,
            awaiting_choice=bool(pick_ban.awaiting_choice),
            paused_at=pick_ban.paused_at,
        )


def _kind_open(summary: schemas.PregameKindSummary | None) -> bool:
    """Whether this kind is what the room is currently waiting on: an active
    session with a step open, or one holding for an opener choice."""
    if summary is None or summary.status != "active":
        return False
    return summary.step_index is not None or summary.awaiting_choice


def derive_phase(
    *,
    teams_known: bool,
    done: bool,
    any_session: bool,
    readiness_complete: bool,
    map_open: bool,
    hero_open: bool,
    report_pending: bool,
) -> str:
    """Where a room stands, as ONE string the dashboard groups by.

    Ranked, not a state machine: a room can be several things at once (a map
    session open AND a disputed game of an earlier map), and the organizer wants
    the thing that is blocking progress. Teams first -- an unseeded slot blocks
    everything -- then a finished match (nothing left to run), then the gate the
    pre-game phase opens with, then the two pick-ban kinds in the order they are
    played, then the reports. ``idle`` is a room with nothing owed: configured,
    ready, and waiting on its captains to start playing.
    """
    if not teams_known:
        return "teams_unknown"
    if done:
        return "done"
    if not any_session and not readiness_complete:
        return "readiness"
    if map_open:
        return "map"
    if hero_open:
        return "hero"
    if report_pending:
        return "report"
    return "idle"


def derive_attention(
    *,
    phase: str,
    result_disputed: bool,
    game_disputed: bool,
    awaiting_choice: bool,
    overdue: bool,
    scheduled_at: datetime | None,
    now: datetime,
) -> list[str]:
    """The flags that make a row stand out, each one a thing only staff can
    clear: two captains disagreeing (per map or on the series), a round nobody
    has named an opener for, an expired step timer, and a match whose start time
    has passed with a captain still not ready."""
    flags: list[str] = []
    if game_disputed:
        flags.append("game_disputed")
    if result_disputed:
        flags.append("result_disputed")
    if awaiting_choice:
        flags.append("awaiting_choice")
    if overdue:
        flags.append("overdue")
    if phase == "readiness" and scheduled_at is not None and _aware(scheduled_at) < now:
        flags.append("late_not_ready")
    return flags


def _aware(moment: datetime) -> datetime:
    """Stored timestamps come back naive on some drivers; they are UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


pregame_rooms_service = PregameRoomsService()

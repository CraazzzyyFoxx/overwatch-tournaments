"""Find a pickup mix round's match by its players and file it as the round's match import.

Every round recorded within :data:`fetch.FETCH_WINDOW` in a discipline whose module declares a ``match_searchers``
entry gets one ``stats.match_search`` row, enrolled by this worker tick (a missed tick or a restart loses nothing).
The tick asks the module's searcher for the matches any seated player's linked account (the discipline's
``identity_provider``) played between the round's Start, :data:`START_SLACK` earlier, and its Record. A match is the
round's when every round team has at least half of its linked members on one distinct side of it and none on another
(:func:`fitting`); one another game of the workspace already holds is not. Exactly one -> its id is filed through
:func:`fetch.submit_fetch` like a host's (``found``); several -> ``not_found`` (``ambiguous``); none -> retried with
the fetch backoff until the window closes (``not_found``). A round that got statistics or a live/done filed id another
way stops searching (``stopped``); filing an id stops it at once (``submit_fetch``). The round's organizer may start it
again (:func:`restart_search`): a fresh window, also for a round recorded before the enrolment window.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import permutations
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.disciplines.ingest import MatchCandidate, MatchFetchFailed, MatchFetchNotReady, MatchQuery, MatchSearcher
from shared.models import MatchSearch, MatchSearchStatus
from shared.observability import observe_scheduled_job
from shared.repository.encounter import EncounterGameRepository, EncounterTeamRepository
from shared.repository.match_fetch import MatchFetchRepository
from shared.repository.match_search import MatchSearchRepository
from shared.repository.tournament import EncounterRepository
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
    renew_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.services.ingest import fetch

__all__ = ("fitting", "restart_search", "run_search_tick", "searcher_of", "shutdown_scheduler", "start_scheduler")

#: A lobby is often readied before the host presses Start.
START_SLACK = timedelta(minutes=5)
#: Its own lease: the fetch tick runs beside it on the same workers.
LEADER_LOCK_KEY = "stats:match_search:leader"
_DUE_PER_TICK = 20
_REASON_LIMIT = 500

_encounters = EncounterRepository()
_fetches = MatchFetchRepository()
_games = EncounterGameRepository()
_teams = EncounterTeamRepository()
_searches = MatchSearchRepository()
_scheduler = IntervalScheduler(job_id="match_search_tick", label="Match search tick")


def searcher_of(discipline: str) -> tuple[str, MatchSearcher, str] | None:
    """``(source kind, searcher, identity provider)`` of a discipline that can find a round's match, else ``None``."""
    spec = DISCIPLINES.get(discipline)
    if spec is None or spec.identity_provider is None:
        return None
    for kind, searcher in spec.match_searchers.items():
        if kind in spec.match_fetchers:
            return kind, searcher, str(spec.identity_provider)
    return None


def fitting(teams: Sequence[Sequence[frozenset[str]]], candidates: Sequence[MatchCandidate]) -> list[str]:
    """The candidates the round played: ``teams`` are the round's teams, each a list of its linked members' account
    sets. A candidate fits when some assignment of the round's teams to distinct sides of it finds at least half of
    every team's members on its side (a private profile hides a player, so not all of them) and none on another one
    (the same players split otherwise are another round)."""

    def holds(members: Sequence[frozenset[str]], side: frozenset[str], elsewhere: frozenset[str]) -> bool:
        return 2 * sum(1 for accounts in members if accounts & side) >= len(members) and not any(
            accounts & elsewhere for accounts in members
        )

    def fits(candidate: MatchCandidate) -> bool:
        everyone = frozenset().union(*candidate.teams)
        return any(
            all(holds(members, side, everyone - side) for members, side in zip(teams, sides, strict=True))
            for sides in permutations(candidate.teams, len(teams))
        )

    return [candidate.external_id for candidate in candidates if fits(candidate)]


async def _enroll(session: AsyncSession, discipline: str, now: datetime) -> None:
    """One row, due at once, for each round of the discipline recorded within the window that has none yet."""
    encounter = models.Encounter
    rounds = (
        sa.select(
            encounter.workspace_id,
            encounter.discipline,
            encounter.id,
            sa.literal(now, type_=sa.DateTime(timezone=True)),
        )
        .join(models.CustomGameRound, models.CustomGameRound.encounter_id == encounter.id)
        .where(
            encounter.discipline == discipline,
            encounter.started_at.is_not(None),
            encounter.confirmed_at >= now - fetch.FETCH_WINDOW,
            ~sa.exists().where(MatchSearch.encounter_id == encounter.id),
        )
    )
    await _searches.enroll(session, rounds)


async def _locked(session: AsyncSession, search_id: int) -> MatchSearch | None:
    row = await _searches.get_for_update(session, search_id)
    return row if row is not None and row.status == MatchSearchStatus.PENDING else None


async def _settle(
    session_factory: Any,
    search_id: int,
    now: datetime,
    *,
    retry: str | None = None,
    outcome: MatchSearchStatus | None = None,
    reason: str | None = None,
) -> None:
    """Record an attempt: ``outcome`` ends the row, ``retry`` backs it off until the window closes."""
    async with session_factory() as session:
        row = await _locked(session, search_id)
        if row is None:
            return
        row.attempts += 1
        if outcome is None and now - row.created_at >= fetch.FETCH_WINDOW:
            outcome, reason = MatchSearchStatus.NOT_FOUND, "not_found_in_window"
        if outcome is not None:
            row.status, row.last_error = outcome, reason[:_REASON_LIMIT] if reason else None
        else:
            row.next_attempt_at, row.last_error = now + fetch.next_delay(row.attempts), retry
        await session.commit()


async def _settled(session: AsyncSession, encounter_id: int) -> bool:
    """The round has statistics or a live/done filed id; one that gave up leaves the round to the search."""
    return bool(
        await session.scalar(
            sa.select(
                sa.or_(
                    sa.exists().where(models.StatsMatch.encounter_id == encounter_id),
                    sa.exists().where(
                        models.MatchFetch.hint_encounter_id == encounter_id,
                        models.MatchFetch.status != models.MatchFetchStatus.FAILED,
                    ),
                )
            )
        )
    )


async def _round(
    session: AsyncSession, row: MatchSearch, provider: str
) -> tuple[int, MatchQuery, list[list[frozenset[str]]]] | MatchSearchStatus:
    """The round's game, query and linked teams, or the outcome that ends the search before asking anyone."""
    # A pickup round is mix-owned, so the tournament-only ``get`` would hide it.
    encounter = await _encounters.get_any_owner(session, row.encounter_id)
    games = await _games.list_for_encounter(session, row.encounter_id)
    if encounter is None or encounter.started_at is None or not games or await _settled(session, row.encounter_id):
        return MatchSearchStatus.STOPPED
    member = models.EncounterTeamMember
    linked = await session.execute(
        sa.select(member.encounter_team_id, member.workspace_member_id, models.SocialAccount.username_normalized)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == member.workspace_member_id)
        .join(models.SocialAccount, models.SocialAccount.user_id == models.WorkspaceMember.player_id)
        .where(
            member.encounter_id == row.encounter_id,
            member.active.is_(True),
            models.SocialAccount.provider == provider,
            models.SocialAccount.username_normalized.is_not(None),
        )
    )
    accounts: dict[int, dict[int, set[str]]] = {}
    for team_id, member_id, account in linked:
        accounts.setdefault(team_id, {}).setdefault(member_id, set()).add(account)
    teams = [
        [frozenset(member_accounts) for member_accounts in accounts.get(team.id, {}).values()]
        for team in await _teams.list_active(session, row.encounter_id)
    ]
    if len(teams) < 2 or not all(teams):
        return MatchSearchStatus.NOT_FOUND
    query = MatchQuery(
        identities=frozenset().union(*(member_accounts for team in teams for member_accounts in team)),
        started_from=encounter.started_at - START_SLACK,
        started_until=encounter.confirmed_at or row.created_at,
    )
    return games[0].id, query, teams


async def _attempt(search_id: int, *, session_factory: Any, now: datetime) -> None:
    async with session_factory() as session:
        row = await _searches.get(session, search_id)
        if row is None or row.status != MatchSearchStatus.PENDING:
            return
        found = searcher_of(row.discipline)
        workspace_id, discipline, encounter_id = row.workspace_id, row.discipline, row.encounter_id
        known = await _round(session, row, found[2]) if found is not None else MatchSearchStatus.STOPPED
    if isinstance(known, MatchSearchStatus):
        reason = "no_linked_accounts" if known == MatchSearchStatus.NOT_FOUND else None
        return await _settle(session_factory, search_id, now, outcome=known, reason=reason)
    assert found is not None  # a round only reaches the search through a discipline that has one
    kind, searcher, _provider = found
    game_id, query, teams = known
    try:
        candidates = await searcher(query)
    except MatchFetchNotReady as exc:
        return await _settle(session_factory, search_id, now, retry=str(exc)[:_REASON_LIMIT] or "not_ready")
    except MatchFetchFailed as exc:
        return await _settle(
            session_factory, search_id, now, outcome=MatchSearchStatus.NOT_FOUND, reason=str(exc) or "search_failed"
        )
    except Exception as exc:
        logger.exception("Match search {} ({}) raised; retried", search_id, kind)
        return await _settle(session_factory, search_id, now, retry=type(exc).__name__)
    async with session_factory() as session:
        row = await _locked(session, search_id)
        if row is None:
            return None
        ours = [
            external_id
            for external_id in fitting(teams, candidates)
            if not await _fetches.active_elsewhere(
                session,
                workspace_id=workspace_id,
                source_kind=kind,
                external_id=external_id,
                encounter_game_id=game_id,
            )
        ]
        if len(ours) > 1:
            row.attempts += 1
            row.status, row.last_error = MatchSearchStatus.NOT_FOUND, f"ambiguous: {', '.join(ours)}"[:_REASON_LIMIT]
            await session.commit()
            return None
        if ours:
            row.attempts += 1
            row.status, row.external_id, row.last_error = MatchSearchStatus.FOUND, ours[0], None
            await session.flush()
            try:
                # Commits the row with the request: the round's import, as if its host had filed the id.
                await fetch.submit_fetch(
                    session,
                    data={
                        "workspace_id": workspace_id,
                        "discipline": discipline,
                        "tournament_id": None,
                        "encounter_id": encounter_id,
                        "encounter_game_id": game_id,
                        "external_id": ours[0],
                    },
                    requested_by_user_id=None,
                )
                return None
            except HTTPException as exc:  # another game took the match meanwhile
                await session.rollback()
                return await _settle(session_factory, search_id, now, retry=str(exc.detail)[:_REASON_LIMIT])
    return await _settle(session_factory, search_id, now, retry="no_match_yet")


async def restart_search(session: AsyncSession, target: dict[str, Any]) -> None:
    """Look the round up by its players again (``target`` as :func:`fetch.mix_round_target` names it, so already
    authorized): a fresh window, due at the next tick; a search still looking is left as it is. Refused for a game
    without a searcher, and for a round that has statistics or a live/done filed id -- nothing left to look for."""
    if searcher_of(target["discipline"]) is None:
        raise HTTPException(
            status_code=422,
            detail=[ApiExc(code="unsupported_match_search", msg="This game's matches cannot be found by players")],
        )
    encounter_id = target["encounter_id"]
    if await _settled(session, encounter_id):
        raise HTTPException(
            status_code=409,
            detail=[ApiExc(code="match_search_settled", msg="This match already has statistics or a filed id")],
        )
    await _searches.restart(
        session,
        workspace_id=target["workspace_id"],
        discipline=target["discipline"],
        encounter_id=encounter_id,
        now=datetime.now(UTC),
    )
    await session.commit()


async def _run_discipline(discipline: str, *, redis: Any, session_factory: Any, now: datetime) -> int:
    """Enroll the discipline's new rounds and try its due searches, under the discipline's own lease."""
    try:
        token = await acquire_distributed_lock(
            redis, f"{LEADER_LOCK_KEY}:{discipline}", ttl_seconds=fetch.LEASE_SECONDS, acquire_timeout_seconds=0.5
        )
    except DistributedLockUnavailable:
        return 0
    tried = 0
    try:
        async with session_factory() as session:
            await _enroll(session, discipline, now)
            await session.commit()
            due = await _searches.due_ids(session, now=now, limit=_DUE_PER_TICK, discipline=discipline)
        for search_id in due:
            if not await renew_distributed_lock(redis, token, ttl_seconds=fetch.LEASE_SECONDS):
                logger.warning("Match search lease for {} lost; the pass stops", discipline)
                break
            try:
                await _attempt(search_id, session_factory=session_factory, now=now)
            except Exception:
                logger.exception("Match search {} failed unexpectedly; retried next tick", search_id)
            tried += 1
        return tried
    except Exception:
        logger.exception("Match search pass for {} failed", discipline)
        return tried
    finally:
        await release_distributed_lock(redis, token)


async def run_search_tick(
    *,
    redis: Any,
    disciplines: Sequence[str],
    session_factory: Any = db.async_session_maker,
    now: datetime | None = None,
) -> int:
    """One pass per selected discipline with a searcher; returns how many searches were tried."""
    moment = now or datetime.now(UTC)
    async with observe_scheduled_job("match_search_tick"):
        tried = 0
        for code in sorted(set(disciplines)):
            if searcher_of(code) is not None:
                tried += await _run_discipline(code, redis=redis, session_factory=session_factory, now=moment)
        return tried


def start_scheduler(*, redis: Any, disciplines: Sequence[str]) -> None:
    if not any(searcher_of(code) is not None for code in disciplines):
        return
    _scheduler.start(
        run_search_tick, seconds=fetch.TICK_SECONDS, kwargs={"redis": redis, "disciplines": list(disciplines)}
    )


def shutdown_scheduler() -> None:
    _scheduler.shutdown()

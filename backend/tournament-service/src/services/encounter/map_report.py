"""Per-map result confirmation: two independent captain reports for ONE map
of a series, reconciled the moment both arrive. This is what the pick-ban
engine's progressive rounds wait on — closes the gap documented in
``docs/plans/2026-08-09-generic-pickban-engine.md`` §5.5/§5.6/Decision 9-10
(nothing else in the system reports "this map just finished" mid-series;
``EncounterCaptainReport`` only fires once, at series end).

Agreement -> upserts a ``matches.match`` row (``source=captain_report``),
increments ``Encounter.home_score``/``away_score`` (never touches
``result_status`` — that stays the exclusive job of
``captain.set_encounter_result``), marks the map's ``PickBanEntry`` `played`
in both the map and hero pick-ban sessions, and advances both to their next
round. Disagreement -> leaves both reports standing for an admin to resolve
(mirrors ``captain.set_encounter_result``'s own reconciliation, applied here
at map granularity instead of series granularity).

A scrim room runs this same loop for the progression only: no ``matches.match``
row is written for one, because the score is there to name the next map's opener
rather than to record a result nobody publishes
(``docs/plans/2026-08-12-scrim-rooms.md``).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import MapPoolEntryStatus, MatchSource, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.user import User
from shared.models.matches.match import Match
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_report import EncounterMapReport
from shared.models.tournament.pick_ban import PickBanEntry, PickBanSession
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.repository import EncounterMapReportRepository, PickBanEntryRepository
from shared.services import pick_ban_engine as engine
from shared.services.bracket.usability import is_encounter_live
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from shared.services.scrim_scope import is_scrim_container
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.encounter.realtime_commit import emit_pick_ban_update


class MapReportService:
    """The mid-series, per-map half of captain reporting."""

    def __init__(
        self,
        *,
        report_repo: EncounterMapReportRepository = EncounterMapReportRepository(),
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
    ) -> None:
        self.report_repo = report_repo
        self.entry_repo = entry_repo

    async def _notify_dispute(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        map_id: int,
        map_index: int,
        reporter_auth_user_id: int | None,
    ) -> None:
        """Both captains, not just the opponent.

        A contradiction needs one of the two to correct their claim, and from
        inside the reconciliation neither side is known to be the wrong one -- the
        captain who just reported has as much to answer for as the one who
        reported first. Telling only the opponent would leave the report standing
        unexamined on the half that may be mistaken.

        One query for the pair, not one per side; a team with no captain, or one
        captained by a shadow player (``players.user.auth_user_id IS NULL``),
        simply drops out of the result.
        """
        result = await session.execute(
            sa.select(User.auth_user_id)
            .join(Team, Team.captain_id == User.id)
            .where(
                Team.id.in_([encounter.home_team_id, encounter.away_team_id]),
                User.auth_user_id.is_not(None),
            )
        )
        recipients = [int(value) for value in result.scalars().all()]
        # The organizer whose bracket this encounter belongs to: it owns the
        # rows, so its operators can retire them. One scalar, and only on the
        # dispute branch -- ``Encounter`` carries the tournament, not the tenant.
        workspace_id = await session.scalar(
            sa.select(Tournament.workspace_id).where(Tournament.id == encounter.tournament_id)
        )
        for recipient in recipients:
            await notify(
                session,
                kind="encounter.report_disputed",
                recipient_auth_user_id=recipient,
                source_workspace_id=int(workspace_id) if workspace_id is not None else None,
                actor_auth_user_id=reporter_auth_user_id,
                payload={
                    "encounter_id": encounter.id,
                    "tournament_id": encounter.tournament_id,
                    "map_id": map_id,
                    "map_index": map_index,
                },
            )

    async def _pending_play(
        self, session: AsyncSession, map_pick_ban: PickBanSession | None, map_id: int
    ) -> tuple[int, PickBanEntry | None]:
        """Which play of ``map_id`` this report is for: its 1-based position in the
        series and the pool entry that holds it.

        A series may play the same map twice, and then the map alone names neither
        the report nor the entry to flip `played`. The report belongs to the FIRST
        play still awaiting a result -- exactly the map the room's result phase is
        showing. With every play already `played` (an amendment of an already-agreed
        report) it belongs to the LAST one, so the correction lands on the map it
        was typed against instead of on an earlier play of it.

        ``(0, None)`` when this encounter has no map pick-ban session, or its pool
        never settled this map: there is no series position to speak of.
        """
        if map_pick_ban is None:
            return 0, None
        entries = await self.entry_repo.list_by_session(session, map_pick_ban.id)
        settled = engine.settled_in_order(list(entries))
        plays = [(index, entry) for index, entry in enumerate(settled, start=1) if entry.item_id == map_id]
        if not plays:
            return 0, None
        awaiting = [(index, entry) for index, entry in plays if entry.status != MapPoolEntryStatus.PLAYED.value]
        return awaiting[0] if awaiting else plays[-1]

    async def submit_map_report(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        map_id: int,
        team_id: int,
        reporter_user_id: int | None,
        home_score: int,
        away_score: int,
    ) -> dict:
        """Upsert this captain's report for ``map_id``; reconcile if both sides
        have now reported. Returns
        ``{"disputed": bool, "resolved": bool, "match_id": int | None}``."""
        if not await is_encounter_live(session, encounter):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stage bracket is a preview and is not active yet; wait for the organizer to activate it",
            )
        map_pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter.id, PickBanKind.MAP)
        map_index, entry = await self._pending_play(session, map_pick_ban, map_id)

        # Both sides of the slot in ONE read: reconciliation needs the opponent's row
        # anyway, and it cannot change under us inside this transaction.
        slot_reports = await self.report_repo.list_for_map_slot(
            session, encounter_id=encounter.id, map_id=map_id, map_index=map_index
        )
        other_team_id = encounter.away_team_id if team_id == encounter.home_team_id else encounter.home_team_id
        row = next((report for report in slot_reports if report.team_id == team_id), None)
        other_row = next((report for report in slot_reports if report.team_id == other_team_id), None)

        if row is None:
            row = EncounterMapReport(encounter_id=encounter.id, map_id=map_id, map_index=map_index, team_id=team_id)
            session.add(row)
        row.reporter_user_id = reporter_user_id
        row.home_score = home_score
        row.away_score = away_score
        # Unconditional, on both branches below: the opponent's tile only flips
        # from "not reported" to "sealed" on this signal, and the FIRST
        # captain's report -- the one that resolves nothing -- is exactly the
        # case that used to commit silently. Both topics, because the room
        # refetches map and hero state together: two phases of one loop.
        await emit_pick_ban_update(session, encounter.id)
        await emit_pick_ban_update(session, encounter.id, kind=PickBanKind.HERO.value)
        await session.flush()

        pair = engine.MapReportPair(
            home_report=(row.home_score, row.away_score)
            if team_id == encounter.home_team_id
            else ((other_row.home_score, other_row.away_score) if other_row else None),
            away_report=(row.home_score, row.away_score)
            if team_id == encounter.away_team_id
            else ((other_row.home_score, other_row.away_score) if other_row else None),
        )
        reconciliation = engine.reconcile_map_reports(pair)

        if reconciliation.resolved is None:
            if reconciliation.disputed:
                await self._notify_dispute(
                    session,
                    encounter,
                    map_id=map_id,
                    map_index=map_index,
                    reporter_auth_user_id=reporter_user_id,
                )
            await session.commit()
            return {"disputed": reconciliation.disputed, "resolved": False, "match_id": None}

        resolved_home, resolved_away = reconciliation.resolved
        # `played` is the once-per-map transition, and the series score rides it:
        # a captain amending an already-agreed report (or any other re-entry) must
        # correct the map, never count it twice.
        already_played = entry is not None and entry.status == MapPoolEntryStatus.PLAYED.value

        # A scrim's per-map score exists to run the SERIES, not to record it: it is
        # what tells the engine who won and therefore who opens the next map's bans
        # (``first_ban_rotation``, result-dependent in both real rulebooks). None of
        # the bookkeeping that surrounds that is wanted -- a scrim has no result to
        # publish and no organizer reading it -- so no ``matches.match`` row is
        # written for one. Everything the loop itself needs still happens below:
        # the entry flips to ``played``, the series score advances, and the next
        # round opens. See docs/plans/2026-08-12-scrim-rooms.md.
        match: Match | None = None
        if not await is_scrim_container(session, encounter.tournament_id):
            match = await pick_ban_session_service.find_series_match(session, encounter.id, map_id, map_index)
            if match is None:
                match = Match(
                    encounter_id=encounter.id,
                    map_id=map_id,
                    map_index=map_index or None,
                    home_team_id=encounter.home_team_id,
                    away_team_id=encounter.away_team_id,
                    home_score=resolved_home,
                    away_score=resolved_away,
                    time=None,
                    log_name=None,
                    source=MatchSource.CAPTAIN_REPORT.value,
                )
                session.add(match)
            else:
                # Claim the position for this play, so a second play of the same map
                # writes its own row instead of adopting this one.
                match.map_index = map_index or None
                # A log arrived first (or a re-report after a dispute correction):
                # never downgrade a real parsed log back to a captain claim, but do
                # let the captains' agreement correct a captain-report row.
                if match.source == MatchSource.CAPTAIN_REPORT.value:
                    match.home_score = resolved_home
                    match.away_score = resolved_away

        played_round: int | None = None
        if entry is not None:
            entry.status = MapPoolEntryStatus.PLAYED.value
            played_round = entry.round

        if not already_played:
            encounter.home_score = (encounter.home_score or 0) + (1 if resolved_home > resolved_away else 0)
            encounter.away_score = (encounter.away_score or 0) + (1 if resolved_away > resolved_home else 0)

        if played_round is not None and map_pick_ban is not None:
            # Only the MAP session advances here, and only while the series still
            # has a map to play: the next map's bans open on this result. That
            # map's HERO round opens later, once the map itself is picked --
            # `pick_ban_session.sync_hero_rounds`, because heroes are banned for a
            # known map, not for a map that is still being vetoed.
            winner = engine.winner_side(resolved_home, resolved_away)
            if not engine.series_decided(encounter.home_score or 0, encounter.away_score or 0, encounter.best_of):
                try:
                    await pick_ban_session_service.advance_to_next_round(
                        session, map_pick_ban, completed_round=played_round, winner=winner, commit=False
                    )
                except engine.RotationNeedsChoice:
                    map_pick_ban.awaiting_choice = True
                    map_pick_ban.pending_loser_side = "away" if winner == "home" else "home"
                    await session.flush()

        # Unlike a veto/ban, an AGREED report moves the encounter's own score and
        # writes the match row behind it -- the public encounter read is stale the
        # moment this commits. The scrim branch above writes no match, but the
        # encounter score still moved, so this is unconditional.
        await emit(
            session,
            scope=Scope.tournament(encounter.tournament_id),
            invalidates=[Resource.TOURNAMENT_ENCOUNTERS],
            entity_ids={"encounter_ids": [encounter.id]},
        )

        await session.commit()
        # ``match_id`` is null for a scrim: there is no row to point at. The client
        # only uses it to link a parsed match, which a scrim never has.
        return {"disputed": False, "resolved": True, "match_id": match.id if match is not None else None}


map_report_service = MapReportService()

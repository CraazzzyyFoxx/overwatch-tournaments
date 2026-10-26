"""Encounter upsert from Challonge matches: plan, conflict checks, the locked write, advancement links."""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.domain.encounter_naming import build_encounter_name
from shared.domain.encounter_scoring import WINS_END_FORMULA
from shared.services.encounter.participants import active_teams, place_team, vacate_slot
from shared.services.encounter.result import apply_result, lock_encounter
from src import schemas
from src.services.challonge.stage_refs import StageRefs
from src.services.challonge.sync._types import (
    _ChallongeLinkSpec,
    _ImportSource,
    _MatchLookup,
    _source_lookup_key,
    _TeamLookup,
    _UpsertPlan,
    _UpsertResult,
)
from src.services.challonge.sync.helpers import (
    _HELD_RESULT_STATUSES,
    _encounter_status_from_challonge,
    _encounter_sync_snapshot,
    _has_local_decision,
    _iter_challonge_link_specs,
    _parse_scores,
    _resolve_group_for_match,
)
from src.services.notifications.lifecycle import advance_and_announce, after_encounter_teams_changed


def _places(totals: Mapping[int, float]) -> dict[int, int]:
    """Competition ranking over a scoreline: 2-0 -> 1, 2; 1-1 -> 1, 1."""
    places: dict[int, int] = {}
    place, previous = 0, None
    for index, (key, value) in enumerate(sorted(totals.items(), key=lambda pair: (-pair[1], pair[0])), 1):
        if value != previous:
            place, previous = index, value
        places[key] = place
    return places


async def _reseat(
    session: AsyncSession,
    encounter: models.Encounter,
    team_ids: Sequence[int | None],
    names: Mapping[int, str],
) -> bool:
    """Make the encounter's seats match ``team_ids`` -- index ``i`` is slot ``i + 1``.

    Challonge's participant 1 and 2 ARE slots 1 and 2; there is no orientation
    to preserve. A seat that changes hands is retired and a new participation
    written, never updated in place, so the games the old occupant played
    stay attached to the row that played them. Returns whether anything moved.
    """
    changed = False
    current = {seat.slot: seat for seat in await active_teams(session, encounter.id)}
    for index, team_id in enumerate(team_ids, 1):
        seat = current.get(index)
        if seat is not None and seat.team_id == team_id:
            continue
        if seat is not None:
            await vacate_slot(session, encounter, slot=index)
            changed = True
        if team_id is not None:
            await place_team(
                session,
                encounter,
                slot=index,
                team_id=team_id,
                name=names.get(team_id, "TBD"),
                seed=None,
                members=(),
            )
            changed = True
    return changed


async def _write_import_result(
    session: AsyncSession,
    encounter: models.Encounter,
    scores: Sequence[float],
) -> None:
    """Record Challonge's scoreline as this encounter's standing.

    Source ``import``: a remote system decided it, which is what stops a later
    ``refresh_from_games`` from overwriting it with whatever the local game rows
    add up to. ``actor_user_id`` stays NULL for the same reason.
    """
    seats = await active_teams(session, encounter.id)
    totals = {seat.id: float(score) for seat, score in zip(seats, scores, strict=False)}
    await apply_result(
        session,
        encounter,
        source=enums.EncounterResultSource.IMPORT,
        totals=totals,
        placements=_places(totals),
        action=enums.EncounterResultAuditAction.IMPORT,
        audit_source="challonge",
        actor_user_id=None,
        reason=None,
    )


class EncounterUpsertMixin:
    """``ChallongeSyncService``'s per-match import half; the service owns the repositories and collaborators."""

    async def _scoring_rule_id(self, session: AsyncSession, tournament: models.Tournament, refs: StageRefs) -> int:
        """The rule an imported encounter is scored by.

        The stage's own when the match resolved to one -- so an imported bracket
        is scored exactly like a locally generated one. A match with no stage
        gets the tournament's own ``wins`` rule, created once and reused, because
        ``encounter.scoring_rule_id`` is NOT NULL and an import must not invent a
        rule row per match.
        """
        if refs.stage_id is not None:
            rule_id = await session.scalar(
                sa.select(models.Stage.scoring_rule_id).where(models.Stage.id == refs.stage_id)
            )
            if rule_id is not None:
                return rule_id
        # Looked up rather than cached on the service: this is a singleton shared
        # by every workspace, and a rule belongs to exactly one of them.
        existing = await session.scalar(
            sa.select(models.ScoringRule.id)
            .where(
                models.ScoringRule.workspace_id == tournament.workspace_id,
                models.ScoringRule.preset == "wins",
                models.ScoringRule.game_formula == "win",
            )
            .order_by(models.ScoringRule.id)
            .limit(1)
        )
        if existing is not None:
            return existing
        rule = models.ScoringRule(
            workspace_id=tournament.workspace_id,
            preset="wins",
            game_formula="win",
            end_formula=WINS_END_FORMULA,
        )
        await self.scoring_rule_repo.create(session, rule)
        return rule.id

    async def _upsert_encounter_from_challonge(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        match: schemas.ChallongeMatch,
        *,
        match_lookup: _MatchLookup,
        team_lookup: _TeamLookup,
    ) -> _UpsertResult:
        """One match, read then written. ``import_tournament`` runs the two halves itself, so a match that changed
        nothing never opens a savepoint."""
        plan = await self._plan_upsert(
            session, tournament, source, match, match_lookup=match_lookup, team_lookup=team_lookup
        )
        if isinstance(plan, _UpsertResult):
            return plan
        return await self._apply_upsert(session, tournament, source, match, plan, match_lookup=match_lookup)

    async def _plan_upsert(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        match: schemas.ChallongeMatch,
        *,
        match_lookup: _MatchLookup,
        team_lookup: _TeamLookup,
    ) -> _UpsertResult | _UpsertPlan:
        """Reads only: an ``error`` or ``skipped`` result, or the plan of a match that will write."""
        encounter = match_lookup.get(source, match.id)
        stage = _resolve_group_for_match(tournament, source, match)
        home_team_id = team_lookup.resolve(source, None, match.player1_id)
        away_team_id = team_lookup.resolve(source, None, match.player2_id)
        missing_team_mapping = tuple(
            challonge_id
            for challonge_id, team_id in (
                (match.player1_id, home_team_id),
                (match.player2_id, away_team_id),
            )
            if challonge_id is not None and team_id is None
        )
        if encounter is None and missing_team_mapping:
            return _UpsertResult(
                action="error",
                error=(
                    "Missing Challonge team mapping for participant(s): "
                    + ", ".join(str(challonge_id) for challonge_id in missing_team_mapping)
                ),
                missing_participant_ids=missing_team_mapping,
            )

        home_team = team_lookup.teams_by_id.get(home_team_id) if home_team_id is not None else None
        away_team = team_lookup.teams_by_id.get(away_team_id) if away_team_id is not None else None
        missing_local_team = [
            str(team_id)
            for team_id, team in (
                (home_team_id, home_team),
                (away_team_id, away_team),
            )
            if team_id is not None and team is None
        ]
        if encounter is None and missing_local_team:
            return _UpsertResult(
                action="error",
                error="Mapped local team(s) not found: " + ", ".join(missing_local_team),
            )

        home_score, away_score = _parse_scores(match.scores_csv)
        status = _encounter_status_from_challonge(match.state)
        refs = await self.structure._resolve_stage_refs_for_match(session, tournament, source, stage, match)
        if encounter is None and home_team_id is not None and away_team_id is not None:
            # A locally generated bracket may already have an Encounter sitting in
            # this exact slot (same stage, round, team pair) with no Challonge
            # mapping yet — adopt it instead of creating a sibling next to it.
            encounter = match_lookup.claim_unlinked(refs.stage_id, match.round, frozenset({home_team_id, away_team_id}))
        names = {
            team_id: team.name
            for team_id, team in ((home_team_id, home_team), (away_team_id, away_team))
            if team_id is not None and team is not None
        }
        teams_mapped = not missing_team_mapping and not missing_local_team
        if encounter is None:
            return _UpsertPlan(
                encounter=None,
                team_ids=(home_team_id, away_team_id),
                scores=(home_score, away_score),
                status=status,
                refs=refs,
                names=names,
                teams_mapped=teams_mapped,
            )

        position = await self.bracket_encounter_repo.get_position(session, encounter.id)
        seats = await active_teams(session, encounter.id)
        after = {
            "id": encounter.id,
            "team_ids": [home_team_id, away_team_id],
            "scores": [float(home_score), float(away_score)],
            "round": match.round,
            "status": status.value,
            "stage_id": refs.stage_id,
            "stage_item_id": refs.stage_item_id,
        }
        name = build_encounter_name([names.get(home_team_id), names.get(away_team_id)])
        seat_teams = {seat.slot: seat.team_id for seat in seats}
        # Everything the update would write is already here -- seats, running
        # scores, status, bracket slot, match mapping: no savepoint, no row lock,
        # no flush, no log row, no recompute. A held result still goes on to
        # report its conflict.
        if (
            encounter.result_status not in _HELD_RESULT_STATUSES
            and encounter.status == status
            and position is not None
            and (position.round, position.stage_id, position.stage_item_id)
            == (match.round, refs.stage_id, refs.stage_item_id)
            and [seat.score for seat in seats] == after["scores"][: len(seats)]
            and (
                not teams_mapped
                or ([seat_teams.get(1), seat_teams.get(2)] == after["team_ids"] and encounter.name == name)
            )
            and (source.source_id is None or (source.source_id, match.id) in match_lookup.mapped_keys)
        ):
            return _UpsertResult(action="skipped", encounter=encounter)
        return _UpsertPlan(
            encounter=encounter,
            team_ids=(home_team_id, away_team_id),
            scores=(home_score, away_score),
            status=status,
            refs=refs,
            names=names,
            teams_mapped=teams_mapped,
            after=after,
        )

    async def _apply_upsert(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        match: schemas.ChallongeMatch,
        plan: _UpsertPlan,
        *,
        match_lookup: _MatchLookup,
    ) -> _UpsertResult:
        """The writes of one planned match: create its encounter, or update the existing one under its row lock."""
        encounter = plan.encounter
        home_team_id, away_team_id = plan.team_ids
        home_score, away_score = plan.scores
        status, refs, names = plan.status, plan.refs, plan.names
        if encounter is None:
            initial_status = enums.EncounterStatus.OPEN if status == enums.EncounterStatus.COMPLETED else status
            encounter = models.Encounter(
                name=build_encounter_name([names.get(home_team_id), names.get(away_team_id)]),
                workspace_id=tournament.workspace_id,
                discipline=tournament.discipline,
                tournament_id=tournament.id,
                scoring_rule_id=await self._scoring_rule_id(session, tournament, refs),
                slot_count=2,
                status=initial_status,
            )
            await self.encounter_repo.create(session, encounter)
            await self.bracket_encounter_repo.create(
                session,
                models.BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=tournament.id,
                    stage_id=refs.stage_id,
                    stage_item_id=refs.stage_item_id,
                    round=match.round,
                ),
            )
            await _reseat(session, encounter, [home_team_id, away_team_id], names)
            match_lookup.set(source, match.id, encounter)
            # challonge_match_mapping is the sole persistence of the encounter↔match link.
            await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)

            newly_completed = status == enums.EncounterStatus.COMPLETED
            if newly_completed:
                # A match can already be complete on the Challonge side the first
                # time we see it (e.g. importing a finished tournament) — route it
                # through the single result writer so ``result_status``,
                # ``confirmed_at``, the journal and ``status`` stay in step
                # (ck_encounter_confirmed_completed).
                await _write_import_result(session, encounter, [home_score, away_score])
            return _UpsertResult(action="created", encounter=encounter, newly_completed=newly_completed)

        after, teams_mapped = plan.after, plan.teams_mapped
        name = build_encounter_name([names.get(home_team_id), names.get(away_team_id)])

        # The background sync races captain submits: the row is ours before any
        # decision is read off it or any seat or standing is written. The plan's
        # reads only decided that something changed; a result a captain committed
        # since then is judged here, on the encounter (``lock_encounter`` re-reads
        # it), seats and position read again under the lock -- never on the plan's.
        await lock_encounter(session, encounter.id)
        position = (
            await session.execute(
                sa.select(models.BracketEncounter)
                .where(models.BracketEncounter.encounter_id == encounter.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        seats = list(
            (
                await session.execute(
                    sa.select(models.EncounterTeam)
                    .where(models.EncounterTeam.encounter_id == encounter.id, models.EncounterTeam.active.is_(True))
                    .order_by(models.EncounterTeam.slot, models.EncounterTeam.id)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        was_completed = encounter.status == enums.EncounterStatus.COMPLETED
        has_local_decision = _has_local_decision(encounter)
        before = _encounter_sync_snapshot(encounter, seats, position)
        if has_local_decision:
            local_score = tuple(seat.score for seat in seats)
            remote_score = (float(home_score), float(away_score))
            local_teams = tuple(seat.team_id for seat in seats)
            remote_teams = (home_team_id, away_team_id)
            # A dispute or a half-reported series is a decision in progress: the
            # remote scoreline matching the running tally is no proof it is settled.
            held = encounter.result_status in _HELD_RESULT_STATUSES
            if (
                held
                or status != enums.EncounterStatus.COMPLETED
                or local_score != remote_score
                or (None not in remote_teams and local_teams != remote_teams)
            ):
                await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)
                return _UpsertResult(
                    action="conflict",
                    encounter=encounter,
                    conflict_type=(
                        "local_result_held"
                        if held
                        else "local_decided_remote_different"
                        if status == enums.EncounterStatus.COMPLETED
                        else "local_decided_remote_not_completed"
                    ),
                    before=before,
                    after=after,
                )

        teams_changed = False
        if teams_mapped:
            teams_changed = await _reseat(session, encounter, [home_team_id, away_team_id], names)
            encounter.name = name
        if position is None:
            await self.bracket_encounter_repo.create(
                session,
                models.BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=tournament.id,
                    stage_id=refs.stage_id,
                    stage_item_id=refs.stage_item_id,
                    round=match.round,
                ),
            )
        else:
            position.round = match.round
            position.stage_id = refs.stage_id
            position.stage_item_id = refs.stage_item_id
        newly_completed = not was_completed and status == enums.EncounterStatus.COMPLETED
        if not newly_completed:
            encounter.status = status
        await session.flush()
        if teams_changed:
            # Challonge corrected a team slot: sync map/hero pick-ban sessions
            # (ensure when both teams are now known, reset a stale existing one)
            # and tell the rosters. No channel post: a sync rewrites a whole
            # bracket at once.
            await after_encounter_teams_changed(session, encounter, channel=False)
        await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)

        if newly_completed:
            await _write_import_result(session, encounter, [home_score, away_score])
        else:
            # Not complete remotely: the scoreline is the running tally, so it is
            # materialized onto the seats with no standing result behind it.
            for seat, score in zip(await active_teams(session, encounter.id), (home_score, away_score), strict=False):
                seat.score = float(score)
            await session.flush()

        return _UpsertResult(
            action="updated",
            encounter=encounter,
            before=before,
            after=after,
            newly_completed=newly_completed,
        )

    async def _sync_challonge_advancement_links(
        self,
        session: AsyncSession,
        matches: list[tuple[_ImportSource, schemas.ChallongeMatch]],
        *,
        match_lookup: _MatchLookup,
    ) -> dict[str, int]:
        specs_by_source_position: dict[tuple[int, int, int], _ChallongeLinkSpec] = {}
        sources_by_key = {_source_lookup_key(source): source for source, _match in matches}
        for source, match in matches:
            for spec in _iter_challonge_link_specs(source, match):
                specs_by_source_position[(spec.source_key, spec.source_challonge_id, spec.source_position)] = spec

        if not specs_by_source_position:
            return {"bracket_links_created": 0, "bracket_links_updated": 0}

        source_encounter_ids = [
            encounter.id
            for spec in specs_by_source_position.values()
            if (source := sources_by_key.get(spec.source_key)) is not None
            and (encounter := match_lookup.get(source, spec.source_challonge_id)) is not None
        ]
        if not source_encounter_ids:
            return {"bracket_links_created": 0, "bracket_links_updated": 0}

        existing_by_source_position = {
            (link.source_encounter_id, link.source_position): link
            for link in await self.encounter_link_repo.list_by_source_ids(session, source_encounter_ids)
        }

        new_links: list[models.EncounterLink] = []
        updated = 0
        for spec in specs_by_source_position.values():
            source_ref = sources_by_key.get(spec.source_key)
            if source_ref is None:
                continue
            source = match_lookup.get(source_ref, spec.source_challonge_id)
            target = match_lookup.get(source_ref, spec.target_challonge_id)
            if source is None or target is None:
                continue

            key = (source.id, spec.source_position)
            existing = existing_by_source_position.get(key)
            if existing is None:
                link = models.EncounterLink(
                    tournament_id=source.tournament_id,
                    source_encounter_id=source.id,
                    source_position=spec.source_position,
                    target_encounter_id=target.id,
                    target_slot=spec.target_slot,
                )
                new_links.append(link)
                existing_by_source_position[key] = link
                continue

            if existing.target_encounter_id != target.id or existing.target_slot != spec.target_slot:
                existing.target_encounter_id = target.id
                existing.target_slot = spec.target_slot
                updated += 1

        # One flush for both halves: create_many flushes, which also persists the
        # in-place `updated` mutations above.
        if new_links:
            await self.encounter_link_repo.create_many(session, new_links)
        elif updated:
            await session.flush()

        return {
            "bracket_links_created": len(new_links),
            "bracket_links_updated": updated,
        }

    async def _advance_completed_challonge_matches(
        self,
        session: AsyncSession,
        matches: list[tuple[_ImportSource, schemas.ChallongeMatch]],
        *,
        match_lookup: _MatchLookup,
    ) -> None:
        for source, match in matches:
            if match.state != "complete":
                continue
            encounter = match_lookup.get(source, match.id)
            if encounter is not None:
                await lock_encounter(session, encounter.id)
                # Re-fires advancement for every complete match (idempotent), so it
                # must not re-stamp an existing standing nor replace one decided
                # locally (games, a captain's claim, an admin, or a CONFLICT just
                # reported by ``_upsert_encounter_from_challonge``): ``refresh_from_games``
                # never touches an ``import`` result, so converting one here would
                # make the local decision unrecomputable forever.
                if encounter.result_status != enums.EncounterResultStatus.CONFIRMED:
                    if _has_local_decision(encounter):
                        continue
                    seats = await active_teams(session, encounter.id)
                    await _write_import_result(session, encounter, [seat.score for seat in seats])
                await advance_and_announce(session, encounter, channel=False)

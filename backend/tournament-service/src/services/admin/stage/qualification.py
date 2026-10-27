"""Downstream qualification: correction guards, the started-cut check and requalification."""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name_from_ids
from shared.services.encounter.participants import active_teams, place_team, vacate_slot
from src.services.admin.stage.base import StageServiceBase
from src.services.notifications.lifecycle import lifecycle_notifier


def _boundary_tie_unresolved(standings: Sequence[models.Standing], position: int) -> bool:
    """Is the team at 1-based ``position`` still tied with the one right below it?

    ``tie_group`` is the standings' own statement that every configured
    tiebreaker failed to separate these teams; what orders them past that point
    is ``team_id``, which is not a sporting result. Fine for rendering a stable
    table, not for deciding who qualifies -- so the boundary between a
    qualifying position and the next one has to be tie-free before a seed is
    frozen off it. ``standings`` must be ordered by ``position``.
    """
    if position >= len(standings):
        return False
    standing = standings[position - 1]
    return standing.tie_group is not None and standings[position].tie_group == standing.tie_group


class StageQualificationMixin(StageServiceBase):
    async def _untouched_stage_items(self, session: AsyncSession, stage_item_ids: Sequence[int]) -> set[int]:
        """Of ``stage_item_ids``, the ones nothing has happened in yet.

        "Untouched" is deliberately stricter than "not COMPLETED": a seed may
        still be rewritten only while every encounter of the item is OPEN,
        carries no ``result_status``, has no seat that scored anything and has
        no team report -- i.e. while no participant has acted on the
        assignment. An item with no encounters at all is untouched.
        """
        ids = set(stage_item_ids)
        if not ids:
            return set()
        scored = (
            sa.exists()
            .where(models.EncounterTeam.encounter_id == models.Encounter.id)
            .where(models.EncounterTeam.score != 0)
        )
        reported = sa.exists().where(models.EncounterTeamReport.encounter_id == models.Encounter.id)
        touched = await session.execute(
            select(models.BracketEncounter.stage_item_id)
            .join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id)
            .where(
                models.BracketEncounter.stage_item_id.in_(ids),
                or_(
                    models.Encounter.status != enums.EncounterStatus.OPEN,
                    models.Encounter.result_status != enums.EncounterResultStatus.NONE,
                    scored,
                    reported,
                ),
            )
            .distinct()
        )
        return ids - set(touched.scalars())

    async def _assert_downstream_untouched(self, session: AsyncSession, stage_item_ids: Sequence[int]) -> None:
        """Refuse to re-rank ``stage_item_ids`` while something seeded off them plays.

        The one rule behind both entry points below: a seed frozen (FINAL) off
        these items may still be re-resolved, but only while the item it feeds is
        untouched. Past that point the playoff is being played with the teams it
        has, and there is nowhere to put a new order -- so the edge is refused
        here instead of diverging silently.
        """
        source_ids = list(stage_item_ids)
        if not source_ids:
            return
        result = await session.execute(
            select(models.StageItemInput.stage_item_id).where(
                models.StageItemInput.source_stage_item_id.in_(source_ids),
                models.StageItemInput.input_type == enums.StageItemInputType.FINAL,
            )
        )
        downstream_item_ids = set(result.scalars())
        if not downstream_item_ids:
            return
        untouched = await self._untouched_stage_items(session, sorted(downstream_item_ids))
        blocked = sorted(downstream_item_ids - untouched)
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "downstream stage already in progress; correct it there or deactivate it first "
                    f"(stage items {blocked})"
                ),
            )

    async def assert_source_correction_allowed(self, session: AsyncSession, encounter: models.Encounter) -> None:
        """Refuse a result correction whose qualification fallout cannot be applied.

        ``requalify_downstream_inputs`` re-resolves a frozen seed only while the
        stage item it feeds is still untouched. Once that playoff has started,
        correcting the group result here would leave it playing with a team that
        no longer qualified and no way to take that back -- so the correction is
        refused at the entry point rather than allowed to diverge silently.
        """
        position = await session.get(models.BracketEncounter, encounter.id)
        if position is None or position.stage_item_id is None:
            return
        await self._assert_downstream_untouched(session, [position.stage_item_id])

    async def assert_stage_correction_allowed(self, session: AsyncSession, stage: models.Stage) -> None:
        """Refuse a stage-wide re-ranking whose fallout cannot be applied.

        ``assert_source_correction_allowed`` asks this of the one group a
        corrected encounter belongs to. Editing the stage's scoring re-ranks
        EVERY group of it at once, so the question is asked of every item the
        stage has -- with the same answer and the same message, because it is the
        same impossibility: a playoff already being played cannot be re-seeded.
        """
        await self._assert_downstream_untouched(session, [item.id for item in stage.items])

    async def started_qualification_cut(self, session: AsyncSession, source_stage_item_id: int) -> int | None:
        """The lowest ``source_stage_item_id`` place a downstream stage already
        in progress was seeded from, or ``None`` when nothing started plays off it.

        Every place down to this one is frozen into a playoff that
        ``requalify_downstream_inputs`` may no longer re-seed; places below it
        qualified nobody who is playing.
        """
        result = await session.execute(
            select(models.StageItemInput.stage_item_id, models.StageItemInput.source_position).where(
                models.StageItemInput.source_stage_item_id == source_stage_item_id,
                models.StageItemInput.input_type == enums.StageItemInputType.FINAL,
                models.StageItemInput.source_position.is_not(None),
            )
        )
        seeds = result.all()
        if not seeds:
            return None
        untouched = await self._untouched_stage_items(session, sorted({item_id for item_id, _ in seeds}))
        started = [position for item_id, position in seeds if item_id not in untouched]
        return max(started) if started else None

    async def requalify_downstream_inputs(
        self, session: AsyncSession, tournament_id: int, *, stages: Sequence[models.Stage] | None = None
    ) -> int:
        """Re-resolve frozen qualification seeds that recomputed standings moved.

        Activation turns a TENTATIVE input into a FINAL one, which is what makes
        the playoff's participants stable -- and would hide a later correction of
        the group result from it. This re-reads every
        FINAL input that still remembers where it came from and rewrites it, plus
        the encounter slot and name holding the old team, when the source
        standings now name somebody else.

        Only while the downstream item is untouched: past that point the seed is
        genuinely frozen and ``assert_source_correction_allowed`` refuses the
        correction instead. Returns how many seeds moved.

        ``stages`` -- the tournament's stages with items and inputs loaded -- spares the reload when the caller
        already holds them (the standings job does).
        """
        if stages is None:
            stages = await self.get_stages_by_tournament(session, tournament_id)
        candidates = [
            inp
            for stage in stages
            for item in stage.items
            for inp in item.inputs
            if inp.input_type == enums.StageItemInputType.FINAL
            and inp.source_stage_item_id is not None
            and inp.source_position is not None
        ]
        if not candidates:
            return 0

        standings_result = await session.execute(
            self.standing_repo.select()
            .where(models.Standing.stage_item_id.in_({inp.source_stage_item_id for inp in candidates}))
            .order_by(models.Standing.stage_item_id, models.Standing.position)
        )
        standings_by_item: dict[int, list[models.Standing]] = {}
        for standing in standings_result.scalars():
            standings_by_item.setdefault(standing.stage_item_id, []).append(standing)

        # All-or-nothing per source group: positions in one group are a single
        # ranking, so re-seeding only the tie-free ones moves a team into its new
        # place while its old place still holds it -- the same team seeded twice.
        moved: list[tuple[models.StageItemInput, int, int]] = []
        blocked: set[int] = set()
        for inp in candidates:
            standings = standings_by_item.get(inp.source_stage_item_id, [])
            if inp.source_position > len(standings):
                continue
            if _boundary_tie_unresolved(standings, inp.source_position):
                blocked.add(inp.source_stage_item_id)
                continue
            expected = standings[inp.source_position - 1].team_id
            if expected is None or expected == inp.team_id:
                continue
            moved.append((inp, inp.team_id, expected))
        moved = [entry for entry in moved if entry[0].source_stage_item_id not in blocked]

        if not moved:
            return 0

        # Asked once without a lock, so a started item (live rooms) is never locked; then the untouched candidates'
        # encounter rows are locked and asked again. A result write or a report locks the encounter row (FOR UPDATE,
        # or the KEY SHARE of its foreign key), so neither can land between the re-check and the reseat below.
        candidate_item_ids = sorted(
            await self._untouched_stage_items(session, sorted({inp.stage_item_id for inp, _, _ in moved}))
        )
        if not candidate_item_ids:
            return 0
        await session.execute(
            select(models.Encounter.id)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_item_id.in_(candidate_item_ids))
            .with_for_update(of=models.Encounter)
        )
        untouched = await self._untouched_stage_items(session, candidate_item_ids)
        # One mapping per item, applied in a single pass: two seeds that swapped
        # places (A->B, B->A) would otherwise chase each other slot by slot.
        replacements: dict[int, dict[int, int]] = {}
        applied = 0
        for inp, old_team_id, new_team_id in moved:
            if inp.stage_item_id not in untouched:
                continue
            inp.team_id = new_team_id
            if old_team_id is not None:
                replacements.setdefault(inp.stage_item_id, {})[old_team_id] = new_team_id
            applied += 1
        for stage_item_id, mapping in replacements.items():
            await self._replace_teams_in_stage_item(session, stage_item_id=stage_item_id, mapping=mapping)
        return applied

    async def _replace_teams_in_stage_item(
        self,
        session: AsyncSession,
        *,
        stage_item_id: int,
        mapping: dict[int, int],
    ) -> None:
        """Move every ``old -> new`` slot of an untouched stage item at once,
        renaming the encounters and resetting their pick-ban.

        A seat changes hands the only way it can: the occupant is retired
        and the replacement is seated in the same slot. The item is untouched --
        nothing was played in it -- so the retired rows carry no result with them;
        :meth:`requalify_downstream_inputs` holds the encounter rows locked since it checked that.
        """
        from src.services.encounter.pick_ban_session import pick_ban_session_service

        seat = aliased(models.EncounterTeam)
        result = await session.execute(
            self.encounter_repo.select()
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(
                models.BracketEncounter.stage_item_id == stage_item_id,
                sa.exists()
                .where(seat.encounter_id == models.Encounter.id)
                .where(seat.active.is_(True))
                .where(seat.team_id.in_(mapping)),
            )
        )
        encounters = list(result.scalars())
        if not encounters:
            return
        seats_by_encounter: dict[int, list[models.EncounterTeam]] = defaultdict(list)
        for row in (
            await session.execute(
                select(models.EncounterTeam)
                .where(
                    models.EncounterTeam.encounter_id.in_([encounter.id for encounter in encounters]),
                    models.EncounterTeam.active.is_(True),
                )
                .order_by(models.EncounterTeam.slot)
            )
        ).scalars():
            seats_by_encounter[row.encounter_id].append(row)

        team_ids = set(mapping.values())
        for seats in seats_by_encounter.values():
            team_ids.update(row.team_id for row in seats if row.team_id is not None)
        names = await self._load_team_names(session, sorted(team_ids))
        lineups = await self._team_lineups(session, sorted(set(mapping.values())))
        for encounter in encounters:
            seats = seats_by_encounter[encounter.id]
            for row in seats:
                replacement = mapping.get(row.team_id) if row.team_id is not None else None
                if replacement is None:
                    continue
                await vacate_slot(session, encounter, slot=row.slot)
                await place_team(
                    session,
                    encounter,
                    slot=row.slot,
                    team_id=replacement,
                    name=names.get(replacement, "TBD"),
                    seed=row.seed,
                    members=lineups.get(replacement, ()),
                )
            live = await active_teams(session, encounter.id)
            by_slot = {row.slot: row.team_id for row in live}
            encounter.name = build_encounter_name_from_ids(
                [by_slot.get(slot) for slot in range(1, encounter.slot_count + 1)],
                names,
            )
            # The pick-ban rooms follow the new pairing.
            await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, encounter)
        # No channel post: requalification rewrites a whole stage item.
        await lifecycle_notifier.on_encounters_changed(session, encounters, channel=False)

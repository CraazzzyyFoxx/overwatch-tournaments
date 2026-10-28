"""Every pick-ban outcome of one tournament, read in bulk for the public tournament pages.

The per-room state read (``PickBanActionService.get_state``) answers one encounter; the tournament's ban and map
tables need all of them, so this reads every room at once in at most four queries whatever the tournament's size.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import MapPoolEntryStatus, PickBanKind
from shared.domain import pick_ban_rules as pbr
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.pick_ban import PickBanEntry, PickBanSession, PickBanSubmission
from shared.models.encounter.team import EncounterTeam
from shared.services.cache_generations import versioned
from src.core import config
from src.schemas import pick_ban_outcomes as schemas
from src.services.encounter.pick_ban_session import resolved_steps
from src.services.tournament.cache_resources import ENCOUNTERS, tournament_generations

__all__ = ("PickBanOutcomesService", "pick_ban_outcomes_service")


class PickBanOutcomesService:
    # ENCOUNTERS drops the entry when the tournament's encounters move; a pick-ban write publishes no tournament
    # resource, so a live room's bans reach this read within the short TTL.
    @versioned(
        generations=tournament_generations("{tournament_id}", ENCOUNTERS),
        ttl=config.settings.pick_ban_outcomes_cache_ttl,
        key="pick_ban_outcomes:v1:{tournament_id}",
        prefix="fastapi:",
    )
    async def get_by_tournament(self, session: AsyncSession, tournament_id: int) -> schemas.TournamentPickBanOutcomes:
        """The tournament's hero bans an anonymous viewer may see and its picked/banned maps.

        A hero ban is an item of a submission ``pbr.visible_submissions`` shows a viewer with no seat (the current
        attempt, revealed or on a non-blind step) to a ``ban`` step, one row per item. A map outcome is a map room's
        board entry the room picked or banned.
        """
        hero_sessions = list(
            (
                await session.execute(
                    select(PickBanSession)
                    .join(Encounter, Encounter.id == PickBanSession.encounter_id)
                    .where(Encounter.tournament_id == tournament_id, PickBanSession.kind == PickBanKind.HERO)
                    .order_by(PickBanSession.encounter_id)
                )
            )
            .scalars()
            .all()
        )
        hero_bans: list[schemas.PickBanHeroBan] = []
        if hero_sessions:
            session_ids = [pick_ban.id for pick_ban in hero_sessions]
            submissions: dict[int, list[PickBanSubmission]] = {}
            for row in (
                await session.execute(
                    select(PickBanSubmission)
                    .where(PickBanSubmission.session_id.in_(session_ids))
                    .order_by(PickBanSubmission.step_index, PickBanSubmission.id)
                )
            ).scalars():
                submissions.setdefault(row.session_id, []).append(row)
            # The live seats in slot order: a stored sequence may name home/away instead of participations.
            teams: dict[int, list[EncounterTeam]] = {}
            for team in (
                await session.execute(
                    select(EncounterTeam)
                    .where(
                        EncounterTeam.encounter_id.in_([pick_ban.encounter_id for pick_ban in hero_sessions]),
                        EncounterTeam.active.is_(True),
                    )
                    .order_by(EncounterTeam.slot)
                )
            ).scalars():
                teams.setdefault(team.encounter_id, []).append(team)

            for pick_ban in hero_sessions:
                steps = resolved_steps(pick_ban, teams.get(pick_ban.encounter_id, []))
                by_index = {step.index: step for step in steps}
                for row in pbr.visible_submissions(steps, submissions.get(pick_ban.id, []), None):
                    step = by_index.get(row.step_index)
                    if step is None or step.action != "ban":
                        continue
                    hero_bans.extend(
                        schemas.PickBanHeroBan(
                            encounter_id=pick_ban.encounter_id,
                            hero_id=int(item["item_id"]),
                            first_map=step.round in (None, 1),
                            target_player_id=item.get("target_player_id"),
                        )
                        for item in row.items_json or []
                    )

        map_rows = (
            await session.execute(
                select(PickBanEntry.encounter_id, PickBanEntry.item_id, PickBanEntry.status)
                .join(PickBanSession, PickBanSession.id == PickBanEntry.session_id)
                .join(Encounter, Encounter.id == PickBanEntry.encounter_id)
                .where(
                    Encounter.tournament_id == tournament_id,
                    PickBanSession.kind == PickBanKind.MAP,
                    PickBanEntry.status.in_((MapPoolEntryStatus.BANNED, MapPoolEntryStatus.PICKED)),
                )
                .order_by(PickBanEntry.encounter_id, PickBanEntry.id)
            )
        ).all()
        return schemas.TournamentPickBanOutcomes(
            hero_bans=hero_bans,
            map_outcomes=[
                schemas.PickBanMapOutcome(
                    encounter_id=row.encounter_id, map_id=row.item_id, picked=row.status == MapPoolEntryStatus.PICKED
                )
                for row in map_rows
            ],
        )


pick_ban_outcomes_service = PickBanOutcomesService()

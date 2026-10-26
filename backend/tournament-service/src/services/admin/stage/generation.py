"""Encounter generation: skeletons, seats and lineups, and the FFA/grouped/bracket generators."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import replace

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name_from_ids
from shared.models.tournament.player_role import PlayerRole
from shared.services.encounter.participants import MemberSnapshot, place_team
from src.domain.admin.best_of import best_of_config, resolve_best_of, resolve_swiss_best_of
from src.domain.bracket import (
    BracketSkeleton,
    Pairing,
    SwissPairingImpossibleError,
    SwissStanding,
    SwissThresholds,
    generate_bracket,
    placeholder_seeds,
    round_robin,
)
from src.domain.stage.seeds import (
    SeedRanking,
    apply_seed_ranking,
)
from src.domain.stage.seeds import collect_item_team_ids as _collect_item_team_ids
from src.domain.stage.seeds import lower_bracket_item as _lower_bracket_item
from src.domain.stage.seeds import resolve_seeds as _resolve_seeds
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage_common import (
    BRACKET_STAGE_TYPES,
    FFA_STAGE_TYPES,
    GROUPED_GENERATION_STAGE_TYPES,
    _bracket_seeds,
)
from src.services.bracket.persist import SeatTeam, persist_skeleton
from src.services.bracket.swiss_state import (
    clear_swiss_byes,
    clear_swiss_scope_stopped,
    mark_swiss_scope_stopped,
    record_swiss_bye,
    swiss_bye_team_ids,
)
from src.services.encounter.ffa import ffa_encounter_service
from src.services.standings.service import StageEncounter, rank_group, standings_service


def _with_decisive_best_of(
    stage: models.Stage,
    skeleton: BracketSkeleton,
    thresholds: SwissThresholds,
    standings: Sequence[SwissStanding],
) -> BracketSkeleton:
    """The Swiss round with every pairing's best-of resolved off what it can decide.

    ``standings`` are the records the teams bring into the round; a team missing
    from them (round 1) has none yet.
    """
    cfg = best_of_config(stage)
    records = {standing.team_id: (standing.wins, standing.losses) for standing in standings}
    pairings = []
    for pairing in skeleton.pairings:
        qualification, elimination = thresholds.stakes(
            records.get(team_id, (0, 0)) for team_id in pairing.team_ids if team_id is not None
        )
        best_of = resolve_swiss_best_of(cfg, pairing.round_number, qualification=qualification, elimination=elimination)
        pairings.append(replace(pairing, best_of=best_of))
    return replace(skeleton, pairings=pairings)


class StageGenerationMixin(StageServiceBase):
    async def _load_team_names(
        self,
        session: AsyncSession,
        team_ids: Sequence[int],
    ) -> dict[int, str]:
        # ``> 0`` skips the negative placeholder seeds a bracket generated before
        # its teams are known is built from (``placeholder_seeds``).
        unique_team_ids = sorted({team_id for team_id in team_ids if team_id is not None and team_id > 0})
        if not unique_team_ids:
            return {}

        # Two-column projection: names only, never whole Team rows.
        result = await session.execute(
            select(models.Team.id, models.Team.name).where(models.Team.id.in_(unique_team_ids))
        )
        return dict(result.all())

    async def _load_rankable_teams(
        self,
        session: AsyncSession,
        team_ids: Sequence[int],
    ) -> dict[int, models.Team]:
        unique_team_ids = sorted({team_id for team_id in team_ids if team_id is not None and team_id > 0})
        if not unique_team_ids:
            return {}
        teams = await self.team_repo.bulk_get(session, unique_team_ids)
        return {team.id: team for team in teams}

    async def _rank_seed_ids(
        self,
        session: AsyncSession,
        stage: models.Stage,
        team_ids: list[int],
    ) -> list[int]:
        ranking = SeedRanking(stage.seed_ranking)
        if ranking is SeedRanking.SLOT or not team_ids:
            return team_ids
        teams = await self._load_rankable_teams(session, team_ids)
        return apply_seed_ranking(team_ids, teams, ranking, rng_seed=stage.id)

    async def _get_swiss_generation_context(
        self,
        session: AsyncSession,
        stage: models.Stage,
        stage_item_id: int | None,
        encounters: list[StageEncounter] | None = None,
    ) -> tuple[list[SwissStanding] | None, set[frozenset[int]] | None, int]:
        """``encounters``: the scope's encounters when the caller already loaded them (the standings job)."""
        stage_id = stage.id
        if encounters is None:
            encounters = [
                encounter
                for encounter in await standings_service.load_stage_encounters(session, stage_id)
                if encounter.stage_item_id == stage_item_id
            ]
        if not encounters:
            return None, None, 1

        swiss_round = max(encounter.round for encounter in encounters) + 1
        # The pairs this scope already played, off the participations: a Swiss
        # pairing refuses a rematch, and who met whom is the seats of each card.
        # A seat that was taken over still counts as a meeting.
        seats = (
            await session.execute(
                select(models.EncounterTeam.encounter_id, models.EncounterTeam.team_id).where(
                    models.EncounterTeam.encounter_id.in_([encounter.id for encounter in encounters]),
                    models.EncounterTeam.team_id.is_not(None),
                )
            )
        ).all()
        by_encounter: dict[int, set[int]] = defaultdict(set)
        for encounter_id, team_id in seats:
            by_encounter[encounter_id].add(team_id)
        swiss_played_pairs: set[frozenset[int]] = {
            frozenset(team_ids) for team_ids in by_encounter.values() if len(team_ids) > 1
        }

        # Ranked here off the encounters, not read from the stored table: the
        # standings job hands in the very encounters it ranked and closed the
        # round on, so pairing and gate see one snapshot. A result committing
        # after it bumps the generation and gets a job of its own.
        tournament = await session.get_one(models.Tournament, stage.tournament_id)
        stage_item = next((item for item in stage.items if item.id == stage_item_id), None)
        byes = Counter(await swiss_bye_team_ids(session, stage_id, stage_item_id))
        swiss_standings = [
            SwissStanding(
                team_id=team.team_id,
                points=team.points,
                buchholz=team.median_buchholz,
                wins=team.wins + byes[team.team_id],
                losses=team.loses,
            )
            for team in rank_group(tournament, stage, stage_item, encounters, bye_counts=byes)
        ]

        return swiss_standings, swiss_played_pairs, swiss_round

    async def _generate_stage_skeleton(
        self,
        session: AsyncSession,
        stage: models.Stage,
        team_ids: list[int],
        stage_item_id: int | None,
        *,
        lower_bracket_team_ids: list[int] | None = None,
        encounters: list[StageEncounter] | None = None,
    ) -> BracketSkeleton:
        if stage.stage_type in BRACKET_STAGE_TYPES:
            return self._bracket_skeleton(stage, team_ids, lower_bracket_team_ids or [])

        swiss_standings = None
        swiss_played_pairs: set[frozenset[int]] | None = None
        swiss_round = 1
        thresholds = SwissThresholds()
        if stage.stage_type == enums.StageType.SWISS:
            swiss_standings, swiss_played_pairs, swiss_round = await self._get_swiss_generation_context(
                session, stage, stage_item_id, encounters
            )
            if swiss_standings is None:
                await clear_swiss_byes(session, stage.id, stage_item_id)
            from src.services.standings.swiss_auto_round import stage_allows_next_round, stage_max_rounds

            if not stage_allows_next_round(stage, swiss_round):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Swiss stage reached max_rounds",
                )

            thresholds = SwissThresholds.of(stage)
            if swiss_standings is not None and thresholds:
                # A team through or out is paired no more. Fewer than two left
                # and the scope is over: the standings call it complete.
                swiss_standings = [
                    standing
                    for standing in swiss_standings
                    if thresholds.status(standing.wins, standing.losses) is None
                ]
                if len(swiss_standings) < 2:
                    logger.info(
                        "Swiss scope ended because fewer than two teams are still undecided",
                        stage_id=stage.id,
                        stage_item_id=stage_item_id,
                        round=swiss_round,
                    )
                    return BracketSkeleton(pairings=[], total_rounds=0)

            # A Swiss allowed as many rounds as a full circle IS a round robin.
            # Pairing it one round at a time only invites corners where no
            # rematch-free round is left, and no ordering of the schedule can
            # matter when every team meets every other anyway. An odd field
            # needs ``n`` rounds for that full circle, not ``n - 1``: one team
            # sits out each round, so the shortcut must not fire a round early
            # and hand out a schedule longer than the configured limit. Not with
            # thresholds: they take teams out of the circle as it goes.
            rr_rounds = len(team_ids) if len(team_ids) % 2 else len(team_ids) - 1
            if swiss_standings is None and not thresholds and stage_max_rounds(stage) >= rr_rounds:
                await clear_swiss_scope_stopped(session, stage.id, stage_item_id)
                return round_robin.generate(team_ids)

        try:
            skeleton = generate_bracket(
                stage.stage_type,
                team_ids,
                swiss_standings=swiss_standings,
                swiss_played_pairs=swiss_played_pairs,
                swiss_round_number=swiss_round,
                swiss_bye_history=(
                    set(await swiss_bye_team_ids(session, stage.id, stage_item_id))
                    if stage.stage_type == enums.StageType.SWISS
                    else set()
                ),
            )
        except SwissPairingImpossibleError:
            await mark_swiss_scope_stopped(session, stage.id, stage_item_id)
            logger.info(
                "Swiss scope ended because no complete pairing exists",
                stage_id=stage.id,
                stage_item_id=stage_item_id,
                round=swiss_round,
            )
            return BracketSkeleton(pairings=[], total_rounds=0)

        if stage.stage_type == enums.StageType.SWISS:
            await clear_swiss_scope_stopped(session, stage.id, stage_item_id)
            if skeleton.bye_team_id is not None:
                await record_swiss_bye(session, stage.id, stage_item_id, skeleton.bye_team_id, round_number=swiss_round)
            if thresholds:
                skeleton = _with_decisive_best_of(stage, skeleton, thresholds, swiss_standings or [])
        return skeleton

    async def _seat_teams(self, session: AsyncSession, team_ids: Sequence[int]) -> dict[int, SeatTeam]:
        """The teams a skeleton seeds, as the participation writer wants them.

        ``seed`` is the team's place in the order the stage handed the
        generator, which is what ``encounter.team.seed`` means; a placeholder
        (negative) id never reaches a seat, so it gets none. ``members`` is the
        team's roster line-up (:meth:`_team_lineups`).
        """
        ordered = [team_id for team_id in dict.fromkeys(team_ids) if team_id is not None and team_id > 0]
        names = await self._load_team_names(session, ordered)
        lineups = await self._team_lineups(session, ordered)
        return {
            team_id: SeatTeam(name=names.get(team_id, "TBD"), seed=index, members=lineups.get(team_id, ()))
            for index, team_id in enumerate(ordered, 1)
        }

    async def _team_lineups(
        self, session: AsyncSession, team_ids: Sequence[int]
    ) -> dict[int, tuple[MemberSnapshot, ...]]:
        """Each team's tournament roster (substitutes and captain flagged) as the line-up its seat snapshots, as a mix
        seat does.

        Taken when the seat is filled and never synced: a player rostered later
        reaches a seat only the way any mid-encounter change does (the match
        layer seats a logged extra as a substitute), and advancement carries
        the snapshot on. A member rostered on two of these teams is left off
        both: one member, one seat per encounter.
        """
        if not team_ids:
            return {}
        player = models.Player
        rows = (
            await session.execute(
                select(
                    player.id,
                    player.team_id,
                    player.workspace_member_id,
                    player.name,
                    player.rank,
                    player.is_substitution,
                    # The team's captain is a ``players.user``; the seat is its workspace member.
                    (models.WorkspaceMember.player_id == models.Team.captain_id).label("is_captain"),
                )
                .join(models.Team, models.Team.id == player.team_id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == player.workspace_member_id)
                .where(player.team_id.in_(team_ids))
                .order_by(player.team_id, player.is_substitution, player.id)
            )
        ).all()
        if not rows:
            return {}
        roles: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for player_id, dimension, code in await session.execute(
            select(PlayerRole.player_id, models.RoleDimension.code, models.CatalogRole.code)
            .join(models.CatalogRole, models.CatalogRole.id == PlayerRole.role_id)
            .join(models.RoleDimension, models.RoleDimension.id == models.CatalogRole.dimension_id)
            .where(PlayerRole.player_id.in_([row.id for row in rows]))
            .order_by(PlayerRole.player_id, models.RoleDimension.code)
        ):
            roles[player_id].append((dimension, code))
        teams_of: dict[int, set[int]] = defaultdict(set)
        for row in rows:
            teams_of[row.workspace_member_id].add(row.team_id)
        lineups: dict[int, dict[int, MemberSnapshot]] = defaultdict(dict)
        for row in rows:
            if len(teams_of[row.workspace_member_id]) == 1:
                lineups[row.team_id].setdefault(
                    row.workspace_member_id,
                    MemberSnapshot(
                        workspace_member_id=row.workspace_member_id,
                        # ``display_name_snapshot`` is VARCHAR(255); the roster name is unbounded (enclayer01's left()).
                        display_name=row.name[:255],
                        rank=row.rank,
                        is_substitute=row.is_substitution,
                        roles=tuple(roles[row.id]),
                        # NULL when the team has no captain.
                        is_captain=row.is_captain is True,
                    ),
                )
        return {team_id: tuple(members.values()) for team_id, members in lineups.items()}

    async def _create_encounters_from_skeleton(
        self,
        session: AsyncSession,
        stage: models.Stage,
        skeleton: BracketSkeleton,
        stage_item_id: int | None,
        *,
        teams_by_id: dict[int, SeatTeam],
        lb_stage_item_id: int | None = None,
    ) -> list[models.Encounter]:
        """Persist bracket pairings as encounters, seats, positions and links."""
        best_of_cfg = best_of_config(stage)
        return await persist_skeleton(
            session,
            stage=stage,
            skeleton=skeleton,
            stage_item_id=stage_item_id,
            teams_by_id=teams_by_id,
            lb_stage_item_id=lb_stage_item_id,
            is_elimination=stage.stage_type in BRACKET_STAGE_TYPES,
            best_of_for_round=lambda round_number, *, is_final: resolve_best_of(
                best_of_cfg, round_number, is_final=is_final
            ),
        )

    async def _fill_bracket_seeds(
        self,
        session: AsyncSession,
        stage: models.Stage,
        upper_ids: list[int],
        lower_ids: list[int],
    ) -> list[models.Encounter] | None:
        """Seed real teams into a bracket that was generated before it had any.

        ``generate_encounters`` can build a bracket off the preceding group stage's
        ``advance_count`` alone, which leaves every slot TBD. Once the groups finish
        and the TENTATIVE inputs resolve, the shape is already right and only the
        seeds are missing — so they are written into the existing encounters rather
        than throwing the bracket away, which would take its ids, schedule and
        advancement links with it.

        Returns ``None``, leaving the caller to refuse, unless the stage really is
        that untouched preview: a seated participation or an encounter that left
        ``OPEN`` means this is a live bracket, and so does a shape the resolved
        seeds would no longer produce.
        """
        # ``EncounterRepository.list_by_stage`` also predicates on tournament_id,
        # which would change the rows this preview check sees; kept as a select().
        result = await session.execute(
            select(models.Encounter, models.BracketEncounter.round)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_id == stage.id)
            .order_by(models.BracketEncounter.round, models.Encounter.id)
        )
        rows = result.tuples().all()
        existing = [encounter for encounter, _round in rows]
        if not existing or any(encounter.status != enums.EncounterStatus.OPEN for encounter in existing):
            return None
        seated = await session.scalar(
            select(func.count())
            .select_from(models.EncounterTeam)
            .where(models.EncounterTeam.encounter_id.in_([encounter.id for encounter in existing]))
        )
        # ANY participation, retired ones included: a seat that changed hands is
        # a bracket somebody played, not a preview to overwrite.
        if seated:
            return None

        seed_ids = upper_ids + lower_ids
        skeleton = _resolve_seeds(
            self._bracket_skeleton(
                stage,
                placeholder_seeds(len(upper_ids)),
                placeholder_seeds(len(lower_ids), offset=len(upper_ids)),
            ),
            dict(zip(placeholder_seeds(len(seed_ids)), seed_ids, strict=True)),
        )

        encounters_by_round: dict[int, list[models.Encounter]] = {}
        for encounter, round_number in rows:
            encounters_by_round.setdefault(round_number, []).append(encounter)
        pairings_by_round: dict[int, list[Pairing]] = {}
        for pairing in skeleton.pairings:
            pairings_by_round.setdefault(pairing.round_number, []).append(pairing)
        if {rnd: len(items) for rnd, items in encounters_by_round.items()} != {
            rnd: len(items) for rnd, items in pairings_by_round.items()
        }:
            return None

        teams_by_id = await self._seat_teams(session, seed_ids)
        names_by_id = {team_id: seat.name for team_id, seat in teams_by_id.items()}
        for round_number, pairings in pairings_by_round.items():
            for pairing, encounter in zip(pairings, encounters_by_round[round_number], strict=True):
                for index, team_id in enumerate(pairing.team_ids, 1):
                    if team_id is None:
                        continue
                    seat = teams_by_id.get(team_id)
                    await place_team(
                        session,
                        encounter,
                        slot=index,
                        team_id=team_id,
                        name=seat.name if seat is not None else "TBD",
                        seed=seat.seed if seat is not None else None,
                        members=seat.members if seat is not None else (),
                    )
                encounter.name = build_encounter_name_from_ids(pairing.team_ids, names_by_id)
        await session.flush()
        return existing

    async def generate_encounters(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        notify: bool = True,
        commit: bool = True,
        schedule_standings: bool = True,
        stage: models.Stage | None = None,
    ) -> list[models.Encounter]:
        """Generate bracket encounters for a stage based on its type and team inputs.

        Never overwrites: an item (or, for a non-grouped stage, the stage as a
        whole) that already has encounters is left alone rather than getting a
        second set of matches. A grouped stage (Swiss/Round Robin with multiple
        groups) lets a newly added group generate on its own once earlier groups
        are already underway; a non-grouped stage refuses outright, since there
        is no partial bracket to preserve there -- delete its matches first to
        regenerate.

        A bracket stage with no seeds is the one exception. Rather than refuse, it
        is built from the preceding group stage's ``advance_count`` × groups (see
        ``_bracket_seed_counts``) with every slot left TBD, so the playoff can be
        laid out, scheduled and configured while the groups are still running;
        ``_fill_bracket_seeds`` writes the teams into it once they resolve.
        """
        stage = stage or await self.get_stage(session, stage_id)

        existing_by_item_result = await session.execute(
            select(models.BracketEncounter.stage_item_id, func.count())
            .where(models.BracketEncounter.stage_id == stage_id)
            .group_by(models.BracketEncounter.stage_item_id)
        )
        existing_by_item: dict[int | None, int] = dict(existing_by_item_result.all())

        if stage.stage_type in FFA_STAGE_TYPES:
            encounters = await self._generate_ffa_encounters(session, stage, existing_by_item)
        elif stage.stage_type in GROUPED_GENERATION_STAGE_TYPES and len(stage.items) > 1:
            encounters = await self._generate_grouped_encounters(session, stage, existing_by_item)
        else:
            encounters = await self._generate_bracket_encounters(session, stage, existing_by_item)

        if stage.is_published:
            await self._notify_published_encounters(session, stage)

        await self._finish_structure_write(
            session,
            stage,
            notify=notify,
            commit=commit,
            schedule_standings=schedule_standings,
        )
        return encounters

    async def _generate_ffa_encounters(
        self,
        session: AsyncSession,
        stage: models.Stage,
        existing_by_item: dict[int | None, int],
    ) -> list[models.Encounter]:
        """One lobby per group that has none yet. A lobby is not a
        bracket: nothing here goes through ``generate_bracket``/``Pairing``."""
        items = [
            item
            for item in sorted(stage.items, key=lambda it: (it.order, it.id))
            if existing_by_item.get(item.id, 0) == 0
        ]
        if not items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Every group already has a lobby. Delete a lobby to regenerate it.",
            )
        games = resolve_best_of(best_of_config(stage), 1, is_final=False)
        return [
            await ffa_encounter_service.create_lobby(session, stage, item, _collect_item_team_ids(item), games=games)
            for item in items
        ]

    async def _generate_grouped_encounters(
        self,
        session: AsyncSession,
        stage: models.Stage,
        existing_by_item: dict[int | None, int],
    ) -> list[models.Encounter]:
        eligible_items = [item for item in stage.items if existing_by_item.get(item.id, 0) == 0]
        if not eligible_items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Every group already has generated matches. Delete a group's matches first to regenerate it.",
            )
        encounters: list[models.Encounter] = []
        for item in eligible_items:
            team_ids = _collect_item_team_ids(item)
            if len(team_ids) < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each group needs at least 2 teams to generate a bracket",
                )
            skeleton = await self._generate_stage_skeleton(session, stage, team_ids, item.id)
            encounters.extend(
                await self._create_encounters_from_skeleton(
                    session,
                    stage,
                    skeleton,
                    item.id,
                    teams_by_id=await self._seat_teams(session, team_ids),
                )
            )
        return encounters

    async def _generate_bracket_encounters(
        self,
        session: AsyncSession,
        stage: models.Stage,
        existing_by_item: dict[int | None, int],
    ) -> list[models.Encounter]:
        # Before anything is decided off ``existing_by_item`` or the stage's
        # template: a concurrent template swap must wait, not land mid-generation.
        await self._lock_stage(session, stage.id)
        sorted_items = sorted(stage.items, key=lambda it: (it.order, it.id))
        primary_item_id = sorted_items[0].id if sorted_items else None
        lb_item = _lower_bracket_item(stage, sorted_items)
        lb_stage_item_id = lb_item.id if lb_item is not None else None

        team_ids, lower_bracket_team_ids = _bracket_seeds(sorted_items, lb_item)
        is_bracket = stage.stage_type in BRACKET_STAGE_TYPES
        if is_bracket:
            team_ids = await self._rank_seed_ids(session, stage, team_ids)
            lower_bracket_team_ids = await self._rank_seed_ids(session, stage, lower_bracket_team_ids)

        seeds_are_placeholders = False
        if is_bracket and len(team_ids) + len(lower_bracket_team_ids) < 2:
            upper_count, lower_count = await self._projected_bracket_seed_counts(session, stage)
            team_ids = placeholder_seeds(upper_count)
            lower_bracket_team_ids = placeholder_seeds(lower_count, offset=upper_count)
            seeds_are_placeholders = True

        if sum(existing_by_item.values()) > 0:
            filled = (
                None
                if seeds_are_placeholders or not is_bracket
                else await self._fill_bracket_seeds(session, stage, team_ids, lower_bracket_team_ids)
            )
            if filled is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This stage already has generated matches. Delete them first to regenerate the bracket.",
                )
            return filled

        if len(team_ids) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Need at least 2 teams to generate a bracket",
            )

        skeleton = await self._generate_stage_skeleton(
            session,
            stage,
            team_ids,
            primary_item_id,
            lower_bracket_team_ids=lower_bracket_team_ids,
        )
        if seeds_are_placeholders:
            skeleton = _resolve_seeds(skeleton, {})
        return await self._create_encounters_from_skeleton(
            session,
            stage,
            skeleton,
            primary_item_id,
            teams_by_id=await self._seat_teams(session, team_ids + lower_bracket_team_ids),
            lb_stage_item_id=lb_stage_item_id,
        )

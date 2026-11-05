"""Stage and stage item CRUD, the scoring block included."""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_scoring import (
    DEFAULT_COLUMN_KEY,
    DEFAULT_COLUMN_LABEL,
    DEFAULT_FORMULA,
    PLACEMENT_VARIABLES,
    POINTS_END_FORMULA,
    WINS_END_FORMULA,
)
from shared.domain.ffa_formula import compile_formula
from shared.domain.flow.legacy import X_STEP, Y_STEP
from shared.services.stats_owner_delete import capture_owner_delete, stage_owner_delete
from shared.services.team_format import tournament_slot_shape
from src import schemas
from src.domain.bracket import SwissThresholds
from src.domain.individual_swiss import PoolError, PoolPlayer, check_playoff_team_count, teams_per_round
from src.services.admin.stage.base import StageServiceBase
from src.services.individual_swiss.standings import DEFAULT_PLAYOFF_TEAMS, stage_players
from src.services.tournament.events import enqueue_tournament_recalculation


def _apply_stage_fields(stage: models.Stage, fields: dict[str, Any]) -> None:
    """Write validated ``StageCreate``/``StageUpdate`` fields onto the stage.

    ``scoring`` and ``best_of`` arrive as the objects the API shows and each
    replaces its columns as a whole; everything else is a column. The levels
    1-2 half of ``scoring`` is NOT written here -- it lives in
    ``encounter.scoring_rule``, a row of its own, which :func:`_write_rule`
    writes with the session the caller holds.

    Rounds of ``best_of.by_round`` are updated in place rather than recreated: a
    replaced collection would insert the new ``(stage_id, round)`` rows before
    deleting the old ones and collide on the key.
    """
    if "scoring" in fields:
        scoring = fields.pop("scoring") or {}
        stage.win_points = scoring.get("win")
        stage.draw_points = scoring.get("draw")
        stage.loss_points = scoring.get("loss")
    if "best_of" in fields:
        best_of = fields.pop("best_of") or {}
        # ``model_dump(exclude_unset=True)`` drops a nested default, so a body
        # of ``{default, by_round}`` has no ``final`` key. An omitted override is
        # the schema default: none.
        if best_of.get("default") is not None:
            stage.best_of_default = best_of["default"]
        stage.best_of_final = best_of.get("final")
        stage.best_of_swiss_qualify = best_of.get("swiss_qualify")
        stage.best_of_swiss_eliminate = best_of.get("swiss_eliminate")
        wanted: dict[int, int] = best_of.get("by_round") or {}
        existing = {row.round: row for row in stage.round_best_of}
        for round_number, row in existing.items():
            if round_number not in wanted:
                stage.round_best_of.remove(row)
        for round_number, value in sorted(wanted.items()):
            if round_number in existing:
                existing[round_number].best_of = value
            else:
                stage.round_best_of.append(models.StageRoundBestOf(round=round_number, best_of=value))
    for field, value in fields.items():
        setattr(stage, field, value)


def _normalize_individual_swiss(stage: models.Stage) -> None:
    """The two ``individual_swiss`` settings exist only on that type: defaults there, NULL elsewhere."""
    if stage.stage_type == enums.StageType.INDIVIDUAL_SWISS:
        stage.pairing_mode = stage.pairing_mode or enums.StagePairingMode.SCORE.value
        stage.playoff_team_count = stage.playoff_team_count or 4
    else:
        stage.pairing_mode = None
        stage.playoff_team_count = None


def rule_values(stage_type: enums.StageType, block: dict[str, Any]) -> dict[str, Any]:
    """The ``encounter.scoring_rule`` row a stage's ``scoring`` block means.

    Every rule field of the block is nullable and reads as "the preset's own",
    and the preset itself defaults to the one the stage TYPE implies -- a lobby
    stage is scored by points, everything else by wins. The two end formulas are
    the preset's, never the organizer's: when a series or a lobby is OVER is a
    property of the format.
    """
    preset = block.get("preset") or ("points" if stage_type == enums.StageType.FFA_LEAGUE else "wins")
    if preset == "wins":
        return {
            "preset": "wins",
            "columns": [],
            "placement_points": [],
            "game_formula": "win",
            "end_formula": WINS_END_FORMULA,
        }
    columns = block.get("columns")
    return {
        "preset": "points",
        "columns": (
            [dict(column) for column in columns]
            if columns is not None
            else [{"key": DEFAULT_COLUMN_KEY, "label": DEFAULT_COLUMN_LABEL, "public": True, "better": "higher"}]
        ),
        "placement_points": [float(points) for points in (block.get("placement_points") or ())],
        "game_formula": block.get("formula") or DEFAULT_FORMULA,
        "end_formula": POINTS_END_FORMULA,
    }


def _ranking_signature(rule: dict[str, Any]) -> tuple[Any, ...]:
    """What of a resolved rule decides places -- everything except presentation.

    Labels and ``public`` are how the table is drawn; the preset, the formula,
    the placement points, the set of column keys and their ``better`` are what
    the places are computed from. Column ORDER counts too: with no explicit
    ``tiebreak_order`` the ffa_league preset breaks ties by the sum of the FIRST
    column, so moving one can move a team.

    Compared, not merely "was it sent": saving the same form twice must not run
    into a 409.
    """
    return (
        rule["preset"],
        rule["game_formula"].strip(),
        tuple(float(points) for points in rule["placement_points"]),
        # ``.get`` with the same defaults ``compile_rules`` reads the jsonb by: a
        # row written without ``better`` ranks higher-first, it does not crash.
        tuple((column.get("key"), column.get("better", "higher")) for column in rule["columns"]),
    )


class StageCrudMixin(StageServiceBase):
    async def get_stage_progress(self, session: AsyncSession, tournament_id: int) -> list[dict]:
        """Return per-stage and per-stage_item progress (completed / total
        encounters). Used by admin UI to render the "Group A — 8/10 done" badge
        and to warn before starting a playoff with pending group matches. ``status`` is the stage node's.
        """
        stages_list = list(
            await self.stage_repo.list_by_tournament(session, tournament_id, options=[selectinload(models.Stage.items)])
        )
        if not stages_list:
            return []

        stage_ids = [s.id for s in stages_list]
        # GROUP BY in SQL: totals and completed counts, never encounter rows.
        counts = await session.execute(
            select(
                models.BracketEncounter.stage_id,
                models.BracketEncounter.stage_item_id,
                func.count().label("total"),
                func.coalesce(
                    func.sum(case((models.Encounter.status == enums.EncounterStatus.COMPLETED, 1), else_=0)),
                    0,
                ).label("completed"),
            )
            .join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id)
            .where(models.BracketEncounter.stage_id.in_(stage_ids))
            .group_by(models.BracketEncounter.stage_id, models.BracketEncounter.stage_item_id)
        )
        agg = {(row.stage_id, row.stage_item_id): (int(row.total), int(row.completed)) for row in counts}
        output: list[dict] = []
        for stage in stages_list:
            stage_total = 0
            stage_completed = 0
            item_progress: list[dict] = []
            for item in sorted(stage.items, key=lambda it: it.order):
                total, completed = agg.get((stage.id, item.id), [0, 0])
                stage_total += total
                stage_completed += completed
                item_progress.append(
                    {
                        "stage_item_id": item.id,
                        "name": item.name,
                        "total": total,
                        "completed": completed,
                        "is_completed": total > 0 and completed == total,
                    }
                )
            # Encounters with no stage_item_id still count toward the stage total.
            total, completed = agg.get((stage.id, None), [0, 0])
            stage_total += total
            stage_completed += completed

            output.append(
                {
                    "stage_id": stage.id,
                    "name": stage.name,
                    "stage_type": stage.stage_type.value,
                    "node_id": stage.node_id,
                    "status": stage.status,
                    "total": stage_total,
                    "completed": stage_completed,
                    "items": item_progress,
                }
            )
        return output

    async def create_stage(self, session: AsyncSession, tournament_id: int, data: schemas.StageCreate) -> models.Stage:
        tournament = await self.tournament_repo.get(session, tournament_id)
        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        # A supplied Challonge link becomes a challonge_source row scoped to the
        # new stage, not a stage column.
        payload = data.model_dump()
        challonge_id = payload.pop("challonge_id", None)
        challonge_slug = payload.pop("challonge_slug", None)
        stage = models.Stage(tournament_id=tournament_id)
        # Before the stage: ``stage.scoring_rule_id`` is NOT NULL, and every
        # encounter this stage generates points at the same row.
        stage.scoring_rule = models.ScoringRule(
            workspace_id=tournament.workspace_id,
            **rule_values(data.stage_type, payload.get("scoring") or {}),
        )
        _apply_stage_fields(stage, payload)
        _normalize_individual_swiss(stage)
        await self.stage_repo.create(session, stage)
        await self._add_stage_node(session, stage)
        if challonge_id is not None:
            session.add(
                models.ChallongeSource(
                    tournament_id=tournament_id,
                    stage_id=stage.id,
                    challonge_tournament_id=challonge_id,
                    slug=challonge_slug,
                    source_type="stage",
                )
            )
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        return await self.get_stage(session, stage.id)

    async def _add_stage_node(self, session: AsyncSession, stage: models.Stage) -> models.FlowNode:
        """The stage's ``draft`` node (spec §4.5), wired to its input only for the tournament's first stage.

        The input is ``formation.teams`` when the tournament has exactly one formation node, or -- for an individual
        Swiss stage, whose unit is players -- ``registration.participants`` when it has exactly one registration node.
        Every other edge is the organizer's to draw.
        """
        nodes = (
            await session.execute(
                select(models.FlowNode.id, models.FlowNode.kind).where(
                    models.FlowNode.tournament_id == stage.tournament_id
                )
            )
        ).all()
        by_kind: dict[str, list[int]] = {}
        for node_id, kind in nodes:
            by_kind.setdefault(kind, []).append(node_id)
        stage_count = len(by_kind.get(enums.FlowNodeKind.STAGE, []))
        node = models.FlowNode(
            tournament_id=stage.tournament_id,
            kind=enums.FlowNodeKind.STAGE,
            name=stage.name,
            status=enums.FlowNodeStatus.DRAFT,
            stage_id=stage.id,
            position_x=2 * X_STEP,
            position_y=stage_count * Y_STEP,
        )
        stage.node = node
        await session.flush()
        if stage_count == 0:
            individual = stage.stage_type == enums.StageType.INDIVIDUAL_SWISS
            sources = by_kind.get(enums.FlowNodeKind.REGISTRATION if individual else enums.FlowNodeKind.FORMATION, [])
            if len(sources) == 1:
                session.add(
                    models.FlowEdge(
                        tournament_id=stage.tournament_id,
                        source_node_id=sources[0],
                        source_port="participants" if individual else "teams",
                        target_node_id=node.id,
                        target_port="participants",
                    )
                )
                await session.flush()
        return node

    async def update_stage(self, session: AsyncSession, stage_id: int, data: schemas.StageUpdate) -> models.Stage:
        """Edit a stage's regulation.

        ``stage_type`` is not a plain field write: it decides the shape of the
        matches that were already generated, so it cannot be flipped under them
        -- a published Swiss silently becoming a single elimination leaves the
        bracket it already produced meaning nothing.
        """
        stage = await self.get_stage(session, stage_id)
        tournament_id = stage.tournament_id
        update_data = data.model_dump(exclude_unset=True)

        next_type = update_data.get("stage_type", stage.stage_type)
        if next_type != stage.stage_type:
            if stage.bracket_template is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Reset the custom bracket before changing the format",
                )
            existing = await self._count_stage_encounters(session, stage_id)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot change the format of a stage that already has {existing} generated "
                        "matches; delete them first"
                    ),
                )

        rule_before = rule_values(stage.stage_type, stage.scoring)
        if "scoring" in update_data:
            rule_after = rule_values(next_type, update_data["scoring"])
        elif next_type != stage.stage_type:
            # The stored rule is the OLD type's. An empty block is what "the one
            # the stage type implies" means, so a lobby stage turned round robin
            # becomes ``wins`` with its ``max_wins * 2 > best_of`` end rule (a Bo3
            # settles at 2-0 again) instead of keeping ``points`` and the columns
            # a duel never records.
            rule_after = rule_values(next_type, {})
        else:
            rule_after = rule_before
        if rule_after != rule_before:
            await self._assert_scoring_editable(session, stage, rule_before, rule_after)

        thresholds_before = SwissThresholds.of(stage)
        playoff_count_moved = await self._check_playoff_team_count_edit(session, stage, update_data)
        _apply_stage_fields(stage, update_data)
        _normalize_individual_swiss(stage)
        if "name" in update_data:
            stage.node.name = stage.name
        # The rule row is EDITED, never replaced: every encounter of the stage
        # points at its id, and a new row would leave the played ones scored by
        # the retired rule.
        for field, value in rule_after.items():
            setattr(stage.scoring_rule, field, value)
        # Points, places and the public table are all derived from the rules, so
        # a changed block has to re-run the standings: nothing else would, and
        # the same signal drops the gateway's cache of the lobby read. A moved
        # Swiss threshold re-decides who is through / out, and whether the
        # scope is over or owes another round.
        if rule_after != rule_before or SwissThresholds.of(stage) != thresholds_before or playoff_count_moved:
            await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        return await self.get_stage(session, stage.id)

    async def _check_playoff_team_count_edit(
        self, session: AsyncSession, stage: models.Stage, update_data: dict[str, Any]
    ) -> bool:
        """Whether this edit moves an ``individual_swiss`` stage's playoff team count (K), after validating it.

        K sets the per-role cut and the captain count, so a moved one re-runs the standings; it is refused once the
        qualification is locked (the list is frozen), and against a started stage's frozen pool it may not exceed
        the teams a round has.
        """
        if "playoff_team_count" not in update_data or stage.stage_type != enums.StageType.INDIVIDUAL_SWISS:
            return False
        if update_data.get("stage_type", stage.stage_type) != enums.StageType.INDIVIDUAL_SWISS:
            return False
        # An explicit null restores the default, like ``_normalize_individual_swiss``.
        wanted = update_data["playoff_team_count"] or DEFAULT_PLAYOFF_TEAMS
        if wanted == (stage.playoff_team_count or DEFAULT_PLAYOFF_TEAMS):
            return False
        if stage.qualification_locked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Квалификация уже закреплена: число команд плей-офф больше не меняется",
            )
        pool = await stage_players(session, stage.id)
        if pool:
            shape = (await tournament_slot_shape(session, stage.tournament_id)).slots
            try:
                check_playoff_team_count(
                    wanted,
                    teams_per_round(
                        [
                            PoolPlayer(
                                row.workspace_member_id, row.registration_id, row.display_name, row.role, row.rank
                            )
                            for row in pool
                        ],
                        shape,
                    ),
                    shape,
                )
            except PoolError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return True

    async def _assert_scoring_editable(
        self,
        session: AsyncSession,
        stage: models.Stage,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        """The scoring-rule edits a stage in play cannot take.

        Re-ranking edits (the preset, the formula, the placement points, the
        column keys, their ``better``) are refused once a playoff seeded off this
        stage has started -- the same rule, and the same 409, a result correction
        answers to. A formula reading ``place``/``place_pts`` is refused while
        live games hold no places: their places are derived from the formula's
        own points, so the cell and the place would contradict each other.
        Dropping a column the games hold values for is refused outright: the
        values are a record of the tournament, and no later edit brings them back.
        """
        if _ranking_signature(before) != _ranking_signature(after):
            await self.assert_stage_correction_allowed(session, stage)
        formula = compile_formula(after["game_formula"], [column["key"] for column in after["columns"]])
        if formula.names & PLACEMENT_VARIABLES and await self.result_repo.stage_has_unplaced_results(session, stage.id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    ApiExc(
                        code="ffa_formula_places_missing",
                        msg="Games of this stage have no places; enter them before the formula reads place",
                    )
                ],
            )
        removed = {column["key"] for column in before["columns"]} - {column["key"] for column in after["columns"]}
        if not removed:
            return
        in_use = sorted(removed & await self.result_repo.stat_keys_for_stage(session, stage.id))
        if in_use:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    ApiExc(
                        code="ffa_column_in_use",
                        msg=f"Games of this stage already hold values for: {', '.join(in_use)}",
                    )
                ],
            )

    async def delete_stage(self, session: AsyncSession, stage_id: int) -> None:
        stage = await self.get_stage(session, stage_id)
        if stage.status != enums.FlowNodeStatus.DRAFT:
            raise ApiHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[ApiExc(code="node_frozen", msg="A stage that left draft cannot be deleted")],
            )
        tournament_id = stage.tournament_id
        workspace_id = await session.scalar(
            select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
        )
        evidence = await capture_owner_delete(session, stage_id=stage_id)
        # Encounter.stage_id and Standing.stage_id reference Stage with ON DELETE
        # SET NULL, so deleting the stage alone would orphan its matches and
        # standings rather than remove them. Delete that derived data explicitly
        # first; the encounter's dependents (maps, match rows, links, mappings)
        # cascade from the encounter delete.
        await self.encounter_repo.delete_for_stage(session, stage_id)
        await self.standing_repo.delete_for_stage(session, stage_id)
        await self.stage_repo.delete(session, stage)
        await self._publish_structure_changed(session, tournament_id)
        await stage_owner_delete(session, evidence, workspace_id=workspace_id, entity_type="stage", entity_id=stage_id)
        await session.commit()

    async def delete_stage_item(self, session: AsyncSession, stage_item_id: int) -> None:
        """Delete one stage item (group/bracket lane) without deleting its stage.

        Same reasoning as ``delete_stage``: Encounter.stage_item_id and
        Standing.stage_item_id are ON DELETE SET NULL, so deleting the item alone
        would orphan its matches and standings rather than remove them. The item's
        own inputs cascade (StageItemInput.stage_item_id is ON DELETE CASCADE).
        """
        item = await self.get_stage_item(session, stage_item_id)
        tournament_id = await self.stage_repo.get_tournament_id(session, item.stage_id)
        workspace_id = await session.scalar(
            select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
        )
        evidence = await capture_owner_delete(session, stage_item_id=stage_item_id)
        await self.encounter_repo.delete_for_stage_item(session, stage_item_id)
        await self.standing_repo.delete_for_stage_item(session, stage_item_id)
        await self.stage_item_repo.delete(session, item)
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await stage_owner_delete(
            session,
            evidence,
            workspace_id=workspace_id,
            entity_type="stage_item",
            entity_id=stage_item_id,
        )
        await session.commit()

    async def create_stage_item(
        self, session: AsyncSession, stage_id: int, data: schemas.StageItemCreate
    ) -> models.StageItem:
        stage = await self.get_stage(session, stage_id)
        tournament_id = stage.tournament_id
        item = models.StageItem(stage_id=stage_id, **data.model_dump())
        await self.stage_item_repo.create(session, item)
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        item_id = item.id
        return await self.get_stage_item(session, item_id)

    async def update_stage_item(
        self,
        session: AsyncSession,
        stage_item_id: int,
        data: schemas.StageItemUpdate,
    ) -> models.StageItem:
        item = await self.get_stage_item(session, stage_item_id)
        tournament_id = await self.stage_repo.get_tournament_id(session, item.stage_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        return await self.get_stage_item(session, stage_item_id)

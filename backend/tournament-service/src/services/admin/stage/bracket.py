"""An elimination stage's bracket before it is generated: planned rounds, preview, custom template."""

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name_from_ids
from shared.domain.flow.config import FilterNodeConfig, parse_node_config
from src.domain.admin.best_of import best_of_config, resolve_best_of
from src.domain.bracket import (
    BracketSkeleton,
    BracketTemplate,
    generate_bracket,
    placeholder_bracket,
    placeholder_seeds,
    skeleton_to_template,
    template_to_skeleton,
    validate_template,
)
from src.domain.bracket.swiss import SwissThresholds, projected_status_count
from src.domain.stage.seeds import lower_bracket_item as _lower_bracket_item
from src.domain.stage.seeds import resolve_seeds as _resolve_seeds
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage_common import (
    BRACKET_STAGE_TYPES,
    _bracket_seeds,
)
from src.services.individual_swiss.standings import DEFAULT_PLAYOFF_TEAMS


class StageBracketMixin(StageServiceBase):
    async def get_planned_rounds(self, session: AsyncSession, stage_id: int) -> list[int]:
        """The round numbers this stage's bracket has, or will have.

        Elimination round numbering is not the plain ``1..max_rounds`` sequence
        ``max_rounds`` (an independently admin-set planning field) would suggest:
        double elimination's lower bracket uses negative numbers, and even single
        elimination's actual round count depends on team count, which may not
        match ``max_rounds`` at all. This lets a caller scope a cascade config
        (e.g. a pick-ban rule) to a round correctly before the bracket exists,
        rather than guessing and silently missing every lower-bracket round or
        landing a rule on a round number the eventual bracket will never have.

        Once encounters exist they are the ground truth. Before that, this
        predicts the same numbers the real generator will produce off the stage's
        seed counts (``_bracket_seed_counts``) -- empty when the stage type isn't a
        bracket, or no seeds are known or projected yet, in which case only the
        tournament-/stage-wide scopes are meaningful.
        """
        stage = await self.get_stage(session, stage_id)

        # DISTINCT projection of a single column: the round numbers only, never
        # the encounters themselves. The round lives on the bracket position,
        # so the stage's rounds are a read of that table alone.
        generated = await session.execute(
            select(models.BracketEncounter.round).where(models.BracketEncounter.stage_id == stage_id).distinct()
        )
        existing_rounds = sorted({row[0] for row in generated.all()})
        if existing_rounds:
            return existing_rounds

        if stage.stage_type not in BRACKET_STAGE_TYPES:
            return []

        if stage.bracket_template is not None:
            return sorted({match["round"] for match in stage.bracket_template["matches"]})

        upper_count, lower_count = await self._bracket_seed_counts(session, stage, estimate=True)
        skeleton = placeholder_bracket(
            stage.stage_type, upper_count, lower_count=lower_count, third_place_match=stage.third_place_match
        )
        return sorted({pairing.round_number for pairing in skeleton.pairings})

    async def get_bracket_preview(self, session: AsyncSession, stage_id: int) -> dict:
        """The bracket this stage would generate, as a read-only skeleton.

        Same generator, same seed order and same best-of resolution as
        ``_generate_bracket_encounters`` -> ``persist_skeleton``; nothing is
        written. That is the point: a preview drawn from a re-derived shape
        drifts from the real thing on exactly the cases that matter (byes in a
        non-power-of-two bracket, the lower bracket's cross-drops), so it is
        drawn from the generator instead.

        Wired teams come back under their real ids and names; an unseeded playoff
        falls back to the projected seed counts the way generation does, and every
        slot comes back TBD.

        ``local_id`` is 1-based and skeleton-local: ``sources`` reference it and
        not encounter ids, because these matches do not exist yet.
        """
        stage = await self.get_stage(session, stage_id)
        if stage.stage_type not in BRACKET_STAGE_TYPES:
            return {"matches": []}

        sorted_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        upper_ids, lower_ids = _bracket_seeds(sorted_items, _lower_bracket_item(stage, sorted_items))
        upper_ids = await self._rank_seed_ids(session, stage, upper_ids)
        lower_ids = await self._rank_seed_ids(session, stage, lower_ids)

        if stage.bracket_template is not None:
            template = BracketTemplate.model_validate(stage.bracket_template)
            if (len(upper_ids), len(lower_ids)) != (template.upper_seeds, template.lower_seeds):
                # Wired seeds do not fit the custom bracket (generation refuses until
                # they do): draw it with every slot TBD instead.
                upper_ids = placeholder_seeds(template.upper_seeds)
                lower_ids = placeholder_seeds(template.lower_seeds, offset=template.upper_seeds)

        if len(upper_ids) + len(lower_ids) < 2:
            upper_count, lower_count = await self._estimated_bracket_seed_counts(session, stage)
            if upper_count < 2:
                return {"matches": []}
            upper_ids = placeholder_seeds(upper_count)
            lower_ids = placeholder_seeds(lower_count, offset=upper_count)

        skeleton = _resolve_seeds(self._bracket_skeleton(stage, upper_ids, lower_ids), {})

        team_names_by_id = await self._load_team_names(session, upper_ids + lower_ids)
        best_of_cfg = best_of_config(stage)
        third_place_ids = skeleton.third_place_ids
        max_round = max(
            (pairing.round_number for pairing in skeleton.pairings if pairing.local_id not in third_place_ids),
            default=0,
        )
        sources: dict[int, list[dict]] = {}
        for edge in skeleton.advancement_edges:
            # A PLACE in the source encounter and a SEAT of the target: no
            # winner/loser or home/away on the wire.
            sources.setdefault(edge.target_local_id, []).append(
                {
                    "local_id": edge.source_local_id + 1,
                    "source_position": edge.source_position,
                    "slot": edge.target_slot,
                }
            )

        return {
            "matches": [
                {
                    "local_id": pairing.local_id + 1,
                    "round": pairing.round_number,
                    "name": build_encounter_name_from_ids(pairing.team_ids, team_names_by_id),
                    "best_of": resolve_best_of(
                        best_of_cfg,
                        pairing.round_number,
                        is_final=pairing.round_number == max_round and pairing.local_id not in third_place_ids,
                    ),
                    "is_third_place": pairing.local_id in third_place_ids,
                    "slot_count": pairing.slot_count,
                    "team_ids": list(pairing.team_ids),
                    "sources": sources.get(pairing.local_id, []),
                }
                for pairing in skeleton.pairings
            ]
        }

    def _bracket_skeleton(self, stage: models.Stage, upper_ids: list[int], lower_ids: list[int]) -> BracketSkeleton:
        """What ``generate_bracket`` returns for these seeds (real ids or ``placeholder_seeds``),
        drawn from the stage's custom template when it has one."""
        seeds = upper_ids + lower_ids
        duplicates = sorted({seed for seed in seeds if seeds.count(seed) > 1})
        if duplicates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Teams {', '.join(map(str, duplicates))} are seeded more than once in this stage. "
                    "Fix the bracket inputs."
                ),
            )
        if stage.bracket_template is None:
            return generate_bracket(
                stage.stage_type, upper_ids, lower_bracket_team_ids=lower_ids, third_place_match=stage.third_place_match
            )
        template = BracketTemplate.model_validate(stage.bracket_template)
        if (len(upper_ids), len(lower_ids)) != (template.upper_seeds, template.lower_seeds):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Custom bracket expects {template.upper_seeds}+{template.lower_seeds} seeds, stage has "
                    f"{len(upper_ids)}+{len(lower_ids)}. Edit or reset the custom bracket."
                ),
            )
        return _resolve_seeds(
            template_to_skeleton(template),
            dict(zip(placeholder_seeds(len(seeds)), seeds, strict=True)),
        )

    def _require_bracket_stage(self, stage: models.Stage) -> None:
        if stage.stage_type not in BRACKET_STAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only single/double elimination stages have a bracket layout",
            )

    async def get_bracket_template(self, session: AsyncSession, stage_id: int) -> dict:
        """The stage's custom bracket, or the one its format would generate now, plus the seed counts it has."""
        stage = await self.get_stage(session, stage_id)
        self._require_bracket_stage(stage)
        upper, lower = await self._bracket_seed_counts(session, stage)
        if stage.bracket_template is not None:
            template: dict | None = BracketTemplate.model_validate(stage.bracket_template).model_dump(mode="json")
        elif upper >= 2:
            generated = placeholder_bracket(
                stage.stage_type, upper, lower_count=lower, third_place_match=stage.third_place_match
            )
            template = skeleton_to_template(generated, upper_seeds=upper, lower_seeds=lower).model_dump(mode="json")
        else:
            template = None
        return {
            "custom": stage.bracket_template is not None,
            "template": template,
            "seeds": {"upper": upper, "lower": lower},
        }

    async def set_bracket_template(self, session: AsyncSession, stage_id: int, template: BracketTemplate) -> dict:
        stage = await self.get_stage(session, stage_id)
        self._require_bracket_stage(stage)
        await self._lock_stage(session, stage_id)
        await self._assert_no_encounters(session, stage_id)
        problems = validate_template(template, stage.stage_type)
        if problems:
            # A dict detail WITHOUT ``msg``: ``shared.rpc.common.http_error``'s attribute-bag
            # branch is the one that carries ``problems`` to the client untouched.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_bracket_template",
                    "message": f"bracket template has {len(problems)} problem(s)",
                    "problems": [asdict(problem) for problem in problems],
                },
            )
        stage.bracket_template = template.model_dump(mode="json")
        # A drawn bronze is the stage's third-place match: pre-game offers its own scope by this flag.
        stage.third_place_match = bool(template_to_skeleton(template).third_place_ids)
        await self._finish_structure_write(session, stage, notify=True, commit=True, schedule_standings=False)
        return await self.get_bracket_template(session, stage_id)

    async def clear_bracket_template(self, session: AsyncSession, stage_id: int) -> dict:
        stage = await self.get_stage(session, stage_id)
        self._require_bracket_stage(stage)
        await self._lock_stage(session, stage_id)
        await self._assert_no_encounters(session, stage_id)
        stage.bracket_template = None
        await self._finish_structure_write(session, stage, notify=True, commit=True, schedule_standings=False)
        return await self.get_bracket_template(session, stage_id)

    async def _bracket_seed_counts(
        self, session: AsyncSession, stage: models.Stage, *, estimate: bool = False
    ) -> tuple[int, int]:
        """How many teams start in ``stage``'s upper and lower bracket.

        Seated inputs are ground truth. Before any exist — the common case for a playoff seated only
        when it turns ``ready`` — the counts are projected from the rows of the stage's flow input, so the
        bracket can be planned, and generated, while the groups are still running; ``estimate`` reads
        ``_estimated_bracket_seed_counts`` instead.
        """
        sorted_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        upper, lower = _bracket_seeds(sorted_items, _lower_bracket_item(stage, sorted_items))
        if len(upper) + len(lower) >= 2:
            return len(upper), len(lower)
        if estimate:
            return await self._estimated_bracket_seed_counts(session, stage)
        return await self._projected_bracket_seed_counts(session, stage)

    async def _projected_bracket_seed_counts(self, session: AsyncSession, stage: models.Stage) -> tuple[int, int]:
        """The upper/lower seed counts the stage's flow input will seat: its rows, minus the lower starters (only a
        double-elimination stage has a lower bracket). ``(0, 0)`` without rows."""
        _, rows = await self._stage_input_rows(session, stage)
        lower = (
            sum((row.breakdown or {}).get("bracket") == "lower" for row in rows)
            if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
            else 0
        )
        return len(rows) - lower, lower

    async def _estimated_bracket_seed_counts(self, session: AsyncSession, stage: models.Stage) -> tuple[int, int]:
        """For drawing only (preview, planned rounds): ``_projected_bracket_seed_counts``, except that a stage fed by
        a ``swiss_status`` filter is counted from what its Swiss will pass (``_projected_swiss_status_count``).

        Never fed to generation: a bracket built off an estimate the Swiss then misses would refuse its real seeds
        (``_fill_bracket_seeds``).
        """
        node, _ = await self._stage_input_rows(session, stage)
        if node is not None and (passing := await self._projected_swiss_status_count(session, node)) is not None:
            return passing, 0
        return await self._projected_bracket_seed_counts(session, stage)

    async def _projected_swiss_status_count(self, session: AsyncSession, node: models.FlowNode) -> int | None:
        """How many teams a ``swiss_status`` filter wired straight off a running Swiss stage will pass.

        Its rows only hold the teams decided so far, so they undercount the field until that stage completes; the
        count is replayed from each scope instead (``swiss.projected_status_count``). ``None`` for any other input,
        and once the Swiss stage completed: its rows are then the truth.
        """
        gate = await self._sole_source(session, node.id, port="participants")
        if gate is None or gate.kind != enums.FlowNodeKind.FILTER:
            return None
        config = parse_node_config(gate.kind, gate.config)
        if not isinstance(config, FilterNodeConfig) or config.mode != "swiss_status" or config.swiss_status is None:
            return None
        source = await self._sole_source(session, gate.id)
        if source is None or source.stage_id is None or source.status == enums.FlowNodeStatus.COMPLETED:
            return None
        swiss = await self.get_stage(session, source.stage_id)
        if swiss.stage_type != enums.StageType.SWISS:
            return None
        sizes = [
            sum(inp.team_id is not None and inp.input_type != enums.StageItemInputType.EMPTY for inp in item.inputs)
            for item in swiss.items
        ]
        if not any(sizes):
            # Not seated yet: its estimated field, dealt evenly over its groups.
            teams, groups = await self._estimated_team_count(session, source, swiss), max(1, len(swiss.items))
            sizes = [teams // groups + (i < teams % groups) for i in range(groups)]
        thresholds = SwissThresholds.of(swiss)
        return sum(projected_status_count(size, swiss.max_rounds, thresholds, config.swiss_status) for size in sizes)

    async def _estimated_team_count(self, session: AsyncSession, node: models.FlowNode, stage: models.Stage) -> int:
        """The teams an unseated stage will get: its input's rows, else — no team formed yet — the K teams a draft
        formation forms off an individual Swiss's qualifiers (``playoff_team_count``). 0 when neither tells."""
        _, rows = await self._stage_input_rows(session, stage)
        if rows:
            return len(rows)
        formation = await self._sole_source(session, node.id, port="participants")
        if (
            formation is None
            or formation.kind != enums.FlowNodeKind.FORMATION
            or formation.config.get("mode") != "draft"
        ):
            return 0
        source = await self._sole_source(session, formation.id)
        while source is not None and source.kind == enums.FlowNodeKind.FILTER:
            source = await self._sole_source(session, source.id)
        if source is None or source.stage_id is None:
            return 0
        qualifier = await self.get_stage(session, source.stage_id)
        if qualifier.stage_type != enums.StageType.INDIVIDUAL_SWISS:
            return 0
        return qualifier.playoff_team_count or DEFAULT_PLAYOFF_TEAMS

    async def _sole_source(
        self, session: AsyncSession, node_id: int, *, port: str | None = None
    ) -> models.FlowNode | None:
        """The one node wired into ``node_id`` (on ``port``); ``None`` when none or several are."""
        query = (
            select(models.FlowNode)
            .join(models.FlowEdge, models.FlowEdge.source_node_id == models.FlowNode.id)
            .where(models.FlowEdge.target_node_id == node_id)
        )
        if port is not None:
            query = query.where(models.FlowEdge.target_port == port)
        sources = (await session.scalars(query)).all()
        return sources[0] if len(sources) == 1 else None

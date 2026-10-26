"""An elimination stage's bracket before it is generated: planned rounds, preview, custom template."""

from dataclasses import asdict
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name_from_ids
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
from src.domain.stage.seeds import group_advance_counts
from src.domain.stage.seeds import lower_bracket_item as _lower_bracket_item
from src.domain.stage.seeds import resolve_seeds as _resolve_seeds
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage_common import (
    BRACKET_STAGE_TYPES,
    _bracket_seeds,
)


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

        upper_count, lower_count = await self._bracket_seed_counts(session, stage)
        skeleton = placeholder_bracket(stage.stage_type, upper_count, lower_count=lower_count)
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
            upper_count, lower_count = await self._projected_bracket_seed_counts(session, stage)
            if upper_count < 2:
                return {"matches": []}
            upper_ids = placeholder_seeds(upper_count)
            lower_ids = placeholder_seeds(lower_count, offset=upper_count)

        skeleton = _resolve_seeds(self._bracket_skeleton(stage, upper_ids, lower_ids), {})

        team_names_by_id = await self._load_team_names(session, upper_ids + lower_ids)
        best_of_cfg = best_of_config(stage)
        max_round = max((pairing.round_number for pairing in skeleton.pairings), default=0)
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
                        is_final=pairing.round_number == max_round,
                    ),
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
            return generate_bracket(stage.stage_type, upper_ids, lower_bracket_team_ids=lower_ids)
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
            generated = placeholder_bracket(stage.stage_type, upper, lower_count=lower)
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

    async def _bracket_seed_counts(self, session: AsyncSession, stage: models.Stage) -> tuple[int, int]:
        """How many teams start in ``stage``'s upper and lower bracket.

        Wired inputs (including still-TENTATIVE ones once activation resolves them)
        are ground truth. Before any exist — the common case for a playoff seeded
        only after its groups finish — the counts are projected from the preceding
        group stage instead, so the bracket can be planned, and generated, off the
        ``advance_count`` alone.
        """
        sorted_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        upper, lower = _bracket_seeds(sorted_items, _lower_bracket_item(stage, sorted_items))
        if len(upper) + len(lower) >= 2:
            return len(upper), len(lower)
        return await self._projected_bracket_seed_counts(session, stage)

    async def _projected_bracket_seed_counts(self, session: AsyncSession, stage: models.Stage) -> tuple[int, int]:
        """The upper/lower seed counts the preceding group stage will feed into
        ``stage``, mirroring ``_auto_wire_from_groups``: each group of the nearest
        earlier Swiss/round-robin stage sends its own ``advance_count`` (falling
        back to the stage's), split per group by ``advance_upper_count``. Only a
        DOUBLE_ELIMINATION stage has a lower bracket, so anywhere
        else the split is ignored and everyone advancing is an upper seed.
        ``(0, 0)`` when there is no such source, or nothing is configured
        to advance."""
        source = await self._preceding_group_stage(session, stage)
        if source is None:
            return 0, 0
        items = sorted(source.items, key=lambda item: (item.order, item.id))
        # A source stage with no groups at all is one implicit group.
        groups = items or [SimpleNamespace(id=0, advance_count=None, advance_upper_count=None)]
        counts = group_advance_counts(
            groups, default_advance=source.advance_count or 0, default_upper=source.advance_upper_count
        )
        upper = sum(item_upper for _, item_upper, _ in counts)
        lower = sum(item_lower for _, _, item_lower in counts)
        if stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
            upper, lower = upper + lower, 0
        return (upper, lower) if upper + lower else (0, 0)

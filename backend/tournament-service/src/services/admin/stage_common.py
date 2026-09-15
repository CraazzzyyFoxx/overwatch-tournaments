"""Module-level helpers the admin stage service and its tests share."""

from __future__ import annotations

from shared.core import enums
from shared.models.tournament.pick_ban import PickBanConfig
from src import models
from src.domain.stage.seeds import bracket_seeds, collect_item_team_ids

__all__ = (
    "BRACKET_STAGE_TYPES",
    "GROUPED_GENERATION_STAGE_TYPES",
    "_apply_seeding",
    "_bracket_seeds",
    "_collect_item_team_ids",
    "_pick_ban_config_signature",
)

GROUPED_GENERATION_STAGE_TYPES = {
    enums.StageType.ROUND_ROBIN,
    enums.StageType.SWISS,
}

BRACKET_STAGE_TYPES = {
    enums.StageType.SINGLE_ELIMINATION,
    enums.StageType.DOUBLE_ELIMINATION,
}

_collect_item_team_ids = collect_item_team_ids


def _bracket_seeds(stage, sorted_items, lb_item):
    return bracket_seeds(stage, sorted_items, lb_item, collect=_collect_item_team_ids)


def _pick_ban_config_signature(
    config: PickBanConfig,
) -> tuple[tuple, tuple, enums.MapVetoMode, enums.FirstBanRotation | None, tuple]:
    rotation = config.first_ban_rotation if config.mode == enums.MapVetoMode.SLOTS else None
    return (
        tuple(config.sequence_json or []),
        tuple(entry.item_id for entry in config.items),
        config.mode,
        rotation,
        tuple(
            (
                slot.position,
                slot.reserve_item_id,
                tuple(entry.item_id for entry in sorted(slot.items, key=lambda row: (row.sort_order, row.item_id))),
            )
            for slot in sorted(config.slots, key=lambda row: row.position)
        ),
    )


def _apply_seeding(session, seeding: list[tuple[int, int]], target_item) -> None:
    """Replace ``target_item``'s TENTATIVE inputs with ``seeding``.

    A replacement, not a merge: cutting the advance from top-2 to top-1 has to
    drop the second-place slots too, or the bracket keeps playing the teams the
    new configuration no longer qualifies. FINAL (manually assigned) inputs are
    never touched, at either end.
    """
    existing_inputs = {inp.slot: inp for inp in target_item.inputs}
    for idx, (source_item_id, source_position) in enumerate(seeding, start=1):
        existing = existing_inputs.get(idx)
        if existing is not None and existing.input_type == enums.StageItemInputType.FINAL:
            continue
        if existing is not None:
            existing.input_type = enums.StageItemInputType.TENTATIVE
            existing.source_stage_item_id = source_item_id
            existing.source_position = source_position
            existing.team_id = None
        else:
            new_input = models.StageItemInput(
                stage_item_id=target_item.id,
                slot=idx,
                input_type=enums.StageItemInputType.TENTATIVE,
                source_stage_item_id=source_item_id,
                source_position=source_position,
                team_id=None,
            )
            session.add(new_input)
            target_item.inputs.append(new_input)

    # ``StageItem.inputs`` is delete-orphan: dropping the row from the collection
    # is the delete, and unlike ``session.delete`` it needs no await -- this
    # helper is deliberately synchronous.
    for existing in list(target_item.inputs):
        if existing.input_type == enums.StageItemInputType.TENTATIVE and existing.slot > len(seeding):
            target_item.inputs.remove(existing)

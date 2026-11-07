"""Module-level helpers the admin stage service and its tests share."""

from __future__ import annotations

import json

from shared.core import enums
from shared.models.tournament.pick_ban import PickBanConfig
from src.domain.stage.seeds import bracket_seeds, collect_item_team_ids

__all__ = (
    "BRACKET_STAGE_TYPES",
    "FFA_STAGE_TYPES",
    "GROUPED_GENERATION_STAGE_TYPES",
    "_bracket_seeds",
    "_collect_item_team_ids",
    "_pick_ban_config_signature",
)

GROUPED_GENERATION_STAGE_TYPES = {
    enums.StageType.ROUND_ROBIN,
    enums.StageType.SWISS,
}

FFA_STAGE_TYPES = frozenset({enums.StageType.FFA_LEAGUE})

BRACKET_STAGE_TYPES = {
    enums.StageType.SINGLE_ELIMINATION,
    enums.StageType.DOUBLE_ELIMINATION,
}

_collect_item_team_ids = collect_item_team_ids


def _bracket_seeds(sorted_items, lb_item):
    return bracket_seeds(sorted_items, lb_item, collect=_collect_item_team_ids)


def _pick_ban_config_signature(
    config: PickBanConfig,
) -> tuple[str, tuple, enums.MapVetoMode, enums.FirstBanRotation | None, tuple]:
    """What makes two pick-ban configs "the same rules" for a stage merge.

    The rules half is the ruleset document, canonically dumped: it is a nested
    tree, so ``==`` on the dicts would be key-order-insensitive but unhashable,
    and this value goes into a ``set``. ``sort_keys`` makes two configs that were
    authored in a different field order compare equal, which is what an organizer
    means by "identical rules".
    """
    rotation = config.first_ban_rotation if config.mode != enums.MapVetoMode.POOL else None
    return (
        json.dumps(config.ruleset_json or {}, sort_keys=True, separators=(",", ":")),
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

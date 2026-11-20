"""Pick-ban pool presence and cascade ranking, shared by rooms and log ingestion."""

from collections.abc import Iterable

from shared.core.enums import MapVetoMode
from shared.models.tournament.pick_ban import PickBanConfig


def has_pool(config: PickBanConfig) -> bool:
    """Pool-less configs are rules templates, not restrictions on playable maps."""
    return bool(config.slots) if config.mode == MapVetoMode.SLOTS else bool(config.items)


def pick_config(
    candidates: Iterable[PickBanConfig], *, stage_id: int | None, round: int | None, third_place: bool = False
) -> PickBanConfig | None:
    """Rank round > stage > tournament, without letting templates shadow pools.

    A bronze config is its own round-level scope: only a bronze encounter matches it, and a bronze encounter never
    falls back to the final's round config.

    Callers narrow candidates to the tournament and kind before resolving. If
    every matching config is a template, return the most specific template.
    """
    matched: list[tuple[int, PickBanConfig]] = []
    for config in candidates:
        if (
            config.round is not None
            and config.round == round
            and config.stage_id == stage_id
            and bool(config.third_place) == third_place
        ):
            rank = 2
        elif config.stage_id == stage_id and config.round is None:
            rank = 1
        elif config.stage_id is None and config.round is None:
            rank = 0
        else:
            continue
        matched.append((rank, config))
    if not matched:
        return None
    ranked = sorted(matched, key=lambda pair: -pair[0])
    pooled = [config for _, config in ranked if has_pool(config)]
    if pooled:
        return pooled[0]
    return max(matched, key=lambda pair: pair[0])[1]


def pool_items(
    configs: Iterable[PickBanConfig], *, stage_id: int | None, round: int | None, third_place: bool = False
) -> set[int] | None:
    """Every item the effective pool for (stage, round) names (slot candidates and reserves included); ``None`` when
    no pool applies, which admits anything."""
    config = pick_config(configs, stage_id=stage_id, round=round, third_place=third_place)
    if config is None or not has_pool(config):
        return None
    if config.mode == MapVetoMode.SLOTS:
        return {item.item_id for slot in config.slots for item in slot.items} | {
            slot.reserve_item_id for slot in config.slots if slot.reserve_item_id is not None
        }
    return {item.item_id for item in config.items}

"""Pick-ban pool presence and cascade ranking, shared by rooms and log ingestion."""

from collections.abc import Iterable

from shared.core.enums import MapVetoMode
from shared.models.tournament.pick_ban import PickBanConfig


def has_pool(config: PickBanConfig) -> bool:
    """Pool-less configs are rules templates, not restrictions on playable maps."""
    return bool(config.slots) if config.mode == MapVetoMode.SLOTS else bool(config.items)


def pick_config(
    candidates: Iterable[PickBanConfig], *, stage_id: int | None, round: int | None
) -> PickBanConfig | None:
    """Rank round > stage > tournament, without letting templates shadow pools.

    Callers narrow candidates to the tournament and kind before resolving. If
    every matching config is a template, return the most specific template.
    """
    matched: list[tuple[int, PickBanConfig]] = []
    for config in candidates:
        if config.round is not None and config.round == round and config.stage_id == stage_id:
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

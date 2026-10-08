"""In-memory stand-ins for the mix ranker's tables, shared by the mix tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from src.services.mix_ranker import MixRankerService


class InMemoryHiddenRatings:
    """``balancer.member_hidden_rating`` as a dict keyed by ``(member, role)``."""

    def __init__(self) -> None:
        self.book: dict[tuple[int, str], tuple[float, float]] = {}

    async def for_members(
        self, _session: Any, *, workspace_id: int, member_ids: Sequence[int], for_update: bool = False
    ) -> dict[tuple[int, str], tuple[float, float]]:
        wanted = set(member_ids)
        return {key: value for key, value in self.book.items() if key[0] in wanted}

    async def upsert_many(
        self, _session: Any, *, workspace_id: int, ratings: Mapping[tuple[int, str], tuple[float, float]]
    ) -> None:
        self.book.update(ratings)

    async def replace_for_workspace(
        self, _session: Any, *, workspace_id: int, ratings: Mapping[tuple[int, str], tuple[float, float]]
    ) -> None:
        self.book = dict(ratings)

    async def count_for_workspace(self, _session: Any, _workspace_id: int) -> int:
        return len(self.book)


class _Configs:
    """``balancer.workspace_config``: one workspace, ranker knobs only."""

    def __init__(self, ranker_json: Mapping[str, Any] | None = None) -> None:
        self.row = SimpleNamespace(ranker_json=dict(ranker_json)) if ranker_json is not None else None

    async def get_by_workspace(self, _session: Any, _workspace_id: int) -> Any:
        return self.row


class _History:
    """``casual.*`` as the replay query returns it: one row per frozen seat, in order."""

    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []

    async def replay_seats_for_workspace(self, _session: Any, _workspace_id: int) -> list[tuple[Any, ...]]:
        return list(self.rows)


def in_memory_ranker(ranker_json: Mapping[str, Any] | None = None) -> MixRankerService:
    """A real ``MixRankerService`` over dicts; reach the fakes via ``.hidden`` / ``.casual_matches``."""
    return MixRankerService(hidden=InMemoryHiddenRatings(), configs=_Configs(ranker_json), casual_matches=_History())

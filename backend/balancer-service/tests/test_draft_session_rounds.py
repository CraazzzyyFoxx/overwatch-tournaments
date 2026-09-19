"""``create_session`` derives ``rounds`` from the roster shape.

The scalar ``team_size`` is gone: a draft has exactly one pick per roster slot the
captain does not fill, and the roster shape is the only thing that knows how many
slots that is. These tests pin the derivation and the shape of the signature, so
a caller can no longer smuggle a size in beside the shape.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from src.services.draft import lifecycle  # noqa: E402


class _FakeSession:
    """Just enough AsyncSession for ``create_session``: no active draft, no DB."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    async def scalar(self, statement: Any) -> None:
        return None  # `assert_no_active_draft` finds nothing

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def refresh(self, instance: Any) -> None:
        return None


def _create(**kwargs: Any):
    return asyncio.run(
        lifecycle.lifecycle_service.create_session(_FakeSession(), tournament_id=1, workspace_id=2, **kwargs)  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("slots", "expected_rounds"),
    [
        ({"flex": 6}, 5),
        ({"tank": 1, "damage": 2, "support": 2}, 4),
        ({"tank": 1, "damage": 2}, 2),
        ({"tank": 1, "flex": 1}, 1),
    ],
)
def test_rounds_come_from_the_shape(slots: dict[str, int], expected_rounds: int) -> None:
    draft = _create(shape=parse_roster_slots(slots))

    assert draft.rounds == expected_rounds


def test_the_shape_is_required_and_the_scalars_are_gone() -> None:
    parameters = inspect.signature(lifecycle.lifecycle_service.create_session).parameters

    assert parameters["shape"].default is inspect.Parameter.empty
    assert "team_size" not in parameters
    assert "rounds" not in parameters


@pytest.mark.parametrize("scalar", ["team_size", "rounds"])
def test_passing_a_scalar_size_is_a_type_error(scalar: str) -> None:
    with pytest.raises(TypeError):
        _create(shape=parse_roster_slots({"flex": 6}), **{scalar: 3})


def test_the_session_row_never_stores_a_size_of_its_own() -> None:
    # Phase B drops the column; until then the model still has a default, so this
    # asserts the writer stopped SETTING it rather than that it cannot exist.
    source = inspect.getsource(lifecycle.lifecycle_service.create_session)

    assert "team_size" not in source

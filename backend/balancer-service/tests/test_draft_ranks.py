from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.core.enums import DraftRole  # noqa: E402
from shared.models.balancer.draft import DraftPlayer  # noqa: E402
from src.services.draft import ranks  # noqa: E402


def _player(*, primary="dps", rank_value=3000, role_ranks=None) -> DraftPlayer:
    return DraftPlayer(
        session_id=1,
        primary_role=primary,
        rank_value=rank_value,
        role_ranks=role_ranks or {},
    )


def test_primary_role_uses_role_ranks_entry() -> None:
    p = _player(primary="dps", rank_value=4000, role_ranks={"dps": 4000, "support": 2800})
    assert ranks.role_rank(p, DraftRole.DPS) == 4000


def test_off_role_uses_its_own_rank_not_primary() -> None:
    p = _player(primary="dps", rank_value=4000, role_ranks={"dps": 4000, "support": 2800})
    assert ranks.role_rank(p, DraftRole.SUPPORT) == 2800


def test_falls_back_to_rank_value_when_role_missing() -> None:
    p = _player(primary="dps", rank_value=4000, role_ranks={"dps": 4000})
    assert ranks.role_rank(p, DraftRole.TANK) == 4000


def test_none_role_returns_rank_value() -> None:
    p = _player(rank_value=3300, role_ranks={"support": 2800})
    assert ranks.role_rank(p, None) == 3300


def test_accepts_string_role() -> None:
    p = _player(primary="dps", rank_value=4000, role_ranks={"support": 2800})
    assert ranks.role_rank(p, "support") == 2800


def test_empty_role_ranks_falls_back() -> None:
    p = _player(primary="tank", rank_value=3500, role_ranks={})
    assert ranks.role_rank(p, DraftRole.TANK) == 3500
    assert ranks.role_rank(p, DraftRole.DPS) == 3500

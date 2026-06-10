"""Unit tests for injecting OW rank deltas into the registrations response."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

reg_admin = importlib.import_module("src.services.registration.admin")
serializers = importlib.import_module("src.services.registration.serializers")
player_sub_roles = importlib.import_module("shared.domain.player_sub_roles")


def test_snapshot_role_translates_damage_to_dps() -> None:
    # The snapshot uses the canonical RankRole ("damage"); the registration uses "dps".
    # Translation now lives in shared and is used by shared.services.rank_snapshots.
    assert player_sub_roles.canonical_to_registration_role("damage") == "dps"
    assert player_sub_roles.canonical_to_registration_role("tank") == "tank"
    assert player_sub_roles.canonical_to_registration_role("support") == "support"


def _role_model(role: str, rank_value: int | None):
    # Transient ORM instance: unloaded `hero_entries` -> _role_top_heroes returns [].
    return reg_admin.models.BalancerRegistrationRole(
        role=role, subrole=None, priority=1, is_primary=True, rank_value=rank_value, is_active=True
    )


def test_serialize_role_carries_ow_rank_value() -> None:
    out = serializers.serialize_registration_role(_role_model("dps", 500), ow_rank_value=3000)

    assert out.rank_value == 500
    assert out.ow_rank_value == 3000


def test_serialize_role_defaults_ow_rank_to_none() -> None:
    assert serializers.serialize_registration_role(_role_model("tank", 500)).ow_rank_value is None

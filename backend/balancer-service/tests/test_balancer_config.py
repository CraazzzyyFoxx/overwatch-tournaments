from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

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
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.domain.balancer.config_provider import (  # noqa: E402
    EDITABLE_CONFIG_FIELD_KEYS,
    get_balancer_config_payload,
    normalize_tournament_config_payload,
)
from src.schemas.team import InternalBalancerTeamsPayload  # noqa: E402
from src.services.admin import balancer as balancer_admin_service  # noqa: E402


def test_config_payload_exposes_complete_editable_field_metadata() -> None:
    payload = get_balancer_config_payload()

    fields = payload["fields"]
    field_keys = {field["key"] for field in fields}

    assert field_keys == EDITABLE_CONFIG_FIELD_KEYS
    assert {"workspace_id", "tournament_id", "division_grid"}.isdisjoint(field_keys)

    fields_by_key = {field["key"]: field for field in fields}
    assert fields_by_key["population_size"]["limits"] == {"min": 10, "max": 1000}
    assert fields_by_key["mutation_strength"]["limits"] == {"min": 1, "max": 10}
    assert fields_by_key["max_result_variants"]["limits"] == {"min": 1, "max": 200}
    assert fields_by_key["sub_role_collision_weight"]["limits"] == {"min": 0.0, "max": 10000.0}
    assert fields_by_key["internal_role_spread_weight"]["limits"] == {"min": 0.0, "max": 10000.0}
    assert fields_by_key["tank_impact_weight"]["limits"] == {"min": 0.0, "max": 10000.0}
    assert fields_by_key["mutation_rate_min"]["limits"] == {"min": 0.0, "max": 1.0}
    assert fields_by_key["island_count"]["limits"] == {"min": 1, "max": 64}
    assert fields_by_key["role_mask"]["type"] == "role_mask"
    assert "input_role_mapping" not in field_keys
    assert "elitism_rate" not in field_keys
    assert "stagnation_threshold" not in field_keys
    assert "algorithm" not in field_keys
    assert "algorithm" not in payload["defaults"]
    # Per-team normalized defaults (Rust divides extensive terms by team count;
    # values pre-multiplied to keep legacy 4-team behaviour)
    assert payload["defaults"]["intra_team_std_weight"] == 2.8
    assert payload["defaults"]["internal_role_spread_weight"] == 1.2
    assert payload["defaults"]["sub_role_collision_weight"] == 24.0
    assert payload["defaults"]["team_max_pain_weight"] == 1.0
    assert payload["defaults"]["tank_gap_weight"] == 1.0
    assert payload["defaults"]["tank_impact_weight"] == 1.4
    assert payload["defaults"]["mutation_rate_min"] == 0.15
    assert payload["defaults"]["crossover_rate"] == 0.85

    for field in fields:
        assert field["label"]
        assert field["description"]
        assert field["group"] in {"Roles", "Algorithm", "Quality weights", "Strategy", "Solver output"}
        assert field["default"] == payload["defaults"].get(field["key"])
        assert field["applies_to"]


def test_normalize_tournament_config_payload_keeps_only_valid_editable_fields() -> None:
    normalized = normalize_tournament_config_payload(
        {
            "population_size": 150,
            "use_captains": None,
            "role_mask": {"Tank": 1, "Damage": 2, "Support": 2},
            "workspace_id": 7,
        }
    )

    assert normalized == {
        "population_size": 150,
        "role_mask": {"Tank": 1, "Damage": 2, "Support": 2},
    }


def test_normalize_tournament_config_payload_ignores_legacy_role_mapping() -> None:
    normalized = normalize_tournament_config_payload(
        {
            "population_size": 150,
            "input_role_mapping": {"tank": "Tank", "dps": "Damage"},
        }
    )

    assert normalized == {
        "population_size": 150,
    }


def test_normalize_tournament_config_payload_drops_deprecated_moo_keys() -> None:
    normalized = normalize_tournament_config_payload(
        {
            "population_size": 150,
            "elitism_rate": 0.2,
            "stagnation_threshold": 30,
        }
    )

    assert normalized == {
        "population_size": 150,
    }


def test_normalize_tournament_config_payload_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        normalize_tournament_config_payload({"population_size": 1})


def test_normalize_tournament_config_payload_rejects_legacy_keys_and_algorithms() -> None:
    with pytest.raises(ValidationError):
        normalize_tournament_config_payload({"ALGORITHM": "moo"})

    with pytest.raises(ValidationError):
        normalize_tournament_config_payload({"algorithm": "genetic_moo"})


def test_internal_balance_payload_rejects_legacy_result_shape() -> None:
    with pytest.raises(ValidationError):
        InternalBalancerTeamsPayload.model_validate(
            {
                "teams": [
                    {
                        "id": 1,
                        "name": "Team 1",
                        "avgMMR": 2500.0,
                        "variance": 1.0,
                        "roster": {"Tank": []},
                    }
                ]
            }
        )


def test_internal_balance_payload_accepts_public_player_shape_with_is_flex() -> None:
    payload = InternalBalancerTeamsPayload.model_validate(
        {
            "teams": [
                {
                    "id": 1,
                    "name": "Team 1",
                    "average_mmr": 2500.0,
                    "rating_variance": 0.0,
                    "total_discomfort": 0,
                    "max_discomfort": 0,
                    "roster": {
                        "Damage": [
                            {
                                "uuid": "player-1",
                                "name": "Player#1234",
                                "assigned_rating": 2500,
                                "role_discomfort": 0,
                                "is_captain": False,
                                "role_preferences": ["Damage", "Support"],
                                "all_ratings": {"Damage": 2500, "Support": 2400},
                                "is_flex": True,
                            }
                        ]
                    },
                }
            ],
            "statistics": {
                "average_mmr": 2500.0,
                "mmr_std_dev": 0.0,
                "total_teams": 1,
                "players_per_team": 1,
            },
            "benched_players": [],
        }
    )

    player = payload.teams[0].roster["Damage"][0]
    assert player.is_flex is True
    assert player.rating == 2500
    assert player.discomfort == 0
    assert player.preferences == ["Damage", "Support"]


class TournamentConfigPersistenceTests(IsolatedAsyncioTestCase):
    async def test_upsert_tournament_config_creates_normalized_row(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        user = SimpleNamespace(id=42)

        with (
            patch.object(balancer_admin_service, "get_tournament_workspace_id", AsyncMock(return_value=9)),
            patch.object(balancer_admin_service, "get_tournament_config", AsyncMock(return_value=None)),
        ):
            result = await balancer_admin_service.upsert_tournament_config(
                session,
                77,
                {"population_size": 150, "use_captains": None, "workspace_id": 9},
                user,
            )

        self.assertEqual(result.tournament_id, 77)
        self.assertEqual(result.workspace_id, 9)
        self.assertEqual(result.config_json, {"population_size": 150})
        self.assertEqual(result.updated_by, 42)
        session.add.assert_called_once_with(result)
        session.commit.assert_awaited_once()

    async def test_upsert_tournament_config_updates_existing_row(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        user = SimpleNamespace(id=43)
        existing = SimpleNamespace(
            tournament_id=77,
            workspace_id=9,
            config_json={"population_size": 150},
            updated_by=42,
            updated_at=None,
        )

        with (
            patch.object(balancer_admin_service, "get_tournament_workspace_id", AsyncMock(return_value=9)),
            patch.object(balancer_admin_service, "get_tournament_config", AsyncMock(return_value=existing)),
        ):
            result = await balancer_admin_service.upsert_tournament_config(
                session,
                77,
                {"max_result_variants": 6},
                user,
            )

        self.assertIs(result, existing)
        self.assertEqual(existing.config_json, {"max_result_variants": 6})
        self.assertEqual(existing.updated_by, 43)
        session.add.assert_not_called()
        session.commit.assert_awaited_once()

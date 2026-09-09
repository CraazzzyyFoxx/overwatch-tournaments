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

os.environ["DEBUG"] = "false"

from src.schemas.team import InternalBalancerTeamsPayload  # noqa: E402
from src.services.admin.balancer import balancer_admin_service  # noqa: E402
from src.services.balancer.config.provider import (  # noqa: E402
    EDITABLE_CONFIG_FIELD_KEYS,
    get_balancer_config_payload,
    normalize_tournament_config_payload,
)


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
    assert "role_mask" not in field_keys
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


def test_normalize_tournament_config_payload_keeps_only_valid_editable_fields() -> None:
    normalized = normalize_tournament_config_payload(
        {
            "population_size": 150,
            "use_captains": None,
            # No longer editable: the per-team slot counts come from the
            # tournament roster shape, so a saved copy is dropped rather than
            # allowed to contradict it.
            "role_mask": {"Tank": 1, "Damage": 2, "Support": 2},
            "workspace_id": 7,
        }
    )

    assert normalized == {"population_size": 150}


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


def test_normalize_balance_response_payload_upgrades_legacy_camel_case_row() -> None:
    """Regression: GET /balance must load rows saved before the camelCase ->
    snake_case rename instead of 500-ing on ``BalanceResponse`` validation.
    """

    from src.services.balancer.config.public_contract import (
        normalize_balance_response_payload,
    )

    normalized = normalize_balance_response_payload(
        {
            "teams": [
                {
                    "id": 1,
                    "name": "Team 1",
                    "avgMMR": 2500.0,
                    "variance": 1.0,
                    "totalDiscomfort": 100,
                    "maxDiscomfort": 100,
                    "roster": {
                        "Tank": [
                            {
                                "uuid": "297",
                                "name": "Player#1234",
                                "rating": 2500,
                                "discomfort": 100,
                                "isCaptain": True,
                                "preferences": ["Tank", "Damage"],
                                "allRatings": {"Tank": 2500, "Damage": 2400},
                                "isFlex": False,
                                "subRole": None,
                            }
                        ]
                    },
                }
            ],
            "statistics": {
                "averageMMR": 2422.47,
                "mmrStdDev": 6.91,
                "totalTeams": 1,
                "playersPerTeam": 1,
                "offRoleCount": 1,
                "subRoleCollisionCount": 0,
                "unbalancedCount": 0,
            },
            "benchedPlayers": [
                {
                    "uuid": "298",
                    "name": "Bench#1234",
                    "rating": 2000,
                    "discomfort": 0,
                    "isCaptain": False,
                    "preferences": ["Support"],
                    "allRatings": {"Support": 2000},
                    "isFlex": False,
                    "subRole": "main_heal",
                }
            ],
        }
    )

    team = normalized["teams"][0]
    assert team["average_mmr"] == 2500.0
    assert team["rating_variance"] == 1.0
    assert team["total_discomfort"] == 100
    assert team["max_discomfort"] == 100

    player = team["roster"]["Tank"][0]
    assert player["assigned_rating"] == 2500
    assert player["role_discomfort"] == 100
    assert player["is_captain"] is True
    assert player["role_preferences"] == ["Tank", "Damage"]
    assert player["all_ratings"] == {"Tank": 2500, "Damage": 2400}
    assert player["is_flex"] is False

    assert normalized["statistics"]["average_mmr"] == 2422.47
    assert normalized["statistics"]["mmr_std_dev"] == 6.91
    assert normalized["statistics"]["players_per_team"] == 1
    assert normalized["benched_players"][0]["sub_role"] == "main_heal"

    # The upgraded payload must satisfy the save-side schema too.
    InternalBalancerTeamsPayload.model_validate(normalized)


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


def test_internal_balance_payload_accepts_all_discomforts_snapshot() -> None:
    """Regression: the save round-trip must accept the per-role discomfort
    snapshot the editor attaches to every player for drag-and-drop recompute.

    ``PlayerData`` (the response model) carries ``all_discomforts`` and the
    normalizer re-emits it, so ``InternalBalancerPlayer`` (the save model) must
    accept it too — otherwise PUT /balance 422s on a normal edited payload.
    """

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
                                "all_discomforts": {"Tank": 5000, "Damage": 0, "Support": 100},
                                "is_flex": False,
                            }
                        ]
                    },
                }
            ]
        }
    )

    player = payload.teams[0].roster["Damage"][0]
    assert player.all_discomforts == {"Tank": 5000, "Damage": 0, "Support": 100}


def test_normalize_then_validate_round_trips_all_discomforts() -> None:
    """The full save path (normalize_balance_response_payload -> internal
    schema) must not 422 when the editor sends ``all_discomforts``.
    """

    from src.services.balancer.config.public_contract import (
        normalize_balance_response_payload,
    )

    result_json = {
        "teams": [
            {
                "id": 1,
                "name": "Team 1",
                "average_mmr": 2500.0,
                "rating_variance": 0.0,
                "total_discomfort": 100,
                "max_discomfort": 100,
                "roster": {
                    "Tank": [
                        {
                            "uuid": "player-1",
                            "name": "Player#1234",
                            "assigned_rating": 2500,
                            "role_discomfort": 0,
                            "is_captain": True,
                            "role_preferences": ["Tank"],
                            "all_ratings": {"Tank": 2500},
                            "all_discomforts": {"Tank": 0, "Damage": 100, "Support": 200},
                            "is_flex": False,
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

    normalized = normalize_balance_response_payload(result_json)
    payload = InternalBalancerTeamsPayload.model_validate(normalized)

    player = payload.teams[0].roster["Tank"][0]
    assert player.all_discomforts == {"Tank": 0, "Damage": 100, "Support": 200}


def test_rank_comfort_tilt_field_exposed() -> None:
    from src.services.balancer.config.provider import get_balancer_config_payload

    payload = get_balancer_config_payload()
    fields_by_key = {field["key"]: field for field in payload["fields"]}

    assert payload["defaults"]["rank_comfort_tilt"] == 0.5
    field = fields_by_key["rank_comfort_tilt"]
    assert field["type"] == "slider"
    assert field["group"] == "Quality weights"
    assert field["limits"] == {"min": 0.0, "max": 1.0}


class TournamentConfigPersistenceTests(IsolatedAsyncioTestCase):
    async def test_upsert_tournament_config_creates_normalized_row(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        # An AsyncSession delegates state to its sync_session; that is where
        # `emit` stages, and an AsyncMock would answer `.info` with a mock.
        session.sync_session = SimpleNamespace(info={})
        user = SimpleNamespace(id=42)

        with patch.object(balancer_admin_service, "get_tournament_config", AsyncMock(return_value=None)):
            result = await balancer_admin_service.upsert_tournament_config(
                session,
                77,
                9,
                {"population_size": 150, "use_captains": None, "workspace_id": 9},
                user,
            )

        self.assertEqual(result.tournament_id, 77)
        self.assertEqual(result.workspace_id, 9)
        self.assertEqual(result.config_json, {"population_size": 150})
        self.assertEqual(result.updated_by, 42)
        session.add.assert_called_once_with(result)
        session.commit.assert_awaited_once()
        # The admin tool learns of the edit from the same transaction that
        # writes it, not from a publish scheduled after the fact.
        scope, event, actor = session.sync_session.info["realtime_staged"].domain[0]
        self.assertEqual("tournament:77:balancer", scope.domain_topic(event.domain))
        self.assertEqual("balancer.config_changed", event.event_type)
        self.assertEqual(42, actor)
        # The admin tool learns of the edit from the same transaction that
        # writes it, not from a publish scheduled after the fact.
        scope, event, actor = session.sync_session.info["realtime_staged"].domain[0]
        self.assertEqual("tournament:77:balancer", scope.domain_topic(event.domain))
        self.assertEqual("balancer.config_changed", event.event_type)
        self.assertEqual(42, actor)

    async def test_upsert_tournament_config_updates_existing_row(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.sync_session = SimpleNamespace(info={})
        user = SimpleNamespace(id=43)
        existing = SimpleNamespace(
            tournament_id=77,
            workspace_id=9,
            config_json={"population_size": 150},
            updated_by=42,
            updated_at=None,
        )

        with patch.object(balancer_admin_service, "get_tournament_config", AsyncMock(return_value=existing)):
            result = await balancer_admin_service.upsert_tournament_config(
                session,
                77,
                9,
                {"max_result_variants": 6},
                user,
            )

        self.assertIs(result, existing)
        self.assertEqual(existing.config_json, {"max_result_variants": 6})
        self.assertEqual(existing.updated_by, 43)
        session.add.assert_not_called()
        session.commit.assert_awaited_once()

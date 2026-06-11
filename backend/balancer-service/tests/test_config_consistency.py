"""Single-source-of-truth guard tests for balancer algorithm configuration.

These assertions lock the consistency invariants between the canonical
``AlgorithmConfig`` defaults, the preset deltas, the editable-field catalog,
the limit table, and the public ``/config`` payload. They are deliberately
offline/deterministic (no DB/Redis/network) and exist to catch future drift
between these parallel sources of truth, not to fail on the current code.
"""

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
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.services.balancer.config.defaults import AlgorithmConfig  # noqa: E402
from src.services.balancer.config.presets import ConfigPresets  # noqa: E402
from src.services.balancer.config.provider import (  # noqa: E402
    CONFIG_FIELD_DEFINITIONS,
    CONFIG_LIMITS,
    EDITABLE_CONFIG_FIELD_KEYS,
    get_balancer_config_payload,
)


def _algorithm_field_names() -> set[str]:
    return set(AlgorithmConfig().model_dump().keys())


def test_default_preset_matches_algorithm_config_defaults() -> None:
    """Every ``ConfigPresets.DEFAULT`` entry that is also an ``AlgorithmConfig``
    field must equal that field's default — the preset and the settings class
    must not drift apart."""
    defaults = AlgorithmConfig().model_dump()

    mismatches = {
        key: (preset_value, defaults[key])
        for key, preset_value in ConfigPresets.DEFAULT.items()
        if key in defaults and preset_value != defaults[key]
    }

    assert mismatches == {}, f"DEFAULT preset drifted from AlgorithmConfig defaults: {mismatches}"


def test_default_preset_keys_are_all_algorithm_config_fields() -> None:
    """``ConfigPresets.DEFAULT`` must not reference keys that are not real
    ``AlgorithmConfig`` fields."""
    field_names = _algorithm_field_names()

    unknown_default_keys = set(ConfigPresets.DEFAULT) - field_names

    assert unknown_default_keys == set(), f"DEFAULT preset has non-field keys: {sorted(unknown_default_keys)}"


def test_config_limits_keys_are_valid_algorithm_config_fields() -> None:
    """Every key in ``CONFIG_LIMITS`` must be a valid ``AlgorithmConfig``
    field name."""
    field_names = _algorithm_field_names()

    invalid_limit_keys = set(CONFIG_LIMITS) - field_names

    assert invalid_limit_keys == set(), f"CONFIG_LIMITS references unknown fields: {sorted(invalid_limit_keys)}"


def test_field_definitions_keys_are_editable() -> None:
    """Every ``CONFIG_FIELD_DEFINITIONS`` entry's ``key`` must be an editable
    config field key."""
    definition_keys = {definition["key"] for definition in CONFIG_FIELD_DEFINITIONS}

    non_editable = definition_keys - EDITABLE_CONFIG_FIELD_KEYS

    assert non_editable == set(), f"Field definitions reference non-editable keys: {sorted(non_editable)}"


def test_config_payload_exposes_expected_top_level_keys() -> None:
    """``get_balancer_config_payload`` returns the stable public envelope."""
    payload = get_balancer_config_payload()

    assert isinstance(payload, dict)
    assert set(payload.keys()) == {"defaults", "limits", "presets", "fields"}

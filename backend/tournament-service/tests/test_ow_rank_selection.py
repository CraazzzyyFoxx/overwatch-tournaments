"""Unit tests for main-account-preferred OW rank selection."""

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

ow_rank_selection = importlib.import_module("src.services.registration.ow_rank_selection")
select_main_account_ow_ranks = ow_rank_selection.select_main_account_ow_ranks


def test_takes_max_across_non_smurf_accounts() -> None:
    accounts = {
        "Main#1111": {"tank": 2000, "dps": 2500},
        "Alt#2222": {"tank": 3000, "support": 1800},
    }
    # No smurfs declared -> both accounts are "main"; per role take the max.
    assert select_main_account_ow_ranks(accounts, None) == {
        "tank": 3000,
        "dps": 2500,
        "support": 1800,
    }


def test_excludes_smurf_even_when_higher() -> None:
    accounts = {
        "Main#1111": {"tank": 2000},
        "Smurf#9999": {"tank": 4000},
    }
    # The smurf has a higher rank but must be ignored while a main account has data.
    assert select_main_account_ow_ranks(accounts, ["Smurf#9999"]) == {"tank": 2000}


def test_falls_back_to_smurf_when_no_main_rank_for_role() -> None:
    accounts = {
        "Main#1111": {"tank": 2000},
        "Smurf#9999": {"tank": 4000, "support": 3200},
    }
    # tank -> main (2000); support -> only the smurf has data, so fall back to it.
    assert select_main_account_ow_ranks(accounts, ["Smurf#9999"]) == {
        "tank": 2000,
        "support": 3200,
    }


def test_smurf_matching_is_case_and_space_insensitive() -> None:
    accounts = {
        "Main#1111": {"dps": 2200},
        "SmUrF #9999": {"dps": 3900},
    }
    # Declared smurf differs in case/spacing but normalises to the same key -> excluded.
    assert select_main_account_ow_ranks(accounts, ["smurf#9999"]) == {"dps": 2200}


def test_max_across_multiple_smurfs_on_fallback() -> None:
    accounts = {
        "SmurfA#1": {"support": 2800},
        "SmurfB#2": {"support": 3100},
    }
    # Every account is a smurf -> fall back to the max smurf rank per role.
    assert select_main_account_ow_ranks(accounts, ["SmurfA#1", "SmurfB#2"]) == {"support": 3100}


def test_empty_accounts_returns_empty() -> None:
    assert select_main_account_ow_ranks({}, ["Smurf#9999"]) == {}


def test_per_role_independence() -> None:
    accounts = {
        "Main#1111": {"tank": 1500, "dps": 2600},
        "Alt#2222": {"tank": 2700, "dps": 2100},
    }
    # Different accounts win different roles.
    assert select_main_account_ow_ranks(accounts, None) == {"tank": 2700, "dps": 2600}

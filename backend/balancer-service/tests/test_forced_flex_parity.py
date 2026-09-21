"""The every-role effective-rank rule, pinned against the shared fixtures.

This file used to check PARITY: the rule lived in two Python implementations
(``rules.map_registration`` for the draft, the admin list's own mapper for the
balancer payload) and a fixture file kept them honest. There is one
implementation now -- ``shared.services.roster.RosterEngine`` -- and both the
draft and the balancer payload read it, so there is nothing left to compare
against. The fixtures survive as the specification they always were, and what is
asserted below is the engine's behaviour on them:

* ``eff_rank`` is the player's best playable rank -- the maximum over the roles
  that carry one, ``is_active`` deliberately ignored (a Google-Sheets row whose
  rank did not parse arrives inactive and would otherwise lose a playable role).
* Every role carries a rating, because balancer eligibility for a role IS having
  one -- so all three are playable.
* A rank the registrant STATED for a role survives; only the unrated roles
  inherit the maximum. The draft shows that per-role number to the captain
  choosing a role.

``eff_ow_rank`` has no counterpart here; without a workspace there is no
Overwatch layer to inherit through. Only the TS side asserts it.

TS half: frontend/src/app/balancer/components/forced-flex-parity.test.ts
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = REPO_BACKEND_ROOT.parent
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
FIXTURES = REPO_ROOT / "docs" / "superpowers" / "fixtures" / "forced-flex-eff-rank.json"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from shared.core.enums import HERO_TYPE_CLASSES  # noqa: E402
from shared.division_grid import DEFAULT_GRID  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.domain.roster import PlayerRoster  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistration,
    BalancerRegistrationRole,
)
from shared.services.roster import roster_engine  # noqa: E402

CASES: list[dict[str, Any]] = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
ALL_ROLE_VALUES = {role.slot_code for role in HERO_TYPE_CLASSES}


@pytest.fixture(params=["all_roles", "forced"])
def mode(request) -> str:
    """Both every-role modes share this rule; only ``forced`` also forces primary."""
    return request.param


def _flex_form(mode: str) -> SimpleNamespace:
    """The one thing the engine reads a registration form for: the flex mode."""
    schema = FormSchema(
        sections=[FormSection(key="roles", fields=[FormField(key="roles", kind="builtin", params={"flex_mode": mode})])]
    )
    return SimpleNamespace(current_version=SimpleNamespace(schema_json=schema.model_dump(mode="json")))


def _resolve(case: dict[str, Any], mode: str) -> PlayerRoster:
    registration = BalancerRegistration(id=1, tournament_id=1, battle_tag="Reg#1")
    registration.roles = [
        BalancerRegistrationRole(
            role=spec["role"],
            priority=index,
            is_primary=True,
            is_active=spec["is_active"],
            rank_value=spec["rank_value"],
        )
        for index, spec in enumerate(case["roles"])
    ]
    rosters = asyncio.run(
        roster_engine.resolve(
            None,  # type: ignore[arg-type]
            [registration],
            workspace_id=None,
            tournament_id=1,
            form=_flex_form(mode),
            grid=DEFAULT_GRID,
        )
    )
    return rosters[1]


def test_fixtures_are_loaded() -> None:
    assert CASES, f"no cases in {FIXTURES}"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_best_rank_matches_the_shared_expectation(case: dict[str, Any], mode: str) -> None:
    assert _resolve(case, mode).best_rank == case["expected"]["eff_rank"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_every_role_carries_a_rating_and_stated_ranks_survive(case: dict[str, Any], mode: str) -> None:
    expected_rank = case["expected"]["eff_rank"]
    stated = {spec["role"]: spec["rank_value"] for spec in case["roles"] if spec["rank_value"] is not None}
    expected = {} if expected_rank is None else {role: stated.get(role, expected_rank) for role in ALL_ROLE_VALUES}

    assert _resolve(case, mode).role_ranks == expected


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_all_three_roles_are_playable_whenever_any_rank_exists(case: dict[str, Any], mode: str) -> None:
    resolved = _resolve(case, mode)

    if case["expected"]["eff_rank"] is None:
        # Nothing to spread: the registration is not draftable at all, which the
        # pool reports instead of the draft inventing a rank.
        assert resolved.playable_roles == frozenset()
        assert resolved.is_draftable is False
        return
    assert resolved.playable_roles == frozenset(HERO_TYPE_CLASSES)
    lead = resolved.primary
    assert lead is not None
    assert {lead.role, *resolved.secondary_roles} == set(HERO_TYPE_CLASSES)

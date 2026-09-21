"""Subscription requirement: the workspace upsert schema and the form read projection.

Pure schema/serializer coverage: the round-trip from an API payload to the stored
blob and back out through the form read model.

The split is the point. ``require_subscription`` is the tournament's toggle and stays
on ``RegistrationFormUpsert``; the rule itself is the workspace's and is written
through ``WorkspaceSubscriptionRequirementUpsert``, which owns the save-time
validation the form schema used to carry. ``RegistrationFormRead`` still exposes the
rule -- server-resolved and read-only -- because the public check-in dialog renders it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.enums import SubscriptionEnforcementStage  # noqa: E402
from shared.domain.forms import default_schema  # noqa: E402
from shared.services.subscriptions import Outcome, parse_requirement  # noqa: E402
from src.schemas.registration import WorkspaceSubscriptionRequirementUpsert  # noqa: E402
from src.schemas.registration_form import RegistrationFormRead, RegistrationFormUpsert  # noqa: E402
from src.services.registration.serializers import serialize_registration_form  # noqa: E402

DEFAULT_SCHEMA = default_schema()

ANY_BOOSTY_OR_TWITCH = {
    "mode": "any",
    "requirements": [
        {"provider": "boosty", "min_tier_rank": 2},
        {"provider": "twitch", "min_tier_rank": 1},
    ],
}


class _FormRow:
    """Stand-in for models.BalancerRegistrationForm (serializer reads attributes)."""

    def __init__(self, **overrides):
        self.id = 1
        self.tournament_id = 10
        self.workspace_id = 7
        self.is_open = True
        self.auto_approve = False
        self.require_open_profile = False
        self.open_profile_scope = "main"
        self.show_ranks = False
        self.hide_registrations = False
        self.max_participants = None
        self.current_version = SimpleNamespace(id=31, number=1, schema_json=DEFAULT_SCHEMA.model_dump(mode="json"))
        self.max_substitutes = 0
        self.require_subscription = False
        self.subscription_stage = "check_in"
        for key, value in overrides.items():
            setattr(self, key, value)


def _upsert(**overrides) -> RegistrationFormUpsert:
    """The upsert is full-replace, so ``form_schema`` is always sent."""
    return RegistrationFormUpsert(form_schema=DEFAULT_SCHEMA, **overrides)


class TestFormUpsertSchema:
    def test_the_toggle_defaults_off(self):
        """A tournament that never configures this must not start enforcing."""
        assert _upsert().require_subscription is False

    def test_the_stage_defaults_to_check_in(self):
        """The looser stage. A client that never sends the field -- or an older one that
        cannot -- must not arm a sign-up wall by omission."""
        assert _upsert().subscription_stage == SubscriptionEnforcementStage.check_in

    def test_max_substitutes_defaults_to_zero(self):
        assert _upsert().max_substitutes == 0

    def test_max_substitutes_rejects_a_negative(self):
        try:
            _upsert(max_substitutes=-1)
        except ValueError:
            pass
        else:
            raise AssertionError("a negative bench must not validate")

    def test_the_stage_rejects_a_value_outside_the_enum(self):
        """Better a 422 on save than a stored typo that silently reads as check-in."""
        try:
            _upsert(subscription_stage="whenever")
        except ValueError:
            pass
        else:
            raise AssertionError("an unknown stage must not validate")

    def test_the_rule_is_not_writable_through_the_form(self):
        """The rule moved to the workspace; the form must not carry a second copy.

        Asserted through `model_validate` rather than `hasattr` on a default instance:
        the field being undeclared is only half the contract. The other half is what
        happens to a stale client that still POSTs it -- the key is DROPPED and the save
        succeeds (200, not 422). That tolerance is deliberate (see the model), so it is
        pinned here rather than left to be discovered.
        """
        assert not hasattr(_upsert(), "subscription_requirement_json")

        body = RegistrationFormUpsert.model_validate(
            {
                "is_open": True,
                "require_subscription": True,
                "form_schema": DEFAULT_SCHEMA.model_dump(mode="json"),
                "subscription_requirement_json": {
                    "mode": "all",
                    "requirements": [{"provider": "boosty", "min_tier_rank": 2}],
                },
            }
        )
        assert "subscription_requirement_json" not in body.model_dump()
        assert body.require_subscription is True


class TestWorkspaceRequirementUpsertSchema:
    def test_defaults_to_nothing_enforced(self):
        assert WorkspaceSubscriptionRequirementUpsert().requirement == {}

    def test_accepts_a_requirement_blob(self):
        body = WorkspaceSubscriptionRequirementUpsert(requirement=ANY_BOOSTY_OR_TWITCH)
        assert body.requirement["mode"] == "any"

    def test_rejects_an_unknown_mode_at_the_api_boundary(self):
        """Better a 422 on save than a surprise at check-in time."""
        # Pinned to the MESSAGE, not the bare word "mode": Pydantic echoes the
        # offending payload into ValidationError.__str__ as
        # `input_value={'mode': 'most', ...}`, and `match` is an re.search over that
        # string -- so `match="mode"` is satisfied by ANY failure on this input and
        # would keep passing if the mode check were removed entirely.
        with pytest.raises(ValueError, match="Unsupported subscription requirement mode"):
            WorkspaceSubscriptionRequirementUpsert(requirement={"mode": "most", "requirements": []})

    def test_rejects_a_requirement_without_a_provider(self):
        with pytest.raises(ValueError):
            WorkspaceSubscriptionRequirementUpsert(requirement={"requirements": [{"min_tier_rank": 2}]})

    def test_allows_an_empty_requirement(self):
        """Clearing the rule is legitimate -- and it disarms every tournament using it."""
        body = WorkspaceSubscriptionRequirementUpsert(requirement={})
        assert parse_requirement(body.requirement).requirements == ()

    def test_clamps_min_tier_rank_below_one(self):
        body = WorkspaceSubscriptionRequirementUpsert(
            requirement={"requirements": [{"provider": "boosty", "min_tier_rank": 0}]}
        )
        requirement = parse_requirement(body.requirement)
        assert requirement.requirements[0].min_tier_rank == 1

    def test_deduplicates_a_provider_keeping_the_strictest_threshold(self):
        body = WorkspaceSubscriptionRequirementUpsert(
            requirement={
                "requirements": [
                    {"provider": "boosty", "min_tier_rank": 1},
                    {"provider": "boosty", "min_tier_rank": 3},
                ]
            }
        )
        requirement = parse_requirement(body.requirement)
        assert [r.min_tier_rank for r in requirement.requirements] == [3]


class TestReadSchema:
    def test_defaults_are_off(self):
        form = RegistrationFormRead(
            id=1,
            tournament_id=1,
            workspace_id=1,
            is_open=False,
            form_schema=DEFAULT_SCHEMA,
            version_id=1,
            version_number=1,
        )
        assert form.require_subscription is False
        assert form.subscription_requirement_json == {}
        assert form.max_substitutes == 0
        # Organizer-only, so the public read is free to leave it unanswered.
        assert form.stale_registrations is None


class TestSerializer:
    def test_carries_the_toggle_and_the_workspace_rule(self):
        read = serialize_registration_form(
            _FormRow(require_subscription=True),
            is_open=True,
            subscription_requirement=ANY_BOOSTY_OR_TWITCH,
        )
        assert read.require_subscription is True
        assert read.subscription_requirement_json == ANY_BOOSTY_OR_TWITCH

    def test_a_workspace_without_a_rule_serializes_as_an_empty_object(self):
        """The resolved projection must never be null -- the dialog reads it directly."""
        read = serialize_registration_form(
            _FormRow(require_subscription=True), is_open=True, subscription_requirement=None
        )
        assert read.subscription_requirement_json == {}

    def test_untouched_form_serializes_as_disabled(self):
        read = serialize_registration_form(_FormRow(), is_open=False)
        assert read.require_subscription is False
        assert read.subscription_requirement_json == {}

    def test_carries_max_substitutes(self):
        read = serialize_registration_form(_FormRow(max_substitutes=2), is_open=True)
        assert read.max_substitutes == 2

    def test_carries_the_version_the_schema_came_from(self):
        """The wizard posts this id back on submit; a read that lost it would make
        every submission look stale."""
        read = serialize_registration_form(_FormRow(), is_open=True, stale_registrations=4)
        assert (read.version_id, read.version_number) == (31, 1)
        assert read.form_schema.canonical_json() == DEFAULT_SCHEMA.canonical_json()
        assert read.stale_registrations == 4


class TestRoundTrip:
    def test_upsert_blob_survives_into_a_usable_requirement(self):
        """The whole point: what the organizer saved is what the gate evaluates."""
        body = WorkspaceSubscriptionRequirementUpsert(requirement=ANY_BOOSTY_OR_TWITCH)
        read = serialize_registration_form(
            _FormRow(require_subscription=True),
            is_open=True,
            subscription_requirement=body.requirement,
        )
        requirement = parse_requirement(read.subscription_requirement_json)
        assert requirement.mode == "any"
        assert {r.provider: r.min_tier_rank for r in requirement.requirements} == {
            "boosty": 2,
            "twitch": 1,
        }

    def test_single_provider_requirement_is_mode_agnostic(self):
        one = {"requirements": [{"provider": "boosty", "min_tier_rank": 2}]}
        from shared.services.subscriptions import SubscriptionVerdict

        def _v(state, tier):
            from datetime import UTC, datetime

            return SubscriptionVerdict(
                state=state,
                tier_rank=tier,
                tier_label=None,
                source="test",
                checked_at=datetime.now(UTC),
                expires_at=None,
            )

        from shared.services.subscriptions import evaluate_requirement

        for mode in ("any", "all"):
            requirement = parse_requirement({**one, "mode": mode})
            assert evaluate_requirement(requirement, {"boosty": _v("active", 2)}) is Outcome.SATISFIED

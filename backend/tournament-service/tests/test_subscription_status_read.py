"""The patron's own subscription standing, including which mechanism can fix it.

``code_accepted`` exists because ``reason`` cannot express it: under the permissive
method an unlinked patron reads ``no_linked_discord_account``, yet a code would
satisfy them too — so a UI inferring from ``reason`` alone would either hide a
working input or offer one the server is about to reject with 400.

``blocks_registration`` answers a different question — whether SIGN-UP is refused
right now — and must agree with the gate that enforces it: the same deferral of
anything a challenge code could still change, AND the same opt-in on the form's
``subscription_stage``. Promising a block on a check-in-staged tournament would
disable a submit button the server would happily accept.

Runs under stdlib unittest -- there is no pytest-asyncio here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from datetime import UTC, datetime  # noqa: E402

from shared.domain.flow.config import RegistrationNodeConfig  # noqa: E402
from shared.services.subscriptions import (  # noqa: E402
    Outcome,
    SubscriptionState,
    SubscriptionVerdict,
)
from src.services.registration.subscription_status import subscription_status_for_user  # noqa: E402

# The resolver's fail-open contract, defined once -- see that module's docstring.
from tests._subscription_fakes import resolver_rule as _rule  # noqa: E402

WS = 7
USER = 42


class _Form:
    """Only the workspace: the toggles are the registration node's and the rule is the workspace's."""

    workspace_id = WS


#: Staged at ``registration`` so the ``blocks_registration`` cases below exercise the composition rather than the
#: opt-in; the opt-in itself is pinned in ``TestStageGatesBlocksRegistration``.
_NODE = RegistrationNodeConfig(require_subscription=True, subscription_stage="registration")


def _requirement(*providers: str, mode: str = "any") -> dict:
    return {"mode": mode, "requirements": [{"provider": p, "min_tier_rank": 1} for p in providers]}


def _verdict(state: str, *, reason: str | None = None) -> SubscriptionVerdict:
    return SubscriptionVerdict(
        state=state,
        tier_rank=None,
        tier_label=None,
        source="test",
        checked_at=datetime.now(UTC),
        expires_at=None,
        evidence={"reason": reason} if reason else {},
    )


class _FakeResolver:
    def __init__(
        self,
        verdicts: dict[str, SubscriptionVerdict],
        code_providers: set[str],
        requirement: dict | None = None,
    ) -> None:
        self._verdicts = verdicts
        self._code_providers = code_providers
        self._requirement = requirement
        self.code_queries: list[tuple[int, tuple[str, ...]]] = []

    async def load_requirement(self, *, workspace_id):
        return _rule(self._requirement)

    async def evaluate(self, *, workspace_id, auth_user_ids, requirement, force_refresh=False):
        outcome = (
            Outcome.SATISFIED
            if any(v.state == SubscriptionState.ACTIVE for v in self._verdicts.values())
            else Outcome.REFUSED
        )
        return dict.fromkeys(auth_user_ids, (outcome, self._verdicts))

    async def accepted_code_providers(self, *, workspace_id, providers):
        self.code_queries.append((workspace_id, tuple(providers)))
        return self._code_providers


async def _status(verdicts, code_providers, *, requirement=None, stage="registration"):
    resolver = _FakeResolver(verdicts, code_providers, requirement or _requirement("boosty"))
    node = RegistrationNodeConfig(require_subscription=True, subscription_stage=stage)
    read = await subscription_status_for_user(form=_Form(), node_config=node, auth_user_id=USER, resolver=resolver)
    return read, resolver


class TestNotRequired(IsolatedAsyncioTestCase):
    async def test_no_form_reports_not_required(self):
        read = await subscription_status_for_user(
            form=None, node_config=_NODE, auth_user_id=USER, resolver=_FakeResolver({}, set())
        )
        assert read.required is False
        assert read.verdicts == {}

    async def test_an_empty_requirement_reports_not_required(self):
        read, resolver = await _status({}, set(), requirement={"mode": "any", "requirements": []})
        assert read.required is False
        assert resolver.code_queries == [], "nothing is required, so nothing is queried"

    async def test_malformed_requirement_degrades_instead_of_500ing(self):
        read = await subscription_status_for_user(
            form=_Form(),
            node_config=_NODE,
            auth_user_id=USER,
            resolver=_FakeResolver({}, set(), {"mode": "nonsense", "requirements": "not-a-list"}),
        )
        assert read.required is False


class TestCodeAccepted(IsolatedAsyncioTestCase):
    async def test_flag_is_true_for_a_provider_that_takes_codes(self):
        read, _ = await _status({"boosty": _verdict(SubscriptionState.INACTIVE, reason="no_mapped_role")}, {"boosty"})
        assert read.verdicts["boosty"].code_accepted is True

    async def test_flag_is_false_under_live_only(self):
        """The input must not be offered when the server would reject the paste."""
        read, _ = await _status({"boosty": _verdict(SubscriptionState.INACTIVE, reason="no_mapped_role")}, set())
        assert read.verdicts["boosty"].code_accepted is False

    async def test_flag_is_independent_of_the_reason(self):
        """Precisely the case `reason` cannot express: an unlinked patron under the
        permissive method, where a code would work."""
        read, _ = await _status(
            {"boosty": _verdict(SubscriptionState.UNKNOWN, reason="no_linked_discord_account")},
            {"boosty"},
        )
        assert read.verdicts["boosty"].reason == "no_linked_discord_account"
        assert read.verdicts["boosty"].code_accepted is True

    async def test_flag_is_per_provider(self):
        read, _ = await _status(
            {
                "boosty": _verdict(SubscriptionState.INACTIVE),
                "twitch": _verdict(SubscriptionState.INACTIVE),
            },
            {"boosty"},
            requirement=_requirement("boosty", "twitch"),
        )
        assert read.verdicts["boosty"].code_accepted is True
        assert read.verdicts["twitch"].code_accepted is False

    async def test_only_the_required_providers_are_queried(self):
        _, resolver = await _status({"boosty": _verdict(SubscriptionState.INACTIVE)}, {"boosty"})
        assert resolver.code_queries == [(WS, ("boosty",))]


class TestVerdictNarrowing(IsolatedAsyncioTestCase):
    async def test_never_leaks_evidence_beyond_the_reason(self):
        """Evidence carries guild and role ids; only `reason` may reach the patron."""
        verdict = SubscriptionVerdict(
            state=SubscriptionState.INACTIVE,
            tier_rank=None,
            tier_label=None,
            source="test",
            checked_at=datetime.now(UTC),
            expires_at=None,
            evidence={"reason": "no_mapped_role", "guild_id": "1234567890", "held_role_ids": ["999"]},
        )
        read, _ = await _status({"boosty": verdict}, {"boosty"})
        dumped = str(read.model_dump())
        assert "1234567890" not in dumped
        assert "999" not in dumped
        assert read.verdicts["boosty"].reason == "no_mapped_role"

    async def test_carries_the_composed_outcome_and_no_server_worded_rule(self):
        """The rule line is worded by the client in the reader's locale, from the
        form's requirement; a server sentence here shipped "уровень"/"или" to
        English users."""
        read, _ = await _status({"boosty": _verdict(SubscriptionState.ACTIVE)}, set())
        assert read.required is True
        assert read.outcome == Outcome.SATISFIED.value
        assert "rule" not in read.model_dump()


class TestBlocksRegistration(IsolatedAsyncioTestCase):
    """Mirrors ``assert_subscription_allows_registration``; the form disables submit on it."""

    async def test_false_when_satisfied(self):
        read, _ = await _status({"boosty": _verdict(SubscriptionState.ACTIVE)}, set())
        assert read.blocks_registration is False

    async def test_true_on_an_automatic_refusal(self):
        read, _ = await _status({"boosty": _verdict(SubscriptionState.INACTIVE)}, set())
        assert read.blocks_registration is True

    async def test_false_when_a_code_could_still_fix_it(self):
        """The phrase field lives at check-in, so sign-up must not refuse on it."""
        read, _ = await _status({"boosty": _verdict(SubscriptionState.INACTIVE)}, {"boosty"})
        assert read.blocks_registration is False

    async def test_false_on_an_undetermined_verdict(self):
        read, _ = await _status({"boosty": _verdict(SubscriptionState.UNKNOWN, reason="strategy_error")}, set())
        assert read.blocks_registration is False

    async def test_narrower_than_the_composed_outcome(self):
        """The two fields disagree by design: `outcome` is the check-in answer."""
        read, _ = await _status({"boosty": _verdict(SubscriptionState.INACTIVE)}, {"boosty"})
        assert read.outcome == Outcome.REFUSED.value
        assert read.blocks_registration is False

    async def test_all_mode_blocks_when_one_provider_needs_no_code(self):
        read, _ = await _status(
            {
                "boosty": _verdict(SubscriptionState.INACTIVE),
                "twitch": _verdict(SubscriptionState.INACTIVE),
            },
            {"boosty"},
            requirement=_requirement("boosty", "twitch", mode="all"),
        )
        assert read.blocks_registration is True

    async def test_not_required_never_blocks(self):
        read = await subscription_status_for_user(
            form=None, node_config=_NODE, auth_user_id=USER, resolver=_FakeResolver({}, set())
        )
        assert read.blocks_registration is False


class TestStageGatesBlocksRegistration(IsolatedAsyncioTestCase):
    """The field must follow the form's choice, not just the verdicts.

    Each case pairs a stage against the SAME refusal that blocks under
    ``registration`` (``test_true_on_an_automatic_refusal`` above), so a regression
    that ignores the stage cannot pass by accident.
    """

    async def test_check_in_stage_never_blocks_sign_up(self):
        read, _ = await _status({"boosty": _verdict(SubscriptionState.INACTIVE)}, set(), stage="check_in")
        assert read.blocks_registration is False
        # Still refused overall -- that is the check-in answer, and the form shows it.
        assert read.outcome == Outcome.REFUSED.value

    async def test_a_node_left_at_the_default_stage_never_blocks_sign_up(self):
        resolver = _FakeResolver({"boosty": _verdict(SubscriptionState.INACTIVE)}, set(), _requirement("boosty"))
        read = await subscription_status_for_user(
            form=_Form(),
            node_config=RegistrationNodeConfig(require_subscription=True),
            auth_user_id=USER,
            resolver=resolver,
        )
        assert read.blocks_registration is False

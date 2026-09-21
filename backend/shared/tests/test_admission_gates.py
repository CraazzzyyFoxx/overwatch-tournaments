"""The gate is a projection, and these tests pin only what the projection owes.

Nothing here re-tests whether a requirement blocks -- ``evaluate`` owns that and
``test_admission_evaluate`` pins it. What is checkable only here:

- the gate raises off ``blockers`` and nothing else, so a ``blocked`` requirement
  whose gate is still ahead, and every ``blocked`` requirement after check-in
  (D2), pass through it silently;
- every blocker becomes its own ``ApiExc``, in order. A player refused for two
  reasons who is told one of them fixes it, retries, and is refused again;
- the ``code`` is the reason's machine code. That code is the entire i18n
  contract with the client (D13): the client never ran the composition, so a
  wrong or empty code leaves it printing Russian at an English user;
- ``describe_requirement`` still names the ACTUAL rule, including the mode and
  the tier threshold. It moved here from ``tournament-service`` in Ф2 and a move
  that quietly changed the sentence would be indistinguishable from a rewrite.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.core.errors import BaseAPIException  # noqa: E402
from shared.services.admission import (  # noqa: E402
    AdmissionConfig,
    AdmissionDecision,
    AdmissionEvaluation,
    AdmissionStage,
    ReasonActor,
    RequirementState,
    RequirementVerdict,
    reason,
)
from shared.services.admission.gates import assert_admitted, describe_requirement  # noqa: E402
from shared.services.subscriptions import parse_requirement  # noqa: E402

BOOSTY_TIER_2 = {"mode": "all", "requirements": [{"provider": "boosty", "min_tier_rank": 2}]}
BOTH = {"mode": "all", "requirements": [{"provider": "boosty"}, {"provider": "twitch"}]}
EITHER = {"mode": "any", "requirements": [{"provider": "boosty"}, {"provider": "twitch"}]}


def _blocked(key: str, *codes: str) -> RequirementVerdict:
    return RequirementVerdict(
        key=key,
        state=RequirementState.blocked,
        stage=AdmissionStage.check_in,
        reasons=tuple(reason(code) for code in codes),
    )


def _evaluation(
    *blockers: RequirementVerdict,
    overridden: tuple[RequirementVerdict, ...] = (),
    checked_in: bool = False,
) -> AdmissionEvaluation:
    """An evaluation with only the fields the gate reads filled in honestly.

    ``requirements`` mirrors both lists because the gate must never consult it:
    if it did, this would be the test that caught it.
    """
    return AdmissionEvaluation(
        decision=AdmissionDecision.not_admitted if blockers else AdmissionDecision.admitted,
        requirements=blockers + overridden,
        blockers=blockers,
        overridden=overridden,
        checked_in=checked_in,
        ready=True,
    )


def _detail(exc: BaseAPIException) -> list[dict[str, str]]:
    """``ApiHTTPException`` dumps its ``ApiExc`` list in the constructor."""
    assert isinstance(exc.detail, list)
    return exc.detail


class TestNothingToRefuse(TestCase):
    def test_no_blockers_does_not_raise(self):
        assert_admitted(_evaluation(), stage=AdmissionStage.check_in)

    def test_overridden_blockers_do_not_raise(self):
        """D2: check-in spent the requirement, so the gate must stay silent.

        The blocked verdict is still THERE -- it rides in ``overridden`` and the
        badge shows it -- and this is exactly the case the old arrangement broke:
        the admin path had no gate, but the display re-derived the refusal
        forever.
        """
        assert_admitted(
            _evaluation(overridden=(_blocked("open_profile", "profile_private"),), checked_in=True),
            stage=AdmissionStage.check_in,
        )


class TestOneBlocker(TestCase):
    def test_raises_400(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(_evaluation(_blocked("subscription", "not_subscribed")), stage=AdmissionStage.check_in)
        assert ctx.exception.status_code == 400

    def test_code_is_the_first_reason_code(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(_evaluation(_blocked("subscription", "not_subscribed")), stage=AdmissionStage.check_in)
        assert [item["code"] for item in _detail(ctx.exception)] == ["not_subscribed"]

    def test_first_reason_wins_over_the_rest(self):
        """Ordered by the resolver; the first is the one the player acts on."""
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(
                _evaluation(_blocked("subscription", "not_subscribed", "missing_scope")),
                stage=AdmissionStage.check_in,
            )
        assert [item["code"] for item in _detail(ctx.exception)] == ["not_subscribed"]

    def test_message_is_russian_and_non_empty(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(_evaluation(_blocked("open_profile", "profile_private")), stage=AdmissionStage.check_in)
        assert _detail(ctx.exception)[0]["msg"] == "Профиль Overwatch должен быть открыт."


class TestBlockerWithoutReasons(TestCase):
    """A ``blocked`` verdict carrying no reasons is a resolver bug. The gate must
    still refuse, and must still hand the client something to translate."""

    def test_falls_back_to_the_requirement_code(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(_evaluation(_blocked("open_profile")), stage=AdmissionStage.check_in)
        assert [item["code"] for item in _detail(ctx.exception)] == ["open_profile_blocked"]

    def test_fallback_is_per_requirement_not_generic(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(_evaluation(_blocked("subscription")), stage=AdmissionStage.check_in)
        assert [item["code"] for item in _detail(ctx.exception)] == ["subscription_blocked"]


class TestEveryBlockerIsReported(TestCase):
    """The payoff of one gate over two: both refusals arrive in one response.

    Two separate gates could only ever report the first, so a player with a
    closed profile AND a lapsed subscription fixed one, retried, and was refused
    again by the second.
    """

    def test_two_blockers_produce_two_entries_in_order(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(
                _evaluation(
                    _blocked("open_profile", "profile_private"),
                    _blocked("subscription", "not_subscribed"),
                ),
                stage=AdmissionStage.check_in,
            )
        assert [item["code"] for item in _detail(ctx.exception)] == ["profile_private", "not_subscribed"]

    def test_order_follows_blockers_not_the_registry(self):
        """The control: reversed input, reversed output."""
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(
                _evaluation(
                    _blocked("subscription", "not_subscribed"),
                    _blocked("open_profile", "profile_private"),
                ),
                stage=AdmissionStage.check_in,
            )
        assert [item["code"] for item in _detail(ctx.exception)] == ["not_subscribed", "profile_private"]


class TestStageWording(TestCase):
    """The two messages the two deleted gate functions used to own.

    Keyed on the gate being refused at, never on ``verdict.stage``: a
    registration-staged subscription also blocks check-in, and a patron refused
    at check-in reading "нужна активная подписка для регистрации" would be told
    to fix a gate they are already past.
    """

    def _msg(self, stage: AdmissionStage, *, config: AdmissionConfig | None = None) -> str:
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(
                _evaluation(
                    RequirementVerdict(
                        key="subscription",
                        state=RequirementState.blocked,
                        # Armed at sign-up, therefore live at BOTH gates.
                        stage=AdmissionStage.registration,
                        reasons=(reason("not_subscribed"),),
                    )
                ),
                stage=stage,
                config=config,
            )
        return _detail(ctx.exception)[0]["msg"]

    def test_check_in_names_check_in(self):
        message = self._msg(AdmissionStage.check_in)
        assert "чек-ина" in message
        assert "регистрации" not in message

    def test_registration_names_sign_up(self):
        message = self._msg(AdmissionStage.registration)
        assert "регистрации" in message
        assert "чек-ина" not in message

    def test_config_spells_out_the_rule(self):
        config = AdmissionConfig(
            workspace_id=7,
            require_subscription=True,
            subscription_rule=parse_requirement(BOOSTY_TIER_2),
        )
        message = self._msg(AdmissionStage.check_in, config=config)
        assert "Boosty" in message
        assert "2" in message

    def test_no_config_still_refuses(self):
        """Wording degrades; the refusal does not. A gate that needed the config
        to raise would fail OPEN on a config it could not read."""
        assert "подписка" in self._msg(AdmissionStage.check_in)


class TestDescribeRequirement(TestCase):
    def test_single_provider_has_no_conjunction(self):
        text = describe_requirement(parse_requirement(BOOSTY_TIER_2))
        assert " и " not in text
        assert "или" not in text

    def test_all_mode_says_and(self):
        text = describe_requirement(parse_requirement(BOTH))
        assert " и " in text
        assert "или" not in text
        assert "Boosty" in text
        assert "Twitch" in text

    def test_any_mode_says_or(self):
        text = describe_requirement(parse_requirement(EITHER))
        assert " или " in text
        assert " и " not in text

    def test_threshold_above_one_is_named(self):
        assert "уровень 2" in describe_requirement(parse_requirement(BOOSTY_TIER_2))

    def test_threshold_of_one_is_not_spelled_out(self):
        """ "Boosty уровень 1" reads like a restriction that is not there."""
        text = describe_requirement(parse_requirement({"requirements": [{"provider": "boosty"}]}))
        assert "1" not in text
        assert text == "Boosty"

    def test_provider_outside_the_catalog_falls_back_to_its_key(self):
        """A rule naming a provider the catalog does not carry must still NAME
        it. The alternative -- an empty segment -- would refuse a patron over a
        rule the message does not state."""
        text = describe_requirement(parse_requirement({"requirements": [{"provider": "patreon"}]}))
        assert text == "patreon"

    def test_provider_outside_the_catalog_keeps_its_threshold(self):
        text = describe_requirement(parse_requirement({"requirements": [{"provider": "patreon", "min_tier_rank": 3}]}))
        assert text == "patreon уровень 3"


class TestReasonActorsSurviveTheProjection(TestCase):
    """The gate drops ``actor`` -- an HTTP 400 has no room for it -- but the code
    it keeps must still be one the taxonomy knows, or the client has no key."""

    def test_emitted_code_resolves_to_a_known_actor(self):
        with self.assertRaises(BaseAPIException) as ctx:
            assert_admitted(_evaluation(_blocked("open_profile", "profile_private")), stage=AdmissionStage.check_in)
        code = _detail(ctx.exception)[0]["code"]
        assert reason(code).actor is ReasonActor.player

"""One evaluation, two surfaces, identical answer.

The property under test is the one the five deleted client-side copies violated:
the public participants read and the admin registrations read of the SAME
registration must carry a byte-identical ``admission`` object. Before this layer
they carried five raw fields and each surface re-derived the verdict from them,
two of the five derivations deliberately disagreeing with the other three.

Also pins the two things ``AdmissionChips`` exists to get right:

- the chip fields (``profiles_open`` / ``subscription_outcome`` /
  ``subscription_verdicts``) are lifted OUT of the evaluation rather than resolved
  a second time -- a second resolution is precisely how the admin column and the
  player's own card came to disagree;
- a requirement this tournament switched off leaves those chips ``None``, not
  ``{}``. That is the value they have carried all along for a tournament that does
  not require the thing, and an empty dict would make the client render an empty
  Subscription column instead of no column.

No database: the evaluation is produced by the real ``evaluate`` over stub
signals, and the registration is a stub carrying only what the serializers read.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for root in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if root not in sys.path:
        sys.path.insert(0, root)

from src.schemas.admission import AdmissionRead  # noqa: E402
from src.services.admission import (  # noqa: E402
    AdmissionConfig,
    AdmissionDecision,
    AdmissionSignals,
    AdmissionStage,
    ProfileSignal,
    SubscriptionSignal,
)
from src.services.admission.evaluate import evaluate  # noqa: E402
from src.services.admission.reasons import reason  # noqa: E402
from src.services.admission.registry import REQUIREMENTS  # noqa: E402
from src.services.registration.read_model import AdmissionChips  # noqa: E402


def _config(*, profile: bool = False, subscription: bool = False) -> AdmissionConfig:
    return AdmissionConfig.from_form(
        SimpleNamespace(
            workspace_id=7,
            require_open_profile=profile,
            open_profile_scope="main",
            require_subscription=subscription,
            subscription_stage="check_in",
        ),
        # A rule is required for ``enforces_subscription``; its content is
        # irrelevant here because the signal is supplied already composed.
        subscription_rule=object() if subscription else None,
    )


def _signals(
    *,
    checked_in: bool = False,
    profile: ProfileSignal | None = None,
    subscription: SubscriptionSignal | None = None,
) -> AdmissionSignals:
    return AdmissionSignals(
        registration_id=1,
        status="approved",
        balancer_status="ready",
        checked_in=checked_in,
        profile=profile,
        subscription=subscription,
    )


def _evaluate(config: AdmissionConfig, signals: AdmissionSignals):
    return evaluate(config, signals, stage=AdmissionStage.check_in, requirements=REQUIREMENTS)


# --------------------------------------------------------------------------- #
# The property the five copies violated
# --------------------------------------------------------------------------- #


def test_both_surfaces_project_the_same_evaluation_identically():
    """Public read and admin read of one registration, byte-identical.

    ``AdmissionChips.of`` is the single projection both list handlers go through,
    so this is checkable without mounting either handler -- and that single funnel
    is the reason the two cannot drift.
    """
    evaluation = _evaluate(
        _config(profile=True),
        _signals(profile=ProfileSignal(is_open=False, reasons=(reason("profile_private", subject="Player#1"),))),
    )

    public = AdmissionChips.of(evaluation)
    admin = AdmissionChips.of(evaluation)

    assert public.admission.model_dump() == admin.admission.model_dump()
    assert public.admission.model_dump() == AdmissionRead.of(evaluation).model_dump()


def test_a_registration_outside_the_batch_serializes_as_unknown():
    """Never ``None`` on the wire. An absent object would make every consumer write
    a null branch, and per-consumer defaulting is how the five copies were born."""
    chips = AdmissionChips.of(None)

    assert chips.admission.model_dump() == AdmissionRead.unknown().model_dump()
    assert chips.admission.decision == "not_admitted"
    assert chips.admission.requirements == []
    assert chips.profiles_open is None
    assert chips.subscription_outcome is None
    assert chips.subscription_verdicts is None


# --------------------------------------------------------------------------- #
# Chips are lifted, not re-resolved
# --------------------------------------------------------------------------- #


def test_chips_come_out_of_the_evaluation():
    providers = {"discord": {"state": "inactive", "tier_rank": None, "tier_label": None, "reason": "no_mapped_role"}}
    evaluation = _evaluate(
        _config(profile=True, subscription=True),
        _signals(
            profile=ProfileSignal(is_open=True),
            subscription=SubscriptionSignal(outcome="refused", reasons=(), providers=providers),
        ),
    )

    chips = AdmissionChips.of(evaluation)

    assert chips.profiles_open is True
    assert chips.subscription_outcome == "refused"
    assert chips.subscription_verdicts == providers


@pytest.mark.parametrize(
    ("profile", "subscription"),
    [(False, True), (True, False), (False, False)],
)
def test_a_disabled_requirement_leaves_its_chips_none(profile: bool, subscription: bool):
    """``not_applicable`` carries an EMPTY detail, and the chips must read ``None``.

    ``{}`` where the old code sent ``None`` renders an empty column instead of no
    column -- a visible regression on every tournament that does not use the
    feature, i.e. most of them.
    """
    evaluation = _evaluate(
        _config(profile=profile, subscription=subscription),
        _signals(
            profile=ProfileSignal(is_open=True) if profile else None,
            subscription=SubscriptionSignal(outcome="satisfied") if subscription else None,
        ),
    )
    chips = AdmissionChips.of(evaluation)

    if not profile:
        assert chips.profiles_open is None
    if not subscription:
        assert chips.subscription_outcome is None
        assert chips.subscription_verdicts is None


# --------------------------------------------------------------------------- #
# The wire shape itself
# --------------------------------------------------------------------------- #


def test_disabled_requirements_still_reach_the_wire():
    """The registrant's progress steps are built by walking ``requirements``.
    Filtering the disabled ones out here would push a ``if require_x`` branch back
    into the UI, once per requirement."""
    evaluation = _evaluate(_config(profile=True), _signals(profile=ProfileSignal(is_open=True)))

    read = AdmissionRead.of(evaluation)
    states = {entry.key: entry.state for entry in read.requirements}

    assert states == {"open_profile": "satisfied", "subscription": "not_applicable"}


def test_a_forced_check_in_serializes_as_admitted_with_the_blocker_overridden():
    """The end-to-end shape of the forced-admission fix, on the wire.

    The organizer checked somebody in over a closed profile. The player is IN, the
    requirement is still visibly unmet, and ``blockers`` is empty -- which is what
    lets the client render "admitted" plus a marker instead of the permanent "not
    admitted" the old badge showed.
    """
    evaluation = _evaluate(
        _config(profile=True),
        _signals(
            checked_in=True,
            profile=ProfileSignal(is_open=False, reasons=(reason("profile_private", subject="Player#1"),)),
        ),
    )
    read = AdmissionRead.of(evaluation)

    assert evaluation.decision is AdmissionDecision.admitted
    assert read.decision == "admitted"
    assert read.blockers == []
    assert [entry.key for entry in read.overridden] == ["open_profile"]
    assert read.overridden[0].reasons[0].code == "profile_private"
    # The actor is what makes an aggregate readable: this one is the player's to fix.
    assert read.overridden[0].reasons[0].actor == "player"
    assert read.overridden[0].reasons[0].subject == "Player#1"


def test_an_undetermined_requirement_is_not_a_blocker_on_the_wire():
    """The fail-open invariant, at the serialization boundary. A stalled rank
    collection must not reach the client as a refusal."""
    evaluation = _evaluate(
        _config(profile=True),
        _signals(profile=ProfileSignal(is_open=None, reasons=(reason("collection_pending", subject="Player#1"),))),
    )
    read = AdmissionRead.of(evaluation)

    assert read.decision == "pending_check_in"
    assert read.blockers == []
    verdict = next(entry for entry in read.requirements if entry.key == "open_profile")
    assert verdict.state == "undetermined"
    assert verdict.reasons[0].actor == "system"

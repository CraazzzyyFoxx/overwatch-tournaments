"""The production requirement list, in the order the registrant sees them.

Each entry is the whole declaration: whether this tournament switched it on, the
earliest gate it blocks at, and the pure mapping from its signal to a verdict.
``resolve.py`` passes this tuple to
:func:`~src.services.admission.evaluate.evaluate`.

Order is load-bearing: ``AdmissionEvaluation.requirements`` preserves it, and the
registrant's progress steps walk that tuple.

The profile stage is a hard-coded ``check_in``; there is no per-tournament
profile stage. The subscription entry is the only reader of
the registration node's ``subscription_stage``, and it is gated on
``enforces_subscription`` rather than ``require_subscription``: an armed toggle
over an empty rule disarms itself rather than refusing everyone.

Adding a requirement is one entry here plus one signal resolver.
"""

from __future__ import annotations

from src.services.admission.requirements import open_profile, subscription
from src.services.admission.types import AdmissionStage, Requirement

__all__ = ("REQUIREMENTS",)

REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        key=open_profile.KEY,
        enabled=lambda cfg: cfg.require_open_profile,
        stage=lambda cfg: AdmissionStage.check_in,
        evaluate=open_profile.eval_open_profile,
    ),
    Requirement(
        key=subscription.KEY,
        enabled=lambda cfg: cfg.enforces_subscription,
        stage=lambda cfg: cfg.subscription_stage,
        evaluate=subscription.eval_subscription,
    ),
)

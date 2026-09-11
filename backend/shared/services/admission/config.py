"""What the tournament and its workspace decided, as one value.

Assembled ONCE per request and passed by value. Two owners are folded in here on
purpose, because that split is correct and should not leak further:

- the tournament's ``registration_form`` holds the TOGGLES (does this tournament
  require the thing, and from which stage);
- the workspace's ``subscriptions.requirement`` holds the RULE itself, so a new
  tournament does not re-ask which providers count (the 2026-08-05 design).

No session, no loader. ``shared`` cannot import tournament-service's form reader,
and the gates are handed duck-typed form objects anyway -- the ORM row in
production, a stub in the unit tests -- so every read below is a defensive
``getattr``. That is inherited behaviour, not caution for its own sake: the gate
this layer replaced read its form the same way, because a form that predates a
column must behave like the default rather than raise mid-admission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from shared.services.admission.types import AdmissionStage

if TYPE_CHECKING:
    from shared.services.subscriptions import SubscriptionRequirement

__all__ = ("AdmissionConfig",)


def _stage(raw: Any) -> AdmissionStage:
    """Read a stored stage value, defaulting to the LOOSER gate.

    Anything unrecognised means check-in. An unknown stage is a config or
    migration error, and the safe reading of one is the LATER gate: a typo must
    not start refusing sign-ups nobody asked it to refuse. This preserves verbatim
    the rule the deleted ``subscription_gate.enforces_at_registration`` carried --
    do not tighten it into a strict parse.
    """
    if raw is None:
        return AdmissionStage.check_in
    try:
        return AdmissionStage(str(raw))
    except ValueError:
        return AdmissionStage.check_in


@dataclass(frozen=True, slots=True)
class AdmissionConfig:
    #: Owner of the subscription rule and the provider configs. Nullable because
    #: the config is also built from stubs and from ``form is None``; a subscription
    #: requirement without it cannot be resolved at all, which
    #: ``enforces_subscription`` below treats as "nothing to enforce" rather than
    #: as a refusal.
    workspace_id: int | None = None
    require_open_profile: bool = False
    open_profile_scope: Literal["main", "all"] = "main"
    require_subscription: bool = False
    subscription_stage: AdmissionStage = AdmissionStage.check_in
    #: ``player`` evaluates the workspace rule per account. ``team`` still
    #: runs that rule, but a current coverage stamp on the registrant's team
    #: satisfies it as well — see ``shared.domain.team_subscription``.
    subscription_scope: Literal["player", "team"] = "player"
    #: The workspace rule. ``None`` means there is nothing to enforce even when
    #: ``require_subscription`` is on -- an armed toggle over an empty rule
    #: disarms itself rather than refusing everyone.
    subscription_rule: SubscriptionRequirement | None = None

    @classmethod
    def from_form(
        cls,
        form: Any | None,
        *,
        subscription_rule: SubscriptionRequirement | None = None,
    ) -> AdmissionConfig:
        """Project a ``BalancerRegistrationForm`` (or a stub) into a config.

        ``form is None`` yields the all-off config: a tournament with no
        registration form has nothing to submit against, so it also has no
        requirements to enforce.
        """
        if form is None:
            return cls()

        scope = str(getattr(form, "open_profile_scope", "main") or "main")
        return cls(
            require_open_profile=bool(getattr(form, "require_open_profile", False)),
            open_profile_scope="all" if scope == "all" else "main",
            require_subscription=bool(getattr(form, "require_subscription", False)),
            workspace_id=getattr(form, "workspace_id", None),
            subscription_stage=_stage(getattr(form, "subscription_stage", None)),
            subscription_scope=(
                "team" if str(getattr(form, "subscription_scope", "player") or "player") == "team" else "player"
            ),
            subscription_rule=subscription_rule,
        )

    @property
    def enforces_subscription(self) -> bool:
        """Whether the subscription requirement can block anything at all.

        Three conditions, and the last two are not paranoia: an armed toggle over
        an empty workspace rule, or over a form that cannot name its workspace,
        must disarm itself. The alternative -- treating "I cannot read the rule" as
        "you fail the rule" -- refuses every registrant in the tournament.
        """
        return self.require_subscription and self.subscription_rule is not None and self.workspace_id is not None

"""What the tournament and its workspace decided, as one value.

Assembled once per request and passed by value. The registration node's config holds the TOGGLES (whether a
requirement is on, and from which stage); the workspace's ``subscriptions.requirement`` holds the RULE, so a
new tournament does not re-ask which providers count.

Forms are duck-typed (the ORM row, or a stub in unit tests), so every read is a
defensive ``getattr``: a form that predates a column must behave like the
default rather than raise mid-admission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from src.services.admission.types import AdmissionStage

if TYPE_CHECKING:
    from shared.domain.flow.config import RegistrationNodeConfig
    from shared.services.subscriptions import SubscriptionRequirement

__all__ = ("AdmissionConfig",)


def _stage(raw: Any) -> AdmissionStage:
    """Read a stored stage value, defaulting to the LOOSER gate.

    Anything unrecognised means check-in: a typo or migration error must not start
    refusing sign-ups nobody asked it to refuse. Do not tighten into a strict parse.
    """
    if raw is None:
        return AdmissionStage.check_in
    try:
        return AdmissionStage(str(raw))
    except ValueError:
        return AdmissionStage.check_in


@dataclass(frozen=True, slots=True)
class AdmissionConfig:
    #: Owner of the subscription rule and provider configs. ``None`` (stubs,
    #: ``form is None``) makes ``enforces_subscription`` false: nothing to
    #: enforce, never a refusal.
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
        node_config: RegistrationNodeConfig,
        *,
        subscription_rule: SubscriptionRequirement | None = None,
    ) -> AdmissionConfig:
        """Project a ``RegistrationForm`` (or a stub) and the registration node's config into a config.

        ``form is None`` yields the all-off config: a tournament with no
        registration form has nothing to submit against, so it also has no
        requirements to enforce. The subscription toggles are the node's (per intake); the open-profile
        requirement is the form's.
        """
        if form is None:
            return cls()

        scope = str(getattr(form, "open_profile_scope", "main") or "main")
        return cls(
            require_open_profile=bool(getattr(form, "require_open_profile", False)),
            open_profile_scope="all" if scope == "all" else "main",
            require_subscription=node_config.require_subscription,
            workspace_id=getattr(form, "workspace_id", None),
            subscription_stage=_stage(node_config.subscription_stage),
            subscription_scope=node_config.subscription_scope,
            subscription_rule=subscription_rule,
        )

    @property
    def enforces_subscription(self) -> bool:
        """Whether the subscription requirement can block anything at all.

        An armed toggle over an empty rule, or over a form that cannot name its
        workspace, disarms itself: "cannot read the rule" must not mean "fails the rule".
        """
        return self.require_subscription and self.subscription_rule is not None and self.workspace_id is not None

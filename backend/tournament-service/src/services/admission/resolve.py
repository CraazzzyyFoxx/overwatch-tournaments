"""All the I/O, paid once per list.

Two entry points, split by "deciding vs displaying", not by stage: a
participants page and a check-in gate ask about the same stage.

- :func:`resolve_admission` answers for a whole list without touching a provider.
  Every read is batched, because resolving per registration serializes behind
  Discord's per-guild rate-limit bucket. It passes ``allow_stale``: a stored
  ``active`` of any age is fine for a badge, and an uncollected user is
  ``unknown`` until the collector's next sweep.
- :func:`resolve_admission_for_gate` answers for ONE registration and forces a
  live provider look: that is the moment a stale ``active`` must not be trusted,
  and one user is one provider call.

Depends only on the ``RequirementEvaluator`` Protocol, never on a concrete
resolver.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import SubscriptionCollectionSource
from shared.domain.team_subscription import team_subscription_is_current
from shared.services.subscriptions import Outcome, SubscriptionRequirement, SubscriptionVerdict
from shared.services.subscriptions.requirement import evaluate_requirement
from src.services.admission.config import AdmissionConfig
from src.services.admission.evaluate import evaluate, stage_reached
from src.services.admission.profile_visibility import resolve_profiles_open
from src.services.admission.registry import REQUIREMENTS
from src.services.admission.requirements.subscription import build_subscription_signal
from src.services.admission.signals import AdmissionSignals, ProfileSignal, SubscriptionSignal
from src.services.admission.types import AdmissionEvaluation, AdmissionStage

__all__ = ("load_auth_user_ids", "resolve_admission", "resolve_admission_for_gate")

#: Which collection source a resolve is attributed to in the check log. Display
#: reads are ``scheduled``: they are not a decision anybody made, and tagging them
#: as a registration or check-in attempt would make the audit trail unreadable.
_GATE_SOURCE: dict[AdmissionStage, SubscriptionCollectionSource] = {
    AdmissionStage.registration: SubscriptionCollectionSource.registration,
    AdmissionStage.check_in: SubscriptionCollectionSource.check_in,
}


class RequirementEvaluator(Protocol):
    """The slice of ``SubscriptionResolver`` this module needs."""

    async def evaluate(
        self,
        *,
        workspace_id: int,
        auth_user_ids: Sequence[int],
        requirement: SubscriptionRequirement,
        force_refresh: bool = False,
        allow_stale: bool = False,
        source: str = ...,
    ) -> dict[int, tuple[Outcome, dict[str, SubscriptionVerdict]]]: ...

    async def accepted_code_providers(self, *, workspace_id: int, providers: Collection[str]) -> set[str]: ...


async def load_auth_user_ids(session: AsyncSession, registrations: Sequence[Any]) -> dict[int, int | None]:
    """Map ``registration.id`` -> ``auth.user.id``.

    Entitlements are keyed on the site account, but a registration only anchors to
    a ``workspace_member`` -> ``players.user`` -> ``auth_user_id``. A registration
    with no linked account yields ``None`` and is skipped rather than resolved --
    a manual row an organizer typed in has no account to ask a provider about.
    """
    reg_ids = [reg.id for reg in registrations]
    if not reg_ids:
        return {}
    rows = await session.execute(
        sa.select(models.Registration.id, models.User.auth_user_id)
        .select_from(models.Registration)
        .join(
            models.WorkspaceMember,
            models.Registration.workspace_member_id == models.WorkspaceMember.id,
        )
        .join(models.User, models.WorkspaceMember.player_id == models.User.id)
        .where(models.Registration.id.in_(reg_ids))
    )
    # `.tuples()` is what makes this a real 2-tuple: without it a `Row` is not an
    # `Iterable[tuple[...]]` and `dict()` does not type-check.
    mapped = dict(rows.tuples().all())
    return {reg_id: mapped.get(reg_id) for reg_id in reg_ids}


def _coverage_signal() -> SubscriptionSignal:
    return SubscriptionSignal(outcome="satisfied")


async def _team_stamp_is_current(session: AsyncSession, registration: Any) -> bool:
    """True when this registration sits on a currently covered team.

    Relationship first so a caller that already loaded the team pays nothing.
    Extra lookups use optional session methods so the unit stubs in
    test_admission_resolve (execute-only) skip the overlay instead of exploding.
    """
    if registration is None:
        return False
    team = getattr(registration, "registration_team", None)
    if team is None:
        team_id = getattr(registration, "registration_team_id", None)
        if not team_id:
            return False
        getter = getattr(session, "get", None)
        if callable(getter):
            try:
                team = await getter(models.RegistrationTeam, team_id)
            except TypeError:
                team = None
        if team is None:
            scalar = getattr(session, "scalar", None)
            if callable(scalar):
                try:
                    team = await scalar(sa.select(models.RegistrationTeam).where(models.RegistrationTeam.id == team_id))
                except TypeError:
                    team = None
    return bool(team) and team_subscription_is_current(team)


async def _profiles(
    session: AsyncSession,
    registrations: Sequence[Any],
    config: AdmissionConfig,
) -> dict[int, ProfileSignal]:
    """One batched ``rank.account_state`` read, or nothing at all.

    A tournament that does not require open profiles pays zero queries -- the
    guard is the flag, not an empty result.
    """
    if not config.require_open_profile:
        return {}
    return await resolve_profiles_open(session, registrations, scope=config.open_profile_scope)


def _subscription_target(config: AdmissionConfig, stage: AdmissionStage) -> tuple[int, SubscriptionRequirement] | None:
    """The workspace and rule to resolve against, or ``None`` when there is none.

    Re-checks what ``enforces_subscription`` already proved rather than asserting
    (asserts vanish under ``-O``); ``None`` degrades to "nothing to enforce".

    A rule not yet due at ``stage`` returns ``None`` before any I/O: resolving it
    would pay a forced provider call ``blocks_at`` discards, and write a
    ``source="registration"`` check-log row for a tournament that does not gate
    sign-up.
    """
    if not config.enforces_subscription or config.workspace_id is None or config.subscription_rule is None:
        return None
    if not stage_reached(config.subscription_stage, stage):
        return None
    return config.workspace_id, config.subscription_rule


async def _subscriptions(
    session: AsyncSession,
    registrations: Sequence[Any],
    config: AdmissionConfig,
    *,
    resolver: RequirementEvaluator | None,
    force_refresh: bool,
    allow_stale: bool = False,
    source: SubscriptionCollectionSource,
    stage: AdmissionStage,
) -> dict[int, SubscriptionSignal]:
    """One composed outcome per registration, in one resolver pass.

    Guards run cheapest-first, so a list with no linked accounts never reaches
    the resolver. A member of a currently covered team is answered by the team's
    stamp and never asked about.
    """
    target = _subscription_target(config, stage)
    if resolver is None or target is None:
        return {}
    workspace_id, rule = target

    covered = {
        registration.id
        for registration in registrations
        if config.subscription_scope == "team"
        and (team := getattr(registration, "registration_team", None)) is not None
        and team_subscription_is_current(team)
    }
    signals: dict[int, SubscriptionSignal] = {reg_id: _coverage_signal() for reg_id in covered}
    auth_user_id_by_reg = await load_auth_user_ids(session, [r for r in registrations if r.id not in covered])
    user_ids = list(dict.fromkeys(uid for uid in auth_user_id_by_reg.values() if uid is not None))
    if not user_ids:
        return signals

    outcomes = await resolver.evaluate(
        workspace_id=workspace_id,
        auth_user_ids=user_ids,
        requirement=rule,
        force_refresh=force_refresh,
        allow_stale=allow_stale,
        source=source,
    )

    for reg_id, auth_user_id in auth_user_id_by_reg.items():
        if auth_user_id is None:
            continue
        resolved = outcomes.get(auth_user_id)
        if resolved is None:
            continue
        outcome, verdicts = resolved
        signals[reg_id] = build_subscription_signal(outcome, verdicts)
    return signals


async def _soften_deferred(
    config: AdmissionConfig,
    outcome: Outcome,
    verdicts: dict[str, SubscriptionVerdict],
    *,
    resolver: RequirementEvaluator,
) -> SubscriptionSignal:
    """Re-compose one refusal that a challenge code could still fix.

    Sign-up only: the code ``phrase`` field exists on the check-in screen alone,
    so a provider the player is one paste away from satisfying must not refuse
    sign-up (under ``mode="any"`` the rule may still be satisfiable). At check-in
    every refusal is final.
    """
    target = _subscription_target(config, AdmissionStage.registration)
    if target is None:
        return build_subscription_signal(outcome, verdicts)
    workspace_id, rule = target

    deferred = await resolver.accepted_code_providers(workspace_id=workspace_id, providers=rule.providers)
    if not deferred:
        return build_subscription_signal(outcome, verdicts)
    relaxed = evaluate_requirement(rule, verdicts, deferred_providers=deferred)
    return build_subscription_signal(relaxed, verdicts)


#: Stands in for ``registration.id`` when there is no row yet. Never collides with
#: a real id (``BIGSERIAL`` starts at 1) and never leaves this module: the signup
#: gate reads ``blockers``, not the id.
_PROSPECTIVE_ID = 0


def _signals_for(
    registration: Any | None,
    *,
    profiles: Mapping[int, ProfileSignal],
    subscriptions: Mapping[int, SubscriptionSignal],
) -> AdmissionSignals:
    """Lifecycle facts for one registration, or for somebody who has none yet.

    ``registration is None`` is the sign-up gate, which runs before the row
    exists. Every lifecycle fact is then falsy, so ``decision`` is
    ``not_admitted``; that gate reads ``blockers``, never ``decision``.
    """
    if registration is None:
        return AdmissionSignals(
            registration_id=_PROSPECTIVE_ID,
            status="",
            balancer_status=None,
            checked_in=False,
            profile=None,
            subscription=subscriptions.get(_PROSPECTIVE_ID),
        )
    return AdmissionSignals(
        registration_id=registration.id,
        status=getattr(registration, "status", ""),
        balancer_status=getattr(registration, "balancer_status", None),
        checked_in=bool(getattr(registration, "checked_in", False)),
        profile=profiles.get(registration.id),
        subscription=subscriptions.get(registration.id),
    )


async def resolve_admission(
    session: AsyncSession,
    registrations: Sequence[Any],
    *,
    config: AdmissionConfig,
    resolver: RequirementEvaluator | None = None,
    stage: AdmissionStage = AdmissionStage.check_in,
    live: bool = False,
) -> dict[int, AdmissionEvaluation]:
    """Evaluate a whole list without forcing a provider call.

    Display surfaces should keep the default ``stage=check_in``: it is the last
    gate, the only one at which every requirement is in force, so a badge never
    shows a requirement as harmless right up until check-in refuses the player.

    ``live=True`` is the check-in gate for a whole roster: one forced provider
    batch, attributed to the stage's collection source, instead of one
    :func:`resolve_admission_for_gate` per member. It applies no sign-up
    softening, so it is for ``stage=check_in`` only.
    """
    if not registrations:
        return {}
    if live and stage is not AdmissionStage.check_in:
        raise ValueError("a live roster resolve is the check-in gate only")

    profiles = await _profiles(session, registrations, config)
    subscriptions = await _subscriptions(
        session,
        registrations,
        config,
        resolver=resolver,
        force_refresh=live,
        allow_stale=not live,
        source=_GATE_SOURCE[stage] if live else SubscriptionCollectionSource.scheduled,
        stage=stage,
    )
    return {
        registration.id: evaluate(
            config,
            _signals_for(registration, profiles=profiles, subscriptions=subscriptions),
            stage=stage,
            requirements=REQUIREMENTS,
        )
        for registration in registrations
    }


async def resolve_admission_for_gate(
    session: AsyncSession,
    registration: Any | None,
    *,
    config: AdmissionConfig,
    resolver: RequirementEvaluator | None,
    stage: AdmissionStage,
    auth_user_id: int | None = None,
) -> AdmissionEvaluation:
    """Evaluate ONE subject for a blocking decision, forcing a live look.

    At ``stage=registration`` a refusal is softened by any provider a challenge
    code could still satisfy (see :func:`_soften_deferred`).

    ``registration`` is ``None`` at sign-up (the row does not exist yet), so the
    caller passes ``auth_user_id``; without it the subscription resolve is
    skipped and fails open, silently not gating sign-up. When both are given,
    ``auth_user_id`` wins and the join is skipped.
    """
    if registration is None and auth_user_id is None:
        raise ValueError("resolve_admission_for_gate needs a registration or an auth_user_id")

    profiles = await _profiles(session, [registration], config) if registration is not None else {}
    source = _GATE_SOURCE[stage]
    subject_id = _PROSPECTIVE_ID if registration is None else registration.id

    subscriptions: dict[int, SubscriptionSignal] = {}
    target = _subscription_target(config, stage)
    if (
        config.subscription_scope == "team"
        and registration is not None
        and await _team_stamp_is_current(session, registration)
    ):
        subscriptions = {subject_id: _coverage_signal()}
        target = None
    if resolver is not None and target is not None:
        workspace_id, rule = target
        if auth_user_id is None:
            auth_user_id = (await load_auth_user_ids(session, [registration])).get(subject_id)
        if auth_user_id is not None:
            resolved = await resolver.evaluate(
                workspace_id=workspace_id,
                auth_user_ids=[auth_user_id],
                requirement=rule,
                force_refresh=True,
                source=source,
            )
            answer = resolved.get(auth_user_id)
            if answer is not None:
                outcome, verdicts = answer
                # Deferring can only ever WEAKEN a refusal, so a non-blocking
                # outcome needs no second question -- and the code-config read is
                # skipped entirely on the happy path.
                if stage is AdmissionStage.registration and outcome is Outcome.REFUSED:
                    signal = await _soften_deferred(config, outcome, verdicts, resolver=resolver)
                else:
                    signal = build_subscription_signal(outcome, verdicts)
                subscriptions = {subject_id: signal}

    return evaluate(
        config,
        _signals_for(registration, profiles=profiles, subscriptions=subscriptions),
        stage=stage,
        requirements=REQUIREMENTS,
    )

"""All the I/O, paid once per list.

Two entry points, and the split between them is NOT the stage:

- :func:`resolve_admission` answers for a whole list without touching a provider.
  Participants pages and the admin table use it, and it is the reason every read
  below is batched: resolving per registration serializes behind Discord's
  per-guild rate-limit bucket, so a 200-row page would spend minutes in one
  bucket. It passes ``allow_stale`` -- a stored ``active`` of any age is fine for
  a badge, and a user nobody has collected yet is ``unknown`` until the
  collector's next sweep. Refreshing from the list read is what made every other
  page load of a 120-row table cost one Twitch call per registrant.
- :func:`resolve_admission_for_gate` answers for ONE registration and forces a
  live provider look. That is the moment a stale ``active`` must not be trusted,
  and one user is one provider call, so it is cheap.

The earlier sketch of this module derived ``force_refresh`` from the stage. That
was wrong: a participants page and a check-in gate ask about the SAME stage and
must behave differently, because the difference is "am I deciding or displaying",
not "which gate". Encoding it as a boolean parameter on one function would have
put the two behaviours one typo apart at every call site, so they are two
functions instead, each with one behaviour.

Everything here depends on Protocols only (``RequirementEvaluator``), never on a
concrete resolver. That is what keeps the planned Discord transport change --
RPC into discord-service, reading discord.py's gateway-pushed member cache --
confined to ``providers/discord_role.py``, with nothing in this layer to touch.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import SubscriptionCollectionSource
from shared.domain.team_subscription import team_subscription_is_current
from shared.services.admission.config import AdmissionConfig
from shared.services.admission.evaluate import evaluate, stage_reached
from shared.services.admission.registry import REQUIREMENTS
from shared.services.admission.requirements.subscription import build_subscription_signal
from shared.services.admission.signals import AdmissionSignals, ProfileSignal, SubscriptionSignal
from shared.services.admission.types import AdmissionEvaluation, AdmissionStage
from shared.services.profile_visibility import resolve_profiles_open
from shared.services.subscriptions import Outcome, SubscriptionRequirement, SubscriptionVerdict
from shared.services.subscriptions.requirement import evaluate_requirement

__all__ = ("load_auth_user_ids", "resolve_admission", "resolve_admission_for_gate")

#: Which collection source a resolve is attributed to in the check log. Display
#: reads are ``scheduled``: they are not a decision anybody made, and tagging them
#: as a registration or check-in attempt would make the audit trail unreadable.
_GATE_SOURCE: dict[AdmissionStage, SubscriptionCollectionSource] = {
    AdmissionStage.registration: SubscriptionCollectionSource.registration,
    AdmissionStage.check_in: SubscriptionCollectionSource.check_in,
}


class RequirementEvaluator(Protocol):
    """The slice of ``SubscriptionResolver`` this module needs. Deliberately narrow."""

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
        sa.select(models.BalancerRegistration.id, models.User.auth_user_id)
        .select_from(models.BalancerRegistration)
        .join(
            models.WorkspaceMember,
            models.BalancerRegistration.workspace_member_id == models.WorkspaceMember.id,
        )
        .join(models.User, models.WorkspaceMember.player_id == models.User.id)
        .where(models.BalancerRegistration.id.in_(reg_ids))
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
                team = await getter(models.BalancerRegistrationTeam, team_id)
            except TypeError:
                team = None
        if team is None:
            scalar = getattr(session, "scalar", None)
            if callable(scalar):
                try:
                    team = await scalar(
                        sa.select(models.BalancerRegistrationTeam).where(models.BalancerRegistrationTeam.id == team_id)
                    )
                except TypeError:
                    team = None
    return bool(team) and team_subscription_is_current(team)


async def _profiles(
    session: AsyncSession,
    registrations: Sequence[Any],
    config: AdmissionConfig,
) -> dict[int, ProfileSignal]:
    """One batched ``battle_tag_state`` read, or nothing at all.

    A tournament that does not require open profiles pays zero queries -- the
    guard is the flag, not an empty result.
    """
    if not config.require_open_profile:
        return {}
    return await resolve_profiles_open(session, registrations, scope=config.open_profile_scope)


def _subscription_target(config: AdmissionConfig, stage: AdmissionStage) -> tuple[int, SubscriptionRequirement] | None:
    """The workspace and rule to resolve against, or ``None`` when there is none.

    ``enforces_subscription`` already proves the first two values are set, but
    re-reading them here rather than asserting is deliberate: an ``assert``
    narrowing a production path disappears under ``-O``, and what it would leave
    behind is a ``None`` reaching ``resolver.evaluate`` as a workspace id. An early
    ``None`` degrades to "nothing to enforce", which is the direction this whole
    layer fails in.

    ``stage`` is the third condition and it is not an optimisation. A rule staged
    at check-in cannot bite during sign-up, so resolving it there would pay a
    forced provider call whose answer ``blocks_at`` then correctly discards -- and
    would write a ``source="registration"`` row into the check log, attributing a
    sign-up decision to a tournament that does not gate sign-up. The gate this
    layer replaced returned before any I/O for exactly this case.
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

    Guards are ordered cheapest-first for a reason inherited from
    ``build_subscription_reads``: a list whose registrations all lack a linked
    account must not pay for the rule read it would discard one line later.
    """
    target = _subscription_target(config, stage)
    if resolver is None or target is None:
        return {}
    workspace_id, rule = target

    auth_user_id_by_reg = await load_auth_user_ids(session, registrations)
    user_ids = list(dict.fromkeys(uid for uid in auth_user_id_by_reg.values() if uid is not None))
    if not user_ids:
        return {}

    outcomes = await resolver.evaluate(
        workspace_id=workspace_id,
        auth_user_ids=user_ids,
        requirement=rule,
        force_refresh=force_refresh,
        allow_stale=allow_stale,
        source=source,
    )

    signals: dict[int, SubscriptionSignal] = {}
    for reg_id, auth_user_id in auth_user_id_by_reg.items():
        if auth_user_id is None:
            continue
        resolved = outcomes.get(auth_user_id)
        if resolved is None:
            continue
        outcome, verdicts = resolved
        signals[reg_id] = build_subscription_signal(outcome, verdicts)
    if config.subscription_scope == "team":
        for registration in registrations:
            team = getattr(registration, "registration_team", None)
            if team is not None and team_subscription_is_current(team):
                signals[registration.id] = _coverage_signal()
    return signals


async def _soften_deferred(
    config: AdmissionConfig,
    outcome: Outcome,
    verdicts: dict[str, SubscriptionVerdict],
    *,
    resolver: RequirementEvaluator,
) -> SubscriptionSignal:
    """Re-compose one refusal that a challenge code could still fix.

    Only meaningful at sign-up. The ``phrase`` field where a patron pastes a code
    exists on the check-in screen and nowhere else, so refusing a sign-up over a
    provider the player is one paste away from satisfying would be wrong -- and
    under ``mode="any"`` it would refuse a rule they can still satisfy on the
    other side. Check-in never routes through here: the field is right there, so
    every refusal at that gate is final.
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

    ``registration is None`` is the sign-up gate: it runs BEFORE the row exists, so
    the subject of the question is the auth user, not a registration. Every
    lifecycle fact is then falsy, which makes ``ready`` false and therefore
    ``decision`` ``not_admitted`` -- correct but useless, and the reason the sign-up
    gate reads ``blockers`` and never ``decision``. A prospective registrant is not
    "not admitted", they are "not yet anything".
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
) -> dict[int, AdmissionEvaluation]:
    """Evaluate a whole list without forcing a provider call.

    ``stage`` defaults to ``check_in`` and display surfaces should leave it there.
    That is not a shrug: stages are ordered, ``registration`` implies ``check_in``,
    so the last gate is the only one at which every requirement is in force -- and
    a badge that showed a requirement as harmless because its gate is still ahead
    would tell a player they are fine right up until check-in refuses them.
    """
    if not registrations:
        return {}

    profiles = await _profiles(session, registrations, config)
    subscriptions = await _subscriptions(
        session,
        registrations,
        config,
        resolver=resolver,
        force_refresh=False,
        allow_stale=True,
        source=SubscriptionCollectionSource.scheduled,
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

    Forces because this is the instant a cached ``active`` must not be trusted,
    and it is one user rather than a list. At ``stage=registration`` the refusal is
    additionally softened by any provider a challenge code could still satisfy
    (see :func:`_soften_deferred`).

    ``registration`` may be ``None``, and ``auth_user_id`` exists because of it. The
    sign-up gate runs before the row exists, so deriving the auth user from
    ``registration.id`` -- which is what this function did first -- found nothing,
    skipped the subscription resolve, answered ``undetermined``, failed open, and
    silently stopped blocking sign-ups. That is a live regression against the
    behaviour ``assert_subscription_allows_registration`` had, not a test artifact,
    and the fix is to let the caller pass the subject it already holds: at both
    sign-up sites the acting user's id is right there in the request.

    When both are given, ``auth_user_id`` wins and the join is skipped -- a caller
    who knows the answer should not pay a query to be told it.
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

"""The one place a write path asks "is this player allowed through this gate".

Three handlers used to answer that question in three different shapes:
``reg_pub_create`` and ``regteam_create`` called a subscription gate, and
``reg_pub_check_in`` called that gate plus an inline ``if`` for the profile. Which
requirement bit at which moment was therefore encoded by the presence, absence
and ORDER of calls across those handlers -- readable only by grepping all of
them, and wrong the moment a fourth write path forgot one. Here it is one call
with an explicit ``stage`` (D8).

Two things are deliberate about the split below.

**The config is loaded once per request and passed by value** (D12). It used to
be read twice per registration submit -- once in the handler to feed the gate,
once again inside ``submit_public_registration`` -- against a form an organizer
can edit live, so the two reads could legitimately disagree. Now the toggles and
the workspace rule are one frozen value, and everything downstream projects from
it.

**``load_admission_config`` reads the form through**
``_common_service.get_registration_form``, which is the single form reader. It is
not cached and must not be: an organizer changes the form in real time, and a
stale read is either a false refusal or a false admission.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.services.admission import AdmissionConfig, AdmissionEvaluation, AdmissionStage
from shared.services.admission.gates import assert_admitted
from shared.services.admission.resolve import resolve_admission_for_gate
from shared.services.subscriptions.wiring import build_resolver
from src.core.broker import optional_broker
from src.core.config import settings
from src.services.registration._common import _common_service

__all__ = ("assert_admitted_at", "build_admission_resolver", "load_admission_config")


def build_admission_resolver(session: AsyncSession) -> Any:
    """Resolver wired with this service's provider credentials.

    Built per call rather than memoized: the Discord strategy caches a guild's
    role list for the lifetime of the resolver, and that cache must not outlive
    the request that filled it -- a role mapping edited mid-tournament would
    otherwise keep refusing patrons it no longer applies to.
    """
    return build_resolver(
        session,
        discord_bot_token=settings.discord_token,
        twitch_client_id=settings.twitch_client_id,
        broker=optional_broker(),
        proxy=settings.proxy_url,
    )


async def load_admission_config(
    session: AsyncSession,
    tournament_id: int,
    *,
    resolver: Any | None = None,
) -> AdmissionConfig:
    """Assemble the tournament's toggles and its workspace's rule into one value.

    The two owners stay separate on purpose and are folded only here: the form
    holds whether this tournament requires the thing, the workspace holds the rule
    itself, so a new tournament does not re-declare which providers count.

    The rule is fetched only when the toggle is on. That ordering is the whole
    reason a tournament with subscriptions switched off pays nothing on this path,
    and it matches ``AdmissionConfig.enforces_subscription``, which treats an
    armed toggle over an absent rule as nothing to enforce rather than as a
    refusal -- the resolver owns the parse and fails open on a malformed row, so
    "the config is broken" must never read as "you fail the rule".

    ``resolver`` lets a caller that already holds one hand it over instead of
    paying for a second. It is optional because the read paths have no resolver of
    their own and only need the rule row.
    """
    form = await _common_service.get_registration_form(session, tournament_id)
    rule = None
    if form is not None and form.require_subscription:
        rule = await (resolver or build_admission_resolver(session)).load_requirement(workspace_id=form.workspace_id)
    return AdmissionConfig.from_form(form, subscription_rule=rule)


async def assert_admitted_at(
    session: AsyncSession,
    registration: Any | None,
    *,
    tournament_id: int,
    auth_user_id: int,
    stage: AdmissionStage,
) -> AdmissionEvaluation:
    """Refuse this subject at ``stage``, or return why it did not have to.

    The evaluation comes back so a caller can read the same answer the gate
    decided on -- the check-in handler serializes it into its response rather than
    resolving a second time.

    ``registration`` is ``None`` at sign-up, where the row does not exist yet, and
    ``auth_user_id`` is what identifies the subject in that case (see
    ``resolve_admission_for_gate``). One consequence matters: with no row every
    lifecycle fact is falsy, so ``ready`` is false and ``decision`` comes back
    ``not_admitted`` for a perfectly acceptable applicant. **Never gate on
    ``decision`` here** -- only on ``blockers``, which is exactly what
    :func:`assert_admitted` reads. ``ready`` is data completeness (approved, ranked
    in the balancer pool), not a requirement, and it is not this gate's business.
    """
    resolver = build_admission_resolver(session)
    config = await load_admission_config(session, tournament_id, resolver=resolver)
    evaluation = await resolve_admission_for_gate(
        session,
        registration,
        config=config,
        resolver=resolver,
        stage=stage,
        auth_user_id=auth_user_id,
    )
    assert_admitted(evaluation, stage=stage, config=config)
    return evaluation

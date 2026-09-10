"""The I/O layer's two promises: one pass per list, and force only when deciding.

Neither is checkable by reading ``resolve.py``, and both are the kind of thing a
well-meaning edit breaks silently:

**One pass.** Resolving per registration serializes behind Discord's per-guild
rate-limit bucket, so a 200-row participants page would sit in one bucket for
minutes. The tests below count ``session.execute`` calls and ``resolver.evaluate``
calls, because a fan-out regression still returns the right answer -- just far too
slowly, in production only, under load only.

**Force only when deciding.** A display read must not force a provider call and a
gate must, and the two ask about the same stage. That is why they are separate
functions rather than one with a boolean; these tests pin that the split survives.

No database: the session is a stub returning queued rows, which is enough because
the two statements this module issues are exercised for real by
``test_admission_open_profile`` and by the integration suites.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.core.enums import SubscriptionCollectionSource  # noqa: E402
from shared.services.admission import (  # noqa: E402
    AdmissionConfig,
    AdmissionDecision,
    AdmissionStage,
    RequirementState,
)
from shared.services.admission.resolve import (  # noqa: E402
    resolve_admission,
    resolve_admission_for_gate,
)
from shared.services.subscriptions import (  # noqa: E402
    Outcome,
    ProviderRequirement,
    SubscriptionRequirement,
    SubscriptionState,
    SubscriptionVerdict,
)

NOW = datetime(2026, 9, 2, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _Result:
    """Stands in for both shapes this module reads: ``.all()`` and ``.tuples().all()``."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def tuples(self) -> _Result:
        return self


class _Session:
    """Returns queued results in call order and remembers how often it was asked."""

    def __init__(self, *results: list[tuple[Any, ...]]) -> None:
        self._queue = list(results)
        self.executes = 0

    async def execute(self, _statement: Any) -> _Result:
        self.executes += 1
        if not self._queue:
            raise AssertionError("resolve.py issued more statements than the test queued")
        return _Result(self._queue.pop(0))


@dataclass
class _Resolver:
    """Records every call so the force/source matrix can be asserted."""

    outcome: Outcome = Outcome.SATISFIED
    verdicts: dict[str, SubscriptionVerdict] = field(default_factory=dict)
    code_providers: set[str] = field(default_factory=set)
    calls: list[dict[str, Any]] = field(default_factory=list)
    code_calls: int = 0

    async def evaluate(
        self,
        *,
        workspace_id: int,
        auth_user_ids: Any,
        requirement: Any,
        force_refresh: bool = False,
        allow_stale: bool = False,
        source: Any = SubscriptionCollectionSource.scheduled,
    ) -> dict[int, tuple[Outcome, dict[str, SubscriptionVerdict]]]:
        ids = list(auth_user_ids)
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "auth_user_ids": ids,
                "force_refresh": force_refresh,
                "allow_stale": allow_stale,
                "source": source,
            }
        )
        return dict.fromkeys(ids, (self.outcome, dict(self.verdicts)))

    async def accepted_code_providers(self, *, workspace_id: int, providers: Any) -> set[str]:
        self.code_calls += 1
        return set(self.code_providers)


def _verdict(state: str, *, reason_code: str | None = None) -> SubscriptionVerdict:
    return SubscriptionVerdict(
        state=state,
        tier_rank=None,
        tier_label=None,
        source="discord_role",
        checked_at=NOW,
        expires_at=None,
        evidence={"reason": reason_code} if reason_code else {},
    )


def _reg(reg_id: int, *, tag: str | None = "Player#1", checked_in: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=reg_id,
        status="approved",
        balancer_status="ready",
        checked_in=checked_in,
        battle_tag=tag,
        smurf_tags_json=None,
    )


_RULE = SubscriptionRequirement(mode="all", requirements=(ProviderRequirement(provider="discord", min_tier_rank=1),))


def _config(*, profile: bool = False, subscription: bool = False, stage: str = "check_in") -> AdmissionConfig:
    return AdmissionConfig.from_form(
        SimpleNamespace(
            workspace_id=7,
            require_open_profile=profile,
            open_profile_scope="main",
            require_subscription=subscription,
            subscription_stage=stage,
        ),
        subscription_rule=_RULE if subscription else None,
    )


# --------------------------------------------------------------------------- #
# One pass per list
# --------------------------------------------------------------------------- #


class BatchingTests(IsolatedAsyncioTestCase):
    async def test_nothing_enabled_issues_no_statements_at_all(self):
        """A tournament using neither requirement must not pay one query for them.

        The guard is the config flag, not an empty result set: the participants
        page of every tournament that never opted in would otherwise carry two
        reads apiece.
        """
        session = _Session()
        result = await resolve_admission(session, [_reg(1), _reg(2)], config=_config())

        assert session.executes == 0
        assert {reg_id: ev.decision for reg_id, ev in result.items()} == {
            1: AdmissionDecision.pending_check_in,
            2: AdmissionDecision.pending_check_in,
        }

    async def test_twenty_registrations_cost_one_profile_read(self):
        session = _Session([("player#1", "ok")])
        regs = [_reg(i, tag="Player#1") for i in range(1, 21)]

        await resolve_admission(session, regs, config=_config(profile=True))

        assert session.executes == 1

    async def test_twenty_registrations_cost_one_resolver_pass(self):
        """The rate-limit promise. One ``evaluate`` for the whole list, with every
        distinct auth user in a single call."""
        session = _Session([(i, 100 + i) for i in range(1, 21)])
        resolver = _Resolver()
        regs = [_reg(i) for i in range(1, 21)]

        await resolve_admission(session, regs, config=_config(subscription=True), resolver=resolver)

        assert session.executes == 1  # the auth-user-id mapping only
        assert len(resolver.calls) == 1
        assert resolver.calls[0]["auth_user_ids"] == [100 + i for i in range(1, 21)]

    async def test_an_empty_list_short_circuits(self):
        session = _Session()
        assert await resolve_admission(session, [], config=_config(profile=True, subscription=True)) == {}
        assert session.executes == 0

    async def test_a_list_with_no_linked_accounts_skips_the_resolver(self):
        """Cheapest guard first: a list whose rows have no site account must not
        pay for a resolver pass it would discard."""
        session = _Session([])  # the auth-user-id mapping finds nothing
        resolver = _Resolver()

        result = await resolve_admission(session, [_reg(1)], config=_config(subscription=True), resolver=resolver)

        assert resolver.calls == []
        verdict = result[1].requirement("subscription")
        assert verdict is not None
        assert verdict.state is RequirementState.undetermined


# --------------------------------------------------------------------------- #
# Force only when deciding
# --------------------------------------------------------------------------- #


class ForcingTests(IsolatedAsyncioTestCase):
    async def test_a_list_read_never_forces_and_logs_as_scheduled(self):
        """A badge is not a decision. Forcing here would put every open admin table
        on the provider's rate limit, and tagging it as a check-in attempt would
        make the audit trail unreadable. It also accepts stale rows: refreshing
        from a list read paid one provider call per registrant every TTL."""
        session = _Session([(1, 101)])
        resolver = _Resolver()

        await resolve_admission(session, [_reg(1)], config=_config(subscription=True), resolver=resolver)

        assert resolver.calls[0]["force_refresh"] is False
        assert resolver.calls[0]["allow_stale"] is True
        assert resolver.calls[0]["source"] is SubscriptionCollectionSource.scheduled

    async def test_a_gate_forces_and_names_its_stage(self):
        for stage, source in (
            (AdmissionStage.registration, SubscriptionCollectionSource.registration),
            (AdmissionStage.check_in, SubscriptionCollectionSource.check_in),
        ):
            with self.subTest(stage=stage):
                session = _Session([(1, 101)])
                resolver = _Resolver()

                await resolve_admission_for_gate(
                    session,
                    _reg(1),
                    config=_config(subscription=True, stage=stage.value),
                    resolver=resolver,
                    stage=stage,
                )

                assert resolver.calls[0]["force_refresh"] is True
                assert resolver.calls[0]["allow_stale"] is False
                assert resolver.calls[0]["source"] is source


# --------------------------------------------------------------------------- #
# Challenge-code deferral
# --------------------------------------------------------------------------- #


class DeferralTests(IsolatedAsyncioTestCase):
    def _refusing(self) -> _Resolver:
        return _Resolver(
            outcome=Outcome.REFUSED,
            verdicts={"discord": _verdict(SubscriptionState.INACTIVE, reason_code="no_mapped_role")},
            code_providers={"discord"},
        )

    async def test_a_refusal_at_sign_up_is_softened_by_a_redeemable_code(self):
        """The ``phrase`` field exists at check-in and nowhere else, so refusing a
        sign-up over a provider the player is one paste away from satisfying would
        turn a soft requirement into a hard deadline nobody set."""
        session = _Session([(1, 101)])
        resolver = self._refusing()

        evaluation = await resolve_admission_for_gate(
            session,
            _reg(1),
            config=_config(subscription=True, stage="registration"),
            resolver=resolver,
            stage=AdmissionStage.registration,
        )

        assert resolver.code_calls == 1
        assert evaluation.blockers == ()
        verdict = evaluation.requirement("subscription")
        assert verdict is not None
        assert verdict.state is RequirementState.undetermined

    async def test_the_same_refusal_at_check_in_is_final(self):
        session = _Session([(1, 101)])
        resolver = self._refusing()

        evaluation = await resolve_admission_for_gate(
            session,
            _reg(1),
            config=_config(subscription=True, stage="registration"),
            resolver=resolver,
            stage=AdmissionStage.check_in,
        )

        assert resolver.code_calls == 0
        assert [v.key for v in evaluation.blockers] == ["subscription"]
        assert evaluation.decision is AdmissionDecision.not_admitted

    async def test_a_satisfied_outcome_never_reads_the_code_config(self):
        """Deferral can only WEAKEN a refusal, so the happy path must not pay for
        the extra read."""
        session = _Session([(1, 101)])
        resolver = _Resolver(outcome=Outcome.SATISFIED, code_providers={"discord"})

        await resolve_admission_for_gate(
            session,
            _reg(1),
            config=_config(subscription=True, stage="registration"),
            resolver=resolver,
            stage=AdmissionStage.registration,
        )

        assert resolver.code_calls == 0

    async def test_no_redeemable_provider_leaves_the_refusal_standing(self):
        session = _Session([(1, 101)])
        resolver = self._refusing()
        resolver.code_providers = set()

        evaluation = await resolve_admission_for_gate(
            session,
            _reg(1),
            config=_config(subscription=True, stage="registration"),
            resolver=resolver,
            stage=AdmissionStage.registration,
        )

        assert [v.key for v in evaluation.blockers] == ["subscription"]


# --------------------------------------------------------------------------- #
# Fail-open at the I/O boundary
# --------------------------------------------------------------------------- #


class FailOpenTests(IsolatedAsyncioTestCase):
    async def test_a_missing_resolver_does_not_refuse_anybody(self):
        """A service wired without a resolver has no opinion on subscriptions. If
        that read as a refusal, one missing dependency would empty a check-in."""
        session = _Session()
        result = await resolve_admission(session, [_reg(1)], config=_config(subscription=True), resolver=None)

        verdict = result[1].requirement("subscription")
        assert verdict is not None
        assert verdict.state is RequirementState.undetermined
        assert result[1].decision is AdmissionDecision.pending_check_in

    async def test_a_closed_profile_blocks_but_a_manual_check_in_still_admits(self):
        """The end-to-end shape of the forced-admission fix, through the real
        registry: the requirement stays visibly blocked, and the player is in."""
        blocked = await resolve_admission(_Session([("player#1", "private")]), [_reg(1)], config=_config(profile=True))
        assert blocked[1].decision is AdmissionDecision.not_admitted
        assert [v.key for v in blocked[1].blockers] == ["open_profile"]

        forced = await resolve_admission(
            _Session([("player#1", "private")]), [_reg(1, checked_in=True)], config=_config(profile=True)
        )
        assert forced[1].decision is AdmissionDecision.admitted
        assert forced[1].blockers == ()
        assert [v.key for v in forced[1].overridden] == ["open_profile"]


# --------------------------------------------------------------------------- #
# The sign-up gate, which has no registration row to ask about
# --------------------------------------------------------------------------- #


class ProspectiveSubjectTests(IsolatedAsyncioTestCase):
    """The sign-up gate runs BEFORE the registration exists.

    This module's first version derived the auth user from ``registration.id``.
    For somebody who has not registered yet that join found nothing, the
    subscription resolve was skipped, the verdict came back ``undetermined``, it
    failed open, and the sign-up gate silently stopped blocking. A subscriber-only
    sign-up list would have quietly accepted everybody, and every test that
    exercised the gate with an EXISTING row would have stayed green.
    """

    async def test_a_refusal_blocks_a_sign_up_with_no_row_yet(self):
        session = _Session()
        resolver = _Resolver(
            outcome=Outcome.REFUSED,
            verdicts={"discord": _verdict(SubscriptionState.INACTIVE, reason_code="not_subscribed")},
        )

        evaluation = await resolve_admission_for_gate(
            session,
            None,
            config=_config(subscription=True, stage="registration"),
            resolver=resolver,
            stage=AdmissionStage.registration,
            auth_user_id=101,
        )

        assert resolver.calls[0]["auth_user_ids"] == [101]
        assert [v.key for v in evaluation.blockers] == ["subscription"]
        # No row means no lifecycle facts to read, so nothing was joined for.
        assert session.executes == 0

    async def test_a_known_subject_skips_the_join_even_when_a_row_exists(self):
        """A caller holding the acting user's id should not pay a query to be told it."""
        session = _Session()
        resolver = _Resolver()

        await resolve_admission_for_gate(
            session,
            _reg(1),
            config=_config(subscription=True, stage="check_in"),
            resolver=resolver,
            stage=AdmissionStage.check_in,
            auth_user_id=101,
        )

        assert session.executes == 0
        assert resolver.calls[0]["auth_user_ids"] == [101]

    async def test_neither_subject_is_a_programming_error(self):
        """Not a silent pass: answering ``undetermined`` for a call that named no
        subject is exactly how the regression above hid."""
        with self.assertRaises(ValueError):
            await resolve_admission_for_gate(
                _Session(),
                None,
                config=_config(subscription=True),
                resolver=_Resolver(),
                stage=AdmissionStage.registration,
            )


class StageScopedResolveTests(IsolatedAsyncioTestCase):
    """A rule that cannot bite at this gate must not be resolved at all.

    Not an optimisation. Resolving it would pay a forced provider call whose
    answer ``blocks_at`` then correctly discards, AND would write a
    ``source="registration"`` row into the subscription check log -- attributing a
    sign-up decision to a tournament that does not gate sign-up, in the very audit
    trail the plan lists as one of the readers of "when does this bite". The gate
    this layer replaced returned before any I/O for exactly this case.
    """

    async def test_a_check_in_staged_rule_is_untouched_during_sign_up(self):
        session = _Session()
        resolver = _Resolver(outcome=Outcome.REFUSED)

        evaluation = await resolve_admission_for_gate(
            session,
            None,
            config=_config(subscription=True, stage="check_in"),
            resolver=resolver,
            stage=AdmissionStage.registration,
            auth_user_id=101,
        )

        assert resolver.calls == []
        assert session.executes == 0
        assert evaluation.blockers == ()

    async def test_the_same_rule_is_resolved_at_check_in(self):
        """Non-vacuity: the skip above must be the stage, not a broken config."""
        session = _Session()
        resolver = _Resolver(outcome=Outcome.REFUSED)

        evaluation = await resolve_admission_for_gate(
            session,
            _reg(1),
            config=_config(subscription=True, stage="check_in"),
            resolver=resolver,
            stage=AdmissionStage.check_in,
            auth_user_id=101,
        )

        assert len(resolver.calls) == 1
        assert [v.key for v in evaluation.blockers] == ["subscription"]

    async def test_a_registration_staged_rule_is_resolved_at_both_gates(self):
        """``registration`` implies ``check_in``, so neither gate may skip it."""
        for stage in (AdmissionStage.registration, AdmissionStage.check_in):
            with self.subTest(stage=stage):
                resolver = _Resolver(outcome=Outcome.SATISFIED)
                await resolve_admission_for_gate(
                    _Session(),
                    _reg(1),
                    config=_config(subscription=True, stage="registration"),
                    resolver=resolver,
                    stage=stage,
                    auth_user_id=101,
                )
                assert len(resolver.calls) == 1

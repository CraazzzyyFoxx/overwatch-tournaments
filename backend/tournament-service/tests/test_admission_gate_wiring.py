"""What the handlers actually call: ``assert_admitted_at``, end to end but DB-free.

This suite replaces ``test_check_in_subscription_gate.py`` and
``test_registration_subscription_gate.py``. Their subject -- two hand-written
gate functions, one per requirement family -- no longer exists; the behaviours
they pinned do, and they are pinned here against the single gate:

- only a CONFIRMED refusal blocks (``undetermined`` fails open, at both stages),
- a malformed workspace rule does not block anybody,
- a check-in-only tournament costs nothing at sign-up: no rule read, no provider
  call, no check-log row,
- a sign-up refusal a challenge code could still fix is deferred,
- and the one the old arrangement could not express at all: a CLOSED PROFILE
  refuses check-in through the registry, not through an inline ``if`` in the RPC
  handler.

Composition itself is not re-tested here. ``shared.services.subscriptions``
owns the Kleene algebra, ``shared/tests/test_admission_evaluate.py`` owns the
decision table, and duplicating either would give three places to update and two
of them would rot.

No database: ``_common_service.get_registration_form`` and
``build_admission_resolver`` are the two seams ``admission.py`` reaches the world
through, and both are patched. The session is a stub that answers the one
``battle_tag_state`` read ``resolve_profiles_open`` issues.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.errors import BaseAPIException  # noqa: E402
from shared.services.admission import AdmissionStage, RequirementState  # noqa: E402
from shared.services.subscriptions import (  # noqa: E402
    SubscriptionRequirement,
    SubscriptionState,
    SubscriptionVerdict,
    evaluate_requirement,
)
from src.services.registration import admission  # noqa: E402
from tests._subscription_fakes import resolver_rule as _rule  # noqa: E402

BOOSTY_TIER_2 = {"mode": "all", "requirements": [{"provider": "boosty", "min_tier_rank": 2}]}
MALFORMED = {"mode": "most", "requirements": []}

TOURNAMENT = 55
USER = 42
REG_ID = 900


def _verdict(state: str, tier: int | None = None, *, reason: str | None = None) -> SubscriptionVerdict:
    """A provider verdict, with the ``evidence["reason"]`` the real providers write.

    Carrying the reason is not decoration. It is the entire i18n contract with the
    client (D13), and ``SubscriptionVerdict`` says in its own docstring that a
    non-active verdict without one is a provider bug. A fixture that omitted it
    would let the gate emit the ``"unknown"`` fallback code and still look green.
    """
    return SubscriptionVerdict(
        state=state,
        tier_rank=tier,
        tier_label=None,
        source="test",
        checked_at=datetime.now(UTC),
        expires_at=None,
        evidence={"reason": reason} if reason else {},
    )


ACTIVE_2 = _verdict(SubscriptionState.ACTIVE, 2)
INACTIVE = _verdict(SubscriptionState.INACTIVE, reason="not_subscribed")
#: An outage, which is the case that must never refuse anybody.
UNKNOWN = _verdict(SubscriptionState.UNKNOWN, reason="provider_unavailable")


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _Form:
    """Only what ``AdmissionConfig.from_form`` reads."""

    def __init__(
        self,
        *,
        require_open_profile: bool = False,
        open_profile_scope: str = "main",
        require_subscription: bool = False,
        subscription_stage: str = "check_in",
        blob: dict | None = None,
        workspace_id: int = 7,
    ) -> None:
        self.require_open_profile = require_open_profile
        self.open_profile_scope = open_profile_scope
        self.require_subscription = require_subscription
        self.subscription_stage = subscription_stage
        self.workspace_id = workspace_id
        #: The test's way of saying "this workspace requires X". The gate reads it
        #: through the resolver, never off the form.
        self.blob = blob or {}


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def tuples(self) -> _Rows:
        return self

    def scalars(self) -> _Rows:
        return self


class _Session:
    """Answers the battle-tag-state read and counts every statement issued.

    The count is asserted, not just the absence of a raise: a gate that resolves
    something it cannot act on still returns the right answer, and pays for it in
    production only.
    """

    def __init__(self, tag_statuses: dict[str, str] | None = None) -> None:
        self._tag_statuses = tag_statuses or {}
        self.statements = 0

    async def execute(self, _statement: Any, *_args: Any, **_kwargs: Any) -> _Rows:
        self.statements += 1
        return _Rows([(tag, status) for tag, status in self._tag_statuses.items()])


class _Resolver:
    """Real composition, faked I/O, and a log of both questions the gate can ask."""

    def __init__(
        self,
        verdicts: dict[str, SubscriptionVerdict] | None = None,
        *,
        code_providers: set[str] | None = None,
        rule: SubscriptionRequirement | None = None,
    ) -> None:
        self._verdicts = verdicts or {}
        self._code_providers = code_providers or set()
        self._rule = rule
        self.calls: list[dict] = []
        self.code_queries: list[tuple[int, tuple[str, ...]]] = []
        self.rule_reads: list[int] = []

    async def load_requirement(self, *, workspace_id: int) -> SubscriptionRequirement | None:
        self.rule_reads.append(workspace_id)
        return self._rule

    async def evaluate(
        self,
        *,
        workspace_id: int,
        auth_user_ids: Any,
        requirement: SubscriptionRequirement,
        force_refresh: bool = False,
        allow_stale: bool = False,
        source: str = "scheduled",
    ) -> dict[int, Any]:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "auth_user_ids": list(auth_user_ids),
                "providers": list(requirement.providers),
                "force_refresh": force_refresh,
                "source": source,
            }
        )
        outcome = evaluate_requirement(requirement, self._verdicts)
        return dict.fromkeys(auth_user_ids, (outcome, self._verdicts))

    async def accepted_code_providers(self, *, workspace_id: int, providers: Any) -> set[str]:
        self.code_queries.append((workspace_id, tuple(providers)))
        return self._code_providers


def _registration(*, battle_tag: str | None = None, smurfs: list[str] | None = None, checked_in: bool = False) -> Any:
    return SimpleNamespace(
        id=REG_ID,
        status="approved",
        balancer_status="ready",
        checked_in=checked_in,
        battle_tag=battle_tag,
        smurf_tags_json=smurfs,
    )


class _GateCase(IsolatedAsyncioTestCase):
    """Drives the real ``assert_admitted_at`` with both of its seams patched."""

    async def gate(
        self,
        form: _Form | None,
        *,
        stage: AdmissionStage,
        registration: Any | None = None,
        session: _Session | None = None,
        resolver: _Resolver | None = None,
    ) -> tuple[Any, _Resolver, _Session]:
        session = session or _Session()
        resolver = resolver or _Resolver()
        # The form's blob is the workspace rule, read through the resolver exactly
        # as production does -- including its fail-open parse.
        resolver._rule = _rule(getattr(form, "blob", None))

        with (
            mock.patch.object(admission, "_common_service") as forms,
            mock.patch.object(admission, "build_admission_resolver", return_value=resolver),
        ):
            forms.get_registration_form = mock.AsyncMock(return_value=form)
            evaluation = await admission.assert_admitted_at(
                session,
                registration,
                tournament_id=TOURNAMENT,
                auth_user_id=USER,
                stage=stage,
            )
        return evaluation, resolver, session


class TestClosedProfileRefusesCheckIn(_GateCase):
    """The consolidation, proven.

    This refusal used to be an inline ``if`` in ``_reg_pub_check_in`` that no
    other write path could reach and no serializer knew about. It is a registry
    entry now, so it arrives through the same gate, in the same 400 shape, with a
    machine code the client can translate.
    """

    async def test_private_profile_blocks(self):
        with self.assertRaises(BaseAPIException) as ctx:
            await self.gate(
                _Form(require_open_profile=True),
                stage=AdmissionStage.check_in,
                registration=_registration(battle_tag="Player#1"),
                session=_Session({"player#1": "private"}),
            )
        assert ctx.exception.status_code == 400

    async def test_refusal_carries_the_profile_reason_code(self):
        """Not a bare 400: the code is what the client renders in the user's
        language, having never computed the refusal itself."""
        with self.assertRaises(BaseAPIException) as ctx:
            await self.gate(
                _Form(require_open_profile=True),
                stage=AdmissionStage.check_in,
                registration=_registration(battle_tag="Player#1"),
                session=_Session({"player#1": "private"}),
            )
        assert [item["code"] for item in ctx.exception.detail] == ["profile_private"]

    async def test_public_profile_passes(self):
        """The control: same wiring, same read, opposite status."""
        evaluation, _resolver, _session = await self.gate(
            _Form(require_open_profile=True),
            stage=AdmissionStage.check_in,
            registration=_registration(battle_tag="Player#1"),
            session=_Session({"player#1": "ok"}),
        )
        assert evaluation.requirement("open_profile").state is RequirementState.satisfied

    async def test_unpolled_profile_fails_open(self):
        """Nobody has fetched the tag yet. A stalled parser must not empty a
        check-in."""
        evaluation, _resolver, _session = await self.gate(
            _Form(require_open_profile=True),
            stage=AdmissionStage.check_in,
            registration=_registration(battle_tag="Player#1"),
            session=_Session({}),
        )
        assert evaluation.requirement("open_profile").state is RequirementState.undetermined
        assert evaluation.blockers == ()

    async def test_profile_requirement_off_never_reads_battle_tag_state(self):
        _evaluation, _resolver, session = await self.gate(
            _Form(require_open_profile=False),
            stage=AdmissionStage.check_in,
            registration=_registration(battle_tag="Player#1"),
            session=_Session({"player#1": "private"}),
        )
        assert session.statements == 0

    async def test_closed_profile_does_not_block_sign_up(self):
        """D9: the profile requirement is staged at check-in, so a closed profile
        is visible at sign-up but not yet due. Encoded by the registry's stage,
        not by this handler omitting a call."""
        evaluation, _resolver, _session = await self.gate(
            _Form(require_open_profile=True),
            stage=AdmissionStage.registration,
            registration=_registration(battle_tag="Player#1"),
            session=_Session({"player#1": "private"}),
        )
        assert evaluation.requirement("open_profile").state is RequirementState.blocked
        assert evaluation.blockers == ()


class TestSubscriptionFailsOpenAtCheckIn(_GateCase):
    """Only a CONFIRMED refusal blocks -- the invariant whose regression cost is
    ejecting a paying subscriber from a live check-in."""

    async def test_undetermined_does_not_raise(self):
        evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2),
            stage=AdmissionStage.check_in,
            registration=_registration(),
            resolver=_Resolver({"boosty": UNKNOWN}),
        )
        assert evaluation.requirement("subscription").state is RequirementState.undetermined
        assert evaluation.blockers == ()
        # Non-vacuity: it really did resolve, and really did fail open.
        assert len(resolver.calls) == 1

    async def test_confirmed_refusal_does_raise(self):
        """The control for the case above: identical wiring, decided verdict."""
        with self.assertRaises(BaseAPIException) as ctx:
            await self.gate(
                _Form(require_subscription=True, blob=BOOSTY_TIER_2),
                stage=AdmissionStage.check_in,
                registration=_registration(),
                resolver=_Resolver({"boosty": INACTIVE}),
            )
        assert [item["code"] for item in ctx.exception.detail] == ["not_subscribed"]

    async def test_satisfied_passes(self):
        evaluation, _resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2),
            stage=AdmissionStage.check_in,
            registration=_registration(),
            resolver=_Resolver({"boosty": ACTIVE_2}),
        )
        assert evaluation.requirement("subscription").state is RequirementState.satisfied

    async def test_check_in_forces_a_fresh_look_and_labels_it(self):
        """A stale ``active`` must not be trusted at the moment of decision, and
        the check-log row must name the trigger."""
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2),
            stage=AdmissionStage.check_in,
            registration=_registration(),
            resolver=_Resolver({"boosty": ACTIVE_2}),
        )
        assert resolver.calls[0]["force_refresh"] is True
        assert resolver.calls[0]["source"] == "check_in"
        assert resolver.calls[0]["auth_user_ids"] == [USER]


class TestNothingToEnforce(_GateCase):
    async def test_no_form_asks_nothing(self):
        _evaluation, resolver, session = await self.gate(
            None,
            stage=AdmissionStage.check_in,
            registration=_registration(battle_tag="Player#1"),
            session=_Session({"player#1": "private"}),
        )
        assert resolver.rule_reads == []
        assert resolver.calls == []
        assert session.statements == 0

    async def test_toggle_off_never_reads_the_rule(self):
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=False, blob=BOOSTY_TIER_2),
            stage=AdmissionStage.check_in,
            registration=_registration(),
        )
        assert resolver.rule_reads == []
        assert resolver.calls == []

    async def test_malformed_rule_does_not_block(self):
        """A bad ``mode`` is rejected on save; if one slipped in anyway, refusing
        every patron mid-tournament would be the worse failure. The resolver owns
        the fail-open parse, so the rule collapses to ``None`` and the armed
        toggle disarms itself."""
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=MALFORMED),
            stage=AdmissionStage.check_in,
            registration=_registration(),
            resolver=_Resolver({"boosty": INACTIVE}),
        )
        assert resolver.rule_reads == [7]
        assert resolver.calls == []

    async def test_empty_rule_does_not_block(self):
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob={}),
            stage=AdmissionStage.check_in,
            registration=_registration(),
            resolver=_Resolver({"boosty": INACTIVE}),
        )
        assert resolver.calls == []


class TestCheckInOnlyTournamentCostsNothingAtSignUp(_GateCase):
    """The opt-in, asserted with the call log rather than the absence of a raise.

    A ``check_in``-staged tournament must not even ASK at sign-up. Every sign-up
    would otherwise pay a live ``force_refresh`` provider call to compute an
    answer ``blocks_at`` immediately discards -- and would write a check-log row
    attributed to a sign-up decision the tournament does not gate, corrupting the
    one audit trail that records when a requirement actually bit.
    """

    async def test_no_provider_call_at_sign_up(self):
        _evaluation, resolver, session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="check_in"),
            stage=AdmissionStage.registration,
            resolver=_Resolver({"boosty": INACTIVE}),
        )
        assert resolver.calls == []
        assert resolver.code_queries == []
        # No auth-user join either, and -- because the check log is written inside
        # `resolver.evaluate` -- no `source="registration"` row for a decision this
        # tournament does not gate.
        assert session.statements == 0

    async def test_registration_staged_form_does_ask(self):
        """The control: identical input, only the stage differs."""
        with self.assertRaises(BaseAPIException):
            await self.gate(
                _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="registration"),
                stage=AdmissionStage.registration,
                resolver=_Resolver({"boosty": INACTIVE}),
            )

    async def test_an_unrecognised_stage_is_check_in(self):
        """Fail LOOSER: an unknown stage is a config or migration error, and a
        typo must not start refusing sign-ups nobody asked it to refuse."""
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="Registration"),
            stage=AdmissionStage.registration,
            resolver=_Resolver({"boosty": INACTIVE}),
        )
        assert resolver.calls == []

    async def test_a_form_predating_the_column_is_check_in(self):
        form = _Form(require_subscription=True, blob=BOOSTY_TIER_2)
        del form.subscription_stage
        _evaluation, resolver, _session = await self.gate(
            form,
            stage=AdmissionStage.registration,
            resolver=_Resolver({"boosty": INACTIVE}),
        )
        assert resolver.calls == []


class TestSignUpDeferral(_GateCase):
    """A refusal the patron could still fix by pasting a code is not final.

    The phrase field is offered at check-in and nowhere else, so refusing someone
    one paste away from admission would be a lie about their standing.
    """

    async def test_refusal_on_a_code_provider_is_deferred(self):
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="registration"),
            stage=AdmissionStage.registration,
            resolver=_Resolver({"boosty": INACTIVE}, code_providers={"boosty"}),
        )
        assert resolver.code_queries == [(7, ("boosty",))]

    async def test_deferral_does_not_apply_without_a_code_path(self):
        resolver = _Resolver({"boosty": INACTIVE}, code_providers=set())
        with self.assertRaises(BaseAPIException) as ctx:
            await self.gate(
                _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="registration"),
                stage=AdmissionStage.registration,
                resolver=resolver,
            )
        # Asked, answered "no code path", refused -- naming sign-up, not check-in.
        assert resolver.code_queries == [(7, ("boosty",))]
        assert "регистрации" in ctx.exception.detail[0]["msg"]

    async def test_no_code_query_when_nothing_is_refused(self):
        """Deferring can only ever WEAKEN a refusal, so the happy path skips it."""
        _evaluation, resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="registration"),
            stage=AdmissionStage.registration,
            resolver=_Resolver({"boosty": ACTIVE_2}, code_providers={"boosty"}),
        )
        assert resolver.code_queries == []

    async def test_check_in_never_defers(self):
        """The field is right there by then, so every refusal is final."""
        resolver = _Resolver({"boosty": INACTIVE}, code_providers={"boosty"})
        with self.assertRaises(BaseAPIException):
            await self.gate(
                _Form(require_subscription=True, blob=BOOSTY_TIER_2),
                stage=AdmissionStage.check_in,
                registration=_registration(),
                resolver=resolver,
            )
        assert resolver.code_queries == []


class TestSignUpReadsBlockersNotDecision(_GateCase):
    """A prospective registrant has no row, so no lifecycle facts.

    ``ready`` is therefore false and ``decision`` is ``not_admitted`` for a
    perfectly acceptable applicant. The gate must refuse on ``blockers`` alone;
    gating on ``decision`` would reject every sign-up in the product.
    """

    async def test_clean_sign_up_passes_despite_not_admitted(self):
        evaluation, _resolver, _session = await self.gate(
            _Form(require_subscription=True, blob=BOOSTY_TIER_2, subscription_stage="registration"),
            stage=AdmissionStage.registration,
            resolver=_Resolver({"boosty": ACTIVE_2}),
        )
        assert evaluation.blockers == ()
        assert evaluation.ready is False
        assert evaluation.admitted is False


class TestForcedCheckInIsAnOverride(_GateCase):
    """D2/D4: the payoff of the whole layer.

    An organizer checked a player in by hand through the admin path, which has no
    gate on purpose. The public gate must not then re-refuse them, and the blocked
    requirement must remain VISIBLE in ``overridden`` rather than vanish.
    """

    async def test_checked_in_registration_is_not_re_refused(self):
        evaluation, _resolver, _session = await self.gate(
            _Form(require_open_profile=True),
            stage=AdmissionStage.check_in,
            registration=_registration(battle_tag="Player#1", checked_in=True),
            session=_Session({"player#1": "private"}),
        )
        assert evaluation.blockers == ()
        assert [verdict.key for verdict in evaluation.overridden] == ["open_profile"]
        assert evaluation.admitted is True

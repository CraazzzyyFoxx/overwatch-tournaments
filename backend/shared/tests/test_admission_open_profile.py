"""The profile-open resolver and its requirement evaluator.

Three claims, and they are separate on purpose.

**The resolver stopped losing the reason.** ``resolve_profiles_open`` used to
collapse seven ``RankCollectionStatus`` values plus "no BattleTag at all" into
``bool | None``, so a ``None`` could not be told apart from another ``None``.
Every row of that mapping is pinned here, because a wrong code sends the
organizer after the wrong person -- ``collection_disabled`` is his own switch,
``profile_private`` is the player's, ``collection_failed`` is nobody's. The
``subject`` assertions matter for the same reason: under ``scope="all"`` a
registrant may carry three tags with exactly one closed, and a reason that does
not name the closed one is not actionable.

**The precedence did not move.** The reason had to be produced inside the loop
that decides the verdict, so the body was rewritten rather than wrapped -- the
one place in this change where a rule could shift unnoticed.
:class:`PrecedenceIsUnchanged` restates the old rule independently and runs both
over every combination of up to three tags.

**The evaluator fails open.** ``False`` and ``None`` are the two values whose
meanings are opposite -- refuse the player, and do not -- yet both are falsy.
:meth:`EvalOpenProfile.test_absent_signal_is_undetermined_not_blocked` and its
``None``-verdict sibling are named after that, because the cost of getting it
wrong is refusing a paying registrant during a live check-in over a parser that
simply had not run yet.

No database: the batched ``SELECT`` is faked at the session boundary, matching
the convention in shared/tests/test_finalize_encounter_score.py. Runs under
stdlib unittest -- there is no pytest-asyncio here.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.core.enums import RankCollectionStatus  # noqa: E402
from shared.services.admission.config import AdmissionConfig  # noqa: E402
from shared.services.admission.requirements.open_profile import KEY, eval_open_profile  # noqa: E402
from shared.services.admission.signals import AdmissionSignals, ProfileSignal  # noqa: E402
from shared.services.admission.types import (  # noqa: E402
    AdmissionReason,
    AdmissionStage,
    ReasonActor,
    RequirementState,
)
from shared.services.profile_visibility import resolve_profiles_open  # noqa: E402

MAIN = "Player#2100"
SMURF_A = "Smurf#1111"
SMURF_B = "Smurf#2222"


class _Rows:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _Session:
    """Just enough ``AsyncSession`` for the one batched ``battle_tag_state`` read.

    Counts ``execute`` calls so the batching contract stays asserted: one pass per
    list, never one per registration.
    """

    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        # Stored verbatim; the resolver is responsible for the case folding, and
        # seeding a pre-lowered map here would test the test instead.
        self._statuses = statuses or {}
        self.executes = 0

    async def execute(self, _statement: Any) -> _Rows:
        self.executes += 1
        return _Rows(list(self._statuses.items()))


def _reg(reg_id: int, battle_tag: str | None, smurfs: list[str] | None = None) -> SimpleNamespace:
    """A registration double: its battlenet handles, primary first."""
    tags = [tag for tag in (battle_tag, *(smurfs or ())) if tag]
    return SimpleNamespace(id=reg_id, handles=lambda _provider: list(tags))


def _codes(signal: ProfileSignal) -> set[tuple[str, str | None]]:
    return {(r.code, r.subject) for r in signal.reasons}


class ResolveProfilesOpen(IsolatedAsyncioTestCase):
    async def _one(self, status: str | None, *, scope: str = "main") -> ProfileSignal:
        session = _Session({MAIN: status} if status is not None else {})
        result = await resolve_profiles_open(session, [_reg(1, MAIN)], scope=scope)
        assert session.executes == 1, "the read must be batched into one statement"
        return result[1]

    # ── the status -> (verdict, code) table ──────────────────────────────────

    async def test_ok_is_open_and_silent(self):
        """A public profile is the one verdict that carries no reasons."""
        signal = await self._one(RankCollectionStatus.ok.value)
        assert signal == ProfileSignal(is_open=True, reasons=())

    async def test_private_blocks_naming_the_tag(self):
        signal = await self._one(RankCollectionStatus.private.value)
        assert signal.is_open is False
        assert _codes(signal) == {("profile_private", MAIN)}

    async def test_not_found_blocks_naming_the_tag(self):
        signal = await self._one(RankCollectionStatus.not_found.value)
        assert signal.is_open is False
        assert _codes(signal) == {("profile_not_found", MAIN)}

    async def test_missing_row_is_never_fetched(self):
        """No ``battle_tag_state`` row at all -- nobody has polled this tag."""
        signal = await self._one(None)
        assert signal.is_open is None
        assert _codes(signal) == {("never_fetched", MAIN)}

    async def test_pending_is_collection_pending(self):
        signal = await self._one(RankCollectionStatus.pending.value)
        assert signal.is_open is None
        assert _codes(signal) == {("collection_pending", MAIN)}

    async def test_error_is_collection_failed(self):
        signal = await self._one(RankCollectionStatus.error.value)
        assert signal.is_open is None
        assert _codes(signal) == {("collection_failed", MAIN)}

    async def test_rate_limited_is_collection_failed(self):
        """``rate_limited`` folds into ``collection_failed``: same actor, same fix."""
        signal = await self._one(RankCollectionStatus.rate_limited.value)
        assert signal.is_open is None
        assert _codes(signal) == {("collection_failed", MAIN)}

    async def test_disabled_is_collection_disabled(self):
        signal = await self._one(RankCollectionStatus.disabled.value)
        assert signal.is_open is None
        assert _codes(signal) == {("collection_disabled", MAIN)}

    async def test_every_status_is_covered(self):
        """No ``RankCollectionStatus`` may resolve to the ``"unknown"`` code.

        A value added to the enum without a code here would silently degrade to
        ``system``/``unknown``, which is safe (it still fails open) but mute -- the
        organizer would be told a tag is unresolved and nothing else.
        """
        for status in RankCollectionStatus:
            signal = await self._one(status.value)
            assert "unknown" not in {r.code for r in signal.reasons}, status

    async def test_actor_is_carried_on_every_reason(self):
        """The actor is the point of the taxonomy: who chases whom."""
        assert (await self._one(RankCollectionStatus.private.value)).reasons[0].actor is ReasonActor.player
        assert (await self._one(RankCollectionStatus.disabled.value)).reasons[0].actor is ReasonActor.organizer
        assert (await self._one(RankCollectionStatus.error.value)).reasons[0].actor is ReasonActor.system

    # ── no tag to check ──────────────────────────────────────────────────────

    async def test_no_battle_tag_at_all(self):
        """An empty ``battle_tag`` is the player's to fill in, and skips the query."""
        session = _Session()
        result = await resolve_profiles_open(session, [_reg(1, None)], scope="main")
        assert session.executes == 0, "nothing to look up must not cost a round trip"
        assert result[1].is_open is None
        assert result[1].reasons == (AdmissionReason(code="no_battle_tag", actor=ReasonActor.player, subject=None),)

    async def test_no_battle_tag_beside_a_tagged_registration(self):
        """The tag-less row still answers ``no_battle_tag`` when the batch does query."""
        session = _Session({MAIN: RankCollectionStatus.ok.value})
        result = await resolve_profiles_open(session, [_reg(1, MAIN), _reg(2, None)], scope="main")
        assert session.executes == 1
        assert result[1].is_open is True
        assert _codes(result[2]) == {("no_battle_tag", None)}

    async def test_smurfs_ignored_under_main_scope(self):
        """``scope="main"`` must not let a closed smurf refuse the registrant."""
        session = _Session({MAIN: RankCollectionStatus.ok.value, SMURF_A: RankCollectionStatus.private.value})
        result = await resolve_profiles_open(session, [_reg(1, MAIN, [SMURF_A])], scope="main")
        assert result[1] == ProfileSignal(is_open=True, reasons=())

    # ── scope="all" ──────────────────────────────────────────────────────────

    async def test_all_scope_requires_every_tag_open(self):
        session = _Session(
            {
                MAIN: RankCollectionStatus.ok.value,
                SMURF_A: RankCollectionStatus.ok.value,
                SMURF_B: RankCollectionStatus.ok.value,
            }
        )
        result = await resolve_profiles_open(session, [_reg(1, MAIN, [SMURF_A, SMURF_B])], scope="all")
        assert result[1] == ProfileSignal(is_open=True, reasons=())

    async def test_one_closed_smurf_among_three_names_the_closed_tag(self):
        """The reason has to point at the smurf, not at the registration.

        This is the case ``subject`` exists for: two tags are fine, one is private,
        and a bare ``False`` would leave the organizer with three tags to guess
        between.
        """
        session = _Session(
            {
                MAIN: RankCollectionStatus.ok.value,
                SMURF_A: RankCollectionStatus.ok.value,
                SMURF_B: RankCollectionStatus.private.value,
            }
        )
        result = await resolve_profiles_open(session, [_reg(1, MAIN, [SMURF_A, SMURF_B])], scope="all")
        assert result[1].is_open is False
        assert _codes(result[1]) == {("profile_private", SMURF_B)}

    async def test_closed_wins_over_unresolved_and_suppresses_it(self):
        """Precedence is unchanged: any closed tag => ``False``, pending or not.

        The pending tag is deliberately NOT reported beside it -- ``False`` is the
        actionable verdict and burying it under "also still fetching" helps nobody.
        """
        session = _Session({MAIN: RankCollectionStatus.pending.value, SMURF_A: RankCollectionStatus.not_found.value})
        result = await resolve_profiles_open(session, [_reg(1, MAIN, [SMURF_A])], scope="all")
        assert result[1].is_open is False
        assert _codes(result[1]) == {("profile_not_found", SMURF_A)}

    async def test_unresolved_tags_are_all_reported(self):
        """An ``ok`` tag beside two unresolved ones yields exactly two reasons."""
        session = _Session({MAIN: RankCollectionStatus.ok.value, SMURF_A: RankCollectionStatus.pending.value})
        result = await resolve_profiles_open(session, [_reg(1, MAIN, [SMURF_A, SMURF_B])], scope="all")
        assert result[1].is_open is None
        assert _codes(result[1]) == {("collection_pending", SMURF_A), ("never_fetched", SMURF_B)}

    async def test_empty_smurf_entries_are_skipped(self):
        session = _Session({MAIN: RankCollectionStatus.ok.value})
        result = await resolve_profiles_open(session, [_reg(1, MAIN, ["", None])], scope="all")
        assert result[1] == ProfileSignal(is_open=True, reasons=())

    async def test_null_smurf_json_is_tolerated(self):
        session = _Session({MAIN: RankCollectionStatus.ok.value})
        result = await resolve_profiles_open(session, [_reg(1, MAIN, None)], scope="all")
        assert result[1] == ProfileSignal(is_open=True, reasons=())

    # ── case folding ─────────────────────────────────────────────────────────

    async def test_tag_matching_is_case_insensitive(self):
        """The stored row's casing must not decide admission.

        BattleTags round-trip through Blizzard and the registration form with
        inconsistent casing; the SQL folds with ``lower()`` and the Python side has
        to fold the same way or a public profile reads as never fetched.
        """
        session = _Session({"pLaYeR#2100": RankCollectionStatus.ok.value})
        result = await resolve_profiles_open(session, [_reg(1, "PLAYER#2100")], scope="main")
        assert result[1] == ProfileSignal(is_open=True, reasons=())

    async def test_reason_subject_keeps_the_registration_casing(self):
        """``subject`` echoes the tag as REGISTERED -- that is what the organizer sees."""
        session = _Session({"player#2100": RankCollectionStatus.private.value})
        result = await resolve_profiles_open(session, [_reg(1, "Player#2100")], scope="main")
        assert _codes(result[1]) == {("profile_private", "Player#2100")}

    # ── batching ─────────────────────────────────────────────────────────────

    async def test_whole_list_costs_one_statement(self):
        session = _Session({MAIN: RankCollectionStatus.ok.value})
        regs = [_reg(i, f"Player#{i}") for i in range(1, 21)]
        result = await resolve_profiles_open(session, regs, scope="main")
        assert session.executes == 1
        assert len(result) == 20


class PrecedenceIsUnchanged(IsolatedAsyncioTestCase):
    """The rewrite must not move a single tri-state answer.

    The reason had to be produced inside the loop that decides the verdict, so the
    body was rewritten rather than wrapped -- and a rewrite is exactly where a
    precedence rule quietly shifts. The old rule is restated here independently,
    from the enum rather than from the module's own constants, so the two cannot
    agree by construction, and both are run over every combination of one, two and
    three tags across "no row" plus all seven statuses.

    Same technique as test_registration_window.py: when a body is replaced, pin it
    against a Python reimplementation of what it replaced.
    """

    #: Restated, not imported. These two are the only BLOCKING statuses.
    CLOSED = frozenset({RankCollectionStatus.private.value, RankCollectionStatus.not_found.value})
    #: ``None`` stands for "no ``battle_tag_state`` row for this tag".
    VALUES = (None, *(status.value for status in RankCollectionStatus))

    @classmethod
    def _old_verdict(cls, statuses: tuple[str | None, ...]) -> bool | None:
        """The pre-rewrite rule: closed wins, then all-ok, else unknown."""
        if any(status in cls.CLOSED for status in statuses):
            return False
        if all(status == RankCollectionStatus.ok.value for status in statuses):
            return True
        return None

    async def test_tri_state_matches_the_old_body(self):
        ok = RankCollectionStatus.ok.value
        checked = 0
        for width in (1, 2, 3):
            for combo in itertools.product(self.VALUES, repeat=width):
                tags = [f"Tag{index}#{index}" for index in range(width)]
                session = _Session({tag: st for tag, st in zip(tags, combo, strict=True) if st is not None})
                signal = (await resolve_profiles_open(session, [_reg(1, tags[0], tags[1:])], scope="all"))[1]
                expected = self._old_verdict(combo)
                assert signal.is_open is expected, combo
                # One reason per tag the verdict is actually about: the closed ones
                # when closed, the unresolved ones when unknown, none when open.
                if expected is False:
                    wanted = sum(1 for status in combo if status in self.CLOSED)
                elif expected is None:
                    wanted = sum(1 for status in combo if status != ok)
                else:
                    wanted = 0
                assert len(signal.reasons) == wanted, combo
                assert all(r.subject in tags for r in signal.reasons), combo
                checked += 1
        assert checked == sum(len(self.VALUES) ** width for width in (1, 2, 3))


CONFIG_MAIN = AdmissionConfig(require_open_profile=True, open_profile_scope="main")
CONFIG_ALL = AdmissionConfig(require_open_profile=True, open_profile_scope="all")

STAGES = (AdmissionStage.registration, AdmissionStage.check_in)


def _signals(profile: ProfileSignal | None) -> AdmissionSignals:
    return AdmissionSignals(
        registration_id=1,
        status="approved",
        balancer_status="ready",
        checked_in=False,
        profile=profile,
    )


PRIVATE = AdmissionReason(code="profile_private", actor=ReasonActor.player, subject=MAIN)
PENDING = AdmissionReason(code="collection_pending", actor=ReasonActor.system, subject=MAIN)


class EvalOpenProfile(TestCase):
    def test_absent_signal_is_undetermined_not_blocked(self):
        """A ``None`` signal means NOT ASKED, and must never read as a failure.

        The resolver skips this requirement entirely when the tournament has it
        switched off, or when the registration was not in the batch. Reading that
        absence as ``blocked`` would refuse every player in a tournament that never
        required an open profile in the first place.
        """
        for stage in STAGES:
            verdict = eval_open_profile(CONFIG_MAIN, _signals(None), stage)
            assert verdict.state is RequirementState.undetermined, stage
            assert verdict.blocks is False, stage
            assert verdict.reasons == (), "an unasked requirement has nothing to explain"
            assert verdict.detail == {}, "no signal, no chip to render"

    def test_unknown_verdict_is_undetermined_not_blocked(self):
        """An unfetched or errored collection must never un-admit anybody.

        This is the fail-open invariant at its sharpest: ``is_open is None`` and
        ``is_open is False`` are both falsy, so any truthiness test here silently
        turns a stalled parser into a mass refusal at check-in.
        """
        for stage in STAGES:
            verdict = eval_open_profile(CONFIG_MAIN, _signals(ProfileSignal(None, (PENDING,))), stage)
            assert verdict.state is RequirementState.undetermined, stage
            assert verdict.blocks is False, stage
            assert verdict.reasons == (PENDING,), "the why is carried through even when it passes"

    def test_closed_profile_blocks_and_carries_its_reasons(self):
        for stage in STAGES:
            verdict = eval_open_profile(CONFIG_MAIN, _signals(ProfileSignal(False, (PRIVATE,))), stage)
            assert verdict.state is RequirementState.blocked, stage
            assert verdict.blocks is True, stage
            assert verdict.reasons == (PRIVATE,)

    def test_open_profile_is_satisfied_and_silent(self):
        for stage in STAGES:
            verdict = eval_open_profile(CONFIG_MAIN, _signals(ProfileSignal(True)), stage)
            assert verdict.state is RequirementState.satisfied, stage
            assert verdict.blocks is False, stage
            assert verdict.reasons == ()

    def test_satisfied_drops_reasons_even_if_the_signal_carries_them(self):
        """A green row must not render a complaint. Enforced, not trusted."""
        verdict = eval_open_profile(CONFIG_MAIN, _signals(ProfileSignal(True, (PENDING,))), AdmissionStage.check_in)
        assert verdict.state is RequirementState.satisfied
        assert verdict.reasons == ()

    def test_verdict_reports_the_stage_it_was_handed(self):
        """The stage is a parameter, not a position in a handler (D8)."""
        for stage in STAGES:
            assert eval_open_profile(CONFIG_MAIN, _signals(ProfileSignal(True)), stage).stage is stage

    def test_key_is_stable(self):
        assert KEY == "open_profile"
        assert eval_open_profile(CONFIG_MAIN, _signals(None), AdmissionStage.check_in).key == KEY

    def test_detail_exposes_scope_and_verdict_for_the_chips(self):
        for config, scope in ((CONFIG_MAIN, "main"), (CONFIG_ALL, "all")):
            for is_open in (True, False, None):
                verdict = eval_open_profile(config, _signals(ProfileSignal(is_open)), AdmissionStage.check_in)
                assert verdict.detail == {"scope": scope, "profiles_open": is_open}

"""Compose per-provider subscription verdicts into one admission answer.

A tournament may require a subscription on one provider, on ALL of several, or on
ANY ONE of several, each with its own ``min_tier_rank`` (Boosty "Уровень 2" and
Twitch "Tier 2" are unrelated scales).

Composition uses **Kleene three-valued logic**, NOT boolean logic with ``unknown``
coerced to a side. Coercing ``unknown`` to false would make ``any[refused,
unknown]`` block, so one provider's outage would lock out every patron subscribed
via the other. Coercing it to true would make ``all[refused, unknown]`` pass,
admitting a confirmed non-subscriber. Kleene is the only mapping that preserves
"block only on certainty" in both modes.

The gate blocks IFF the composed outcome is ``REFUSED``. One ``unknown`` is not
like another, though: an organizer's misconfiguration (no guild, no tier
mapping, a drifted role) is their problem and fails open, while an *outage* --
discord-service or Twitch did not answer -- fails closed: a paid tier that could
not be checked is not confirmed (:data:`OUTAGE_REASONS`). ``deferred_providers``
exists for the one gate that runs *before* the patron has been offered every
proof path — see ``evaluate_requirement``.
"""

from __future__ import annotations

import enum
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from shared.services.subscriptions.types import SubscriptionState, SubscriptionVerdict, meets_min_tier

__all__ = (
    "MODE_ALL",
    "MODE_ANY",
    "OUTAGE_REASONS",
    "Outcome",
    "ProviderRequirement",
    "SubscriptionRequirement",
    "evaluate_requirement",
    "parse_requirement",
)

MODE_ALL: Final = "all"
MODE_ANY: Final = "any"
_MODES: Final = frozenset({MODE_ALL, MODE_ANY})

#: ``unknown`` verdict reasons that mean "could not ask", not "nothing to ask
#: about". The provider resolvers file these when their transport fails
#: (``provider_unavailable``) or was never wired (``bot_not_configured``).
OUTAGE_REASONS: Final = frozenset({"provider_unavailable", "bot_not_configured"})


class Outcome(enum.Enum):
    """Kleene truth value of a composed requirement."""

    SATISFIED = "satisfied"  # T
    REFUSED = "refused"  # F
    UNDETERMINED = "undetermined"  # U

    @property
    def blocks_admission(self) -> bool:
        """Only certainty of failure blocks. ``UNDETERMINED`` fails open."""
        return self is Outcome.REFUSED


@dataclass(frozen=True, slots=True)
class ProviderRequirement:
    provider: str
    min_tier_rank: int = 1


@dataclass(frozen=True, slots=True)
class SubscriptionRequirement:
    mode: Literal["any", "all"]
    requirements: tuple[ProviderRequirement, ...]

    @property
    def providers(self) -> tuple[str, ...]:
        """Distinct providers this requirement needs resolved.

        ``parse_requirement`` already deduplicates, so this is distinct by
        construction.
        """
        return tuple(req.provider for req in self.requirements)


def _evaluate_one(req: ProviderRequirement, verdict: SubscriptionVerdict | None, *, deferred: bool) -> Outcome:
    # No verdict at all: the provider is unconfigured, disabled, or was not
    # resolved. That is the organizer's problem, never read as "not subscribed".
    if verdict is None:
        return Outcome.UNDETERMINED
    if verdict.state == SubscriptionState.UNKNOWN:
        # An outage is the one ``unknown`` that refuses: the patron may well be
        # subscribed, but nothing confirmed it, and a gate that admits everyone
        # while the checker is down is no gate. Deferral still applies -- a
        # code pasted at check-in proves the tier without the provider.
        if verdict.evidence.get("reason") in OUTAGE_REASONS:
            return Outcome.UNDETERMINED if deferred else Outcome.REFUSED
        return Outcome.UNDETERMINED
    # meets_min_tier also fails open on unknown, which is already handled above;
    # here it is a pure active/threshold comparison.
    if meets_min_tier(verdict, min_tier_rank=req.min_tier_rank):
        return Outcome.SATISFIED
    # The provider says no, but the patron still holds an unused way to say yes.
    # Not knowing yet is the honest answer, and it is the same UNDETERMINED the
    # rest of this module already fails open on.
    return Outcome.UNDETERMINED if deferred else Outcome.REFUSED


def evaluate_requirement(
    requirement: SubscriptionRequirement,
    verdicts: Mapping[str, SubscriptionVerdict],
    *,
    deferred_providers: Collection[str] = (),
) -> Outcome:
    """Compose ``requirement`` over ``verdicts`` keyed by provider.

    Commutative and associative in both modes: provider order in config is
    arbitrary and must not change the answer.

    ``deferred_providers`` names providers whose remaining proof — a challenge
    code the patron has not been asked for yet — is still outstanding, so their
    refusal is not yet final. Registration submit passes the code-accepting
    providers here because the phrase field only exists at check-in: refusing
    someone one paste away from admission would be wrong, and under ``any`` it
    would refuse a rule they can still satisfy. Check-in passes nothing — the
    field is right there, so every refusal is final.
    """
    if not requirement.requirements:
        return Outcome.SATISFIED

    outcomes = [
        _evaluate_one(req, verdicts.get(req.provider), deferred=req.provider in deferred_providers)
        for req in requirement.requirements
    ]

    if requirement.mode == MODE_ALL:
        # Kleene AND: F dominates, then U.
        if any(outcome is Outcome.REFUSED for outcome in outcomes):
            return Outcome.REFUSED
        if any(outcome is Outcome.UNDETERMINED for outcome in outcomes):
            return Outcome.UNDETERMINED
        return Outcome.SATISFIED

    # Kleene OR: T dominates, then U.
    if any(outcome is Outcome.SATISFIED for outcome in outcomes):
        return Outcome.SATISFIED
    if any(outcome is Outcome.UNDETERMINED for outcome in outcomes):
        return Outcome.UNDETERMINED
    return Outcome.REFUSED


def parse_requirement(blob: dict[str, Any] | None) -> SubscriptionRequirement:
    """Read a ``{mode, requirements}`` rule blob into a validated requirement.

    Malformed rows are skipped rather than raising: a bad config row must not 500
    the check-in endpoint. An unknown ``mode``, however, IS an error — silently
    picking a mode would change the admission rule.
    """
    blob = blob or {}
    mode = str(blob.get("mode") or MODE_ALL)
    if mode not in _MODES:
        raise ValueError(f"Unsupported subscription requirement mode: {mode!r}")

    # Deduplicate by provider, keeping the strictest threshold, so a duplicated
    # config row cannot accidentally loosen the rule.
    strictest: dict[str, int] = {}
    for row in blob.get("requirements") or []:
        provider = str(row.get("provider") or "").strip()
        if not provider:
            continue
        try:
            min_tier_rank = int(row.get("min_tier_rank", 1))
        except TypeError, ValueError:
            min_tier_rank = 1
        min_tier_rank = max(min_tier_rank, 1)
        strictest[provider] = max(strictest.get(provider, 0), min_tier_rank)

    return SubscriptionRequirement(
        mode=mode,  # type: ignore[arg-type]
        requirements=tuple(
            ProviderRequirement(provider=provider, min_tier_rank=min_tier_rank)
            for provider, min_tier_rank in strictest.items()
        ),
    )

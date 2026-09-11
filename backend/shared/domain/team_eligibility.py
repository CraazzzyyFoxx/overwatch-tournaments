"""Pure team-eligibility rules for registration-mode tournaments.

I/O (roster ranks, Discord membership, identity collisions) lives in the service
that calls this. This module only answers "given these facts, what is wrong".

Rank rules apply to **starters only**. A substitute holds no slot in the
``RosterShape``, so folding them into min/max/spread would refuse a bench
player the captain never claimed as part of the fielded five.

``team_unique_identity`` and ``team_require_discord_guild`` are also evaluated
here once the caller has already resolved the signals: uniqueness is a set of
already-normalized keys, guild membership is a per-player tri-state the loader
already decided. The Discord API hop, if any, does not belong in this file.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = (
    "EligibilityIssue",
    "StarterRank",
    "evaluate_discord_guild",
    "evaluate_rank_rules",
    "evaluate_unique_identity",
)


@dataclass(frozen=True, slots=True)
class EligibilityIssue:
    """One machine-readable finding. ``blocking`` is the export/accept gate."""

    code: str
    registration_id: int | None = None
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class StarterRank:
    registration_id: int
    #: ``None`` when the roster engine could not rate the occupied slot.
    rank: int | None


def evaluate_rank_rules(
    starters: Sequence[StarterRank],
    *,
    rank_min: int | None,
    rank_max: int | None,
    max_spread: int | None,
) -> list[EligibilityIssue]:
    """Min/max/spread over starter ranks. Unrated starters fail min/max, not spread.

    Spread ignores ``None`` so a missing rank does not invent a 0-SR floor that
    every real rating then fails. The missing rank is reported separately as
    ``team_rank_unrated`` when a min or max is configured, because that is the
    case where "we do not know" cannot pass a numeric gate.
    """
    issues: list[EligibilityIssue] = []
    rated = [entry for entry in starters if entry.rank is not None]
    for entry in starters:
        if entry.rank is None:
            if rank_min is not None or rank_max is not None:
                issues.append(EligibilityIssue(code="team_rank_unrated", registration_id=entry.registration_id))
            continue
        if rank_min is not None and entry.rank < rank_min:
            issues.append(EligibilityIssue(code="team_rank_too_low", registration_id=entry.registration_id))
        if rank_max is not None and entry.rank > rank_max:
            issues.append(EligibilityIssue(code="team_rank_too_high", registration_id=entry.registration_id))
    if max_spread is not None and len(rated) >= 2:
        spread = max(entry.rank or 0 for entry in rated) - min(entry.rank or 0 for entry in rated)
        if spread > max_spread:
            issues.append(EligibilityIssue(code="team_rank_spread"))
    return issues


def evaluate_unique_identity(
    *,
    this_keys: Mapping[int, set[str]],
    taken_keys: Iterable[str],
) -> list[EligibilityIssue]:
    """``this_keys`` is ``{registration_id: {normalized identity, ...}}``.

    A key already present on another live team in the tournament is a collision.
    Within-team duplicates are the registration unique indexes' job and are not
    re-checked here.
    """
    occupied = set(taken_keys)
    issues: list[EligibilityIssue] = []
    seen: set[str] = set()
    for registration_id, keys in this_keys.items():
        for key in keys:
            if not key:
                continue
            if key in occupied or key in seen:
                issues.append(EligibilityIssue(code="team_identity_taken", registration_id=registration_id))
                break
        seen.update(k for k in keys if k)
    return issues


def evaluate_discord_guild(
    members: Mapping[int, str | None],
    *,
    guild_id: str | None,
    require: bool,
) -> list[EligibilityIssue]:
    """``members`` maps registration id -> membership signal.

    Values:

    * ``"member"`` — proven in the bound guild;
    * ``"not_linked"`` — no Discord identity on the account;
    * ``"not_member"`` — linked, but not in the guild;
    * ``"unreachable"`` — the check could not be performed;
    * ``None`` — not asked.

    Fail closed: a required check that cannot run, or a workspace with the flag
    on and no guild bound, is a block rather than a pass.
    """
    if not require:
        return []
    if not (guild_id or "").strip():
        return [EligibilityIssue(code="discord_guild_not_configured")]
    issues: list[EligibilityIssue] = []
    for registration_id, signal in members.items():
        if signal == "member":
            continue
        if signal == "not_linked":
            issues.append(EligibilityIssue(code="discord_not_linked", registration_id=registration_id))
        elif signal == "not_member":
            issues.append(EligibilityIssue(code="discord_guild_not_member", registration_id=registration_id))
        else:
            issues.append(EligibilityIssue(code="discord_guild_unreachable", registration_id=registration_id))
    return issues

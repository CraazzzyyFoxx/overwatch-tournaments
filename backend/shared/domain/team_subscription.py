"""Team-scoped subscription coverage.

When ``BalancerRegistrationForm.subscription_scope`` is ``team``, the
workspace rule still decides *what* counts, but *who* is covered is the
registered team rather than each player. Coverage is a stamp on
``balancer.registration_team`` (who redeemed, which provider, which tier, when
it expires). Validity follows that stored expiry — it does not re-query the
redeemer's personal entitlement on every gate. Captaincy transfer therefore
cannot drop a paid roster on the floor.

A player's own Discord-role (or other) entitlement remains an *alternative*
path through the per-player gate; this helper only answers whether the TEAM
stamp currently holds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

__all__ = ("SUBSCRIPTION_SCOPE_PLAYER", "SUBSCRIPTION_SCOPE_TEAM", "team_subscription_is_current")

SUBSCRIPTION_SCOPE_PLAYER = "player"
SUBSCRIPTION_SCOPE_TEAM = "team"


def team_subscription_is_current(team: Any, *, now: datetime | None = None) -> bool:
    """True when the team carries an unexpired coverage stamp.

    ``subscription_covered_at`` is the presence bit: a team that was never
    covered is not current, even if someone wrote a dangling expiry. A NULL
    expiry means "does not lapse" (Discord-role stamps often have none).
    """
    if getattr(team, "subscription_covered_at", None) is None:
        return False
    expires_at = getattr(team, "subscription_expires_at", None)
    if expires_at is None:
        return True
    moment = now or datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > moment

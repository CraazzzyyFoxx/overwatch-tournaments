"""Resolve whether registrants' Overwatch profiles are public, and why not.

Reads the collected `overwatch_rank.battle_tag_state` (populated by the parser)
and produces a per-registration :class:`ProfileSignal` for the "All Profiles
Open" admission requirement. Lives in `shared` because both tournament-service
(public reads) and balancer-service (admin reads) need it.

Returns `dict[int, ProfileSignal]`: the tri-state verdict this function has
always answered (`True` public / `False` confirmed closed / `None` unknown)
**plus** the reasons behind anything that is not a `True`.

The reason is produced here rather than reconstructed by a caller because it
only exists here. Seven `RankCollectionStatus` values plus "the registration
carries no BattleTag at all" collapse into three verdicts, and once the loop
below has answered `None` a caller holding that `None` can no longer tell an
unpolled tag from a rate-limited fetch from an organizer who switched collection
off -- three situations with three different people to chase. Under
`scope="all"` it is worse: a registrant may carry three tags with exactly one
closed, and the `False` names none of them. Reconstructing any of that would
mean a second `battle_tag_state` read on the caller's side, per registration,
which is the fan-out this function's batching exists to prevent.

`private` and `not_found` are the only BLOCKING statuses. Everything else is an
unfinished or failed collection and stays `None`, which fails open: refusing a
player because nobody has polled their tag yet would turn a stalled parser into
a mass refusal mid-check-in.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.social import SocialProvider
from shared.services.admission.reasons import reason
from shared.services.admission.signals import ProfileSignal
from shared.services.admission.types import AdmissionReason

# A tag whose last fetch landed here counts as a *closed* profile.
_CLOSED_STATUSES = frozenset(
    {
        enums.RankCollectionStatus.private.value,
        enums.RankCollectionStatus.not_found.value,
    }
)

#: Status -> reason code. ``ok`` is deliberately absent (a public profile has
#: nothing to explain), and so is any status the enum grows later: ``.get``
#: then yields ``None``, which :func:`reason` turns into the ``"unknown"`` code
#: owned by ``system``. A status this map has not learned yet must read as an
#: unexplained collection, never as a closed profile.
_REASON_BY_STATUS: Final[dict[str | None, str]] = {
    # No row at all: nobody has polled this tag yet.
    None: "never_fetched",
    enums.RankCollectionStatus.pending.value: "collection_pending",
    enums.RankCollectionStatus.error.value: "collection_failed",
    enums.RankCollectionStatus.rate_limited.value: "collection_failed",
    enums.RankCollectionStatus.disabled.value: "collection_disabled",
    enums.RankCollectionStatus.private.value: "profile_private",
    enums.RankCollectionStatus.not_found.value: "profile_not_found",
}

#: Shared by every registration in a tag-less batch. ``ProfileSignal`` is frozen,
#: so one instance is safe to hand out repeatedly. ``subject`` is ``None`` here
#: and only here: there is no tag for the reason to be about.
_NO_BATTLE_TAG: Final = ProfileSignal(is_open=None, reasons=(reason("no_battle_tag"),))


def _registration_tags(registration: Any, scope: str) -> list[str]:
    """The battlenet handles to check: the primary one, or every one under
    ``scope="all"``. Read off the eager-loaded ``identities`` rows."""
    handles = registration.handles(SocialProvider.BATTLENET)
    return [tag for tag in (handles if scope == "all" else handles[:1]) if tag]


def _reason_for(tag: str, status: str | None) -> AdmissionReason:
    """One reason for one tag. ``subject`` is ALWAYS the tag it is about."""
    return reason(_REASON_BY_STATUS.get(status), subject=tag)


async def resolve_profiles_open(
    session: AsyncSession,
    registrations: Sequence[Any],
    *,
    scope: str,
) -> dict[int, ProfileSignal]:
    """Map ``registration.id`` → :class:`ProfileSignal`.

    ``is_open`` keeps the precedence it has always had:

    - ``False`` — at least one relevant tag is private/not_found (closed wins),
      carrying one reason per CLOSED tag.
    - ``True``  — every relevant tag was fetched and is public (status ``ok``),
      carrying no reasons at all.
    - ``None``  — unknown: a relevant tag was never fetched / is pending /
      errored / has collection disabled, carrying one reason per such tag. Also
      the answer when the registration carries no tag to check.

    A closed tag suppresses the unresolved ones on purpose: ``False`` is the
    actionable verdict, and listing "and this other tag is still pending" beside
    it would bury the one thing the player has to fix.

    ``scope`` is ``"main"`` (registered battle tag only) or ``"all"`` (incl. smurfs).
    """
    tags_by_reg = {reg.id: _registration_tags(reg, scope) for reg in registrations}
    all_tags = {tag.lower() for tags in tags_by_reg.values() for tag in tags}
    if not all_tags:
        return dict.fromkeys(tags_by_reg, _NO_BATTLE_TAG)

    rows = await session.execute(
        sa.select(models.BattleTagRankState.battle_tag, models.BattleTagRankState.status).where(
            sa.func.lower(models.BattleTagRankState.battle_tag).in_(all_tags)
        )
    )
    status_by_tag: dict[str, str] = {battle_tag.lower(): status for battle_tag, status in rows.all()}

    ok = enums.RankCollectionStatus.ok.value
    signals: dict[int, ProfileSignal] = {}
    for reg_id, tags in tags_by_reg.items():
        if not tags:
            signals[reg_id] = _NO_BATTLE_TAG
            continue
        statuses = [(tag, status_by_tag.get(tag.lower())) for tag in tags]
        closed = tuple(_reason_for(tag, status) for tag, status in statuses if status in _CLOSED_STATUSES)
        if closed:
            signals[reg_id] = ProfileSignal(is_open=False, reasons=closed)
            continue
        # No closed tag, so every remaining non-``ok`` tag is an unresolved one;
        # an empty tuple here therefore means "all ok" without a second pass.
        unresolved = tuple(_reason_for(tag, status) for tag, status in statuses if status != ok)
        signals[reg_id] = ProfileSignal(is_open=None, reasons=unresolved) if unresolved else ProfileSignal(is_open=True)
    return signals

"""The stat codes the impact history backfill (re)derives.

Everything else of the backfill is IO and lives in ``shared.disciplines.overwatch.backfill.BackfillService``, which
documents the idempotency contract this set protects.
"""

from __future__ import annotations

from shared.core import enums
from shared.core import impact as impact_consts

__all__ = ("NEW_STAT_MEMBERS",)

#: Everything a backfill (re)derives and must wipe before reinserting: the kill-feed event counts, the impact facts
#: and the per-feature contributions.
NEW_STAT_MEMBERS: tuple[enums.LogStatsName, ...] = (
    *(enums.LogStatsName[name] for name in impact_consts.EVENT_STATS),
    enums.LogStatsName.ImpactPoints,
    enums.LogStatsName.ImpactRank,
    enums.LogStatsName.OverperformanceScore,
    enums.LogStatsName.OverperformanceBadge,
    *impact_consts.CONTRIBUTION_STATS.values(),
)

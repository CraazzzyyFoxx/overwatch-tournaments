"""Tournament status facts shared by services.

The status itself is derived from the flow nodes (``shared.core.flow_state``); this module only keeps the
"is it over" fact and the UTC normalizer the schedule readers use.
"""

from datetime import UTC, datetime

from shared.core.enums import TournamentStatus

# Terminal statuses: the tournament is over. Public because several services used
# to carry their own literal pair of them (rank collection, the registration
# backfill script, the registration gate) — this module owns the fact.
FINISHED_STATUSES: frozenset[TournamentStatus] = frozenset({TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED})


def as_utc(value: datetime) -> datetime:
    """Naive datetimes are UTC; aware ones are converted to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_finished_for_status(status: TournamentStatus) -> bool:
    return status in FINISHED_STATUSES

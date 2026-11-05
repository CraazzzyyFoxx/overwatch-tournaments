"""Sign-up and check-in windows of a registration node — the single source of truth.

Every registration node has its own lifecycle (``draft → open → check_in → closed``) and, optionally, ``open`` and
``check_in`` rows in ``flow_node_schedule``. The status is the organizer's decision; a row only narrows the window
inside it. A missing row means "the status decides": ``open`` is always an explicit act now, so the old "no row means
closed" inversion is gone.

**Sign-up** is possible while the node is ``open`` and ``now`` is inside the ``open`` row, or while it is
``check_in`` and the node's ``allow_late_registration`` is on. ``allow_late`` lifts the row's ``ends_at`` and nothing
else: it cannot open a window that has not started. It is a REQUIRED argument: a caller holding only
``(status, schedule)`` cannot know the flag, and defaulting it would silently answer "closed" for exactly the nodes
the flag exists to keep open.

**Late** means the sign-up is only possible past the announced closing time: the node is ``check_in`` or ``now`` is
past the ``open`` row's ``ends_at``. Not ``not open``: closed is closed, late is open-by-override.

**Check-in** is possible while the node is ``check_in`` and ``now`` is inside the ``check_in`` row.

Both a Python predicate and a SQL clause are provided because openness is read per node and inside aggregate queries.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

import sqlalchemy as sa

from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.core.tournament_state import as_utc
from shared.models.tournament.flow import FlowNode, FlowNodeSchedule
from shared.models.tournament.tournament import Tournament

__all__ = (
    "NodeScheduleEntry",
    "is_check_in_open",
    "is_sign_up_late",
    "is_sign_up_open",
    "sign_up_late_clause",
    "sign_up_open_clause",
    "tournament_sign_up_open_clause",
)

_OPEN = FlowNodeStatus.OPEN.value
_CHECK_IN = FlowNodeStatus.CHECK_IN.value


class NodeScheduleEntry(Protocol):
    """Structural view of a ``flow_node_schedule`` row."""

    phase: str
    starts_at: datetime
    ends_at: datetime | None


def _row(schedule: Iterable[NodeScheduleEntry], phase: str) -> NodeScheduleEntry | None:
    return next((entry for entry in schedule if entry.phase == phase), None)


def is_sign_up_open(
    status: str,
    schedule: Iterable[NodeScheduleEntry],
    now: datetime | None = None,
    *,
    allow_late: bool,
) -> bool:
    """Whether a self-service sign-up into the node is possible right now."""
    if status == _CHECK_IN:
        return allow_late
    if status != _OPEN:
        return False
    entry = _row(schedule, "open")
    if entry is None:
        return True
    moment = now or datetime.now(UTC)
    if as_utc(entry.starts_at) > moment:
        return False
    return entry.ends_at is None or allow_late or moment <= as_utc(entry.ends_at)


def is_sign_up_late(
    status: str,
    schedule: Iterable[NodeScheduleEntry],
    now: datetime | None = None,
) -> bool:
    """Whether a sign-up at ``now`` is only possible past the announced closing time (it is written as a reserve)."""
    if status == _CHECK_IN:
        return True
    entry = _row(schedule, "open")
    if status != _OPEN or entry is None or entry.ends_at is None:
        return False
    moment = now or datetime.now(UTC)
    return as_utc(entry.starts_at) <= moment and moment > as_utc(entry.ends_at)


def is_check_in_open(
    status: str,
    schedule: Iterable[NodeScheduleEntry],
    now: datetime | None = None,
) -> bool:
    """Whether the node's check-in is possible right now; a missing ``check_in`` row means the status decides."""
    if status != _CHECK_IN:
        return False
    entry = _row(schedule, "check_in")
    if entry is None:
        return True
    moment = now or datetime.now(UTC)
    return as_utc(entry.starts_at) <= moment and (entry.ends_at is None or moment <= as_utc(entry.ends_at))


def _allow_late() -> sa.ColumnElement[bool]:
    return sa.func.coalesce(FlowNode.config["allow_late_registration"].as_boolean(), False)


def _open_row(*conditions: sa.ColumnElement[bool]) -> sa.ColumnElement[bool]:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowNodeSchedule)
        .where(FlowNodeSchedule.node_id == FlowNode.id, FlowNodeSchedule.phase == "open", *conditions)
        .correlate(FlowNode)
        .exists()
    )


def sign_up_open_clause(now: datetime | None = None) -> sa.ColumnElement[bool]:
    """SQL form of :func:`is_sign_up_open`, correlated on ``FlowNode``.

    The override is a reference to the outer node INSIDE the ``EXISTS`` next to the ``ends_at`` test on purpose:
    lifting it to the top level would also bypass ``starts_at``.
    """
    moment = now or datetime.now(UTC)
    in_window = _open_row(
        FlowNodeSchedule.starts_at <= moment,
        sa.or_(FlowNodeSchedule.ends_at.is_(None), FlowNodeSchedule.ends_at >= moment, _allow_late()),
    )
    return sa.or_(
        sa.and_(FlowNode.status == _OPEN, sa.or_(~_open_row(), in_window)),
        sa.and_(FlowNode.status == _CHECK_IN, _allow_late()),
    )


def sign_up_late_clause(now: datetime | None = None) -> sa.ColumnElement[bool]:
    """SQL form of :func:`is_sign_up_late`, correlated on ``FlowNode``."""
    moment = now or datetime.now(UTC)
    past_end = _open_row(
        FlowNodeSchedule.starts_at <= moment,
        FlowNodeSchedule.ends_at.is_not(None),
        FlowNodeSchedule.ends_at < moment,
    )
    return sa.or_(FlowNode.status == _CHECK_IN, sa.and_(FlowNode.status == _OPEN, past_end))


def tournament_sign_up_open_clause(
    now: datetime | None = None, *node_conditions: sa.ColumnElement[bool]
) -> sa.ColumnElement[bool]:
    """``EXISTS`` a registration node of the (outer) ``Tournament`` that accepts sign-ups and meets every
    ``node_conditions`` (written against ``FlowNode``, e.g. "requires a subscription")."""
    return (
        sa.select(sa.literal(1))
        .select_from(FlowNode)
        .where(
            FlowNode.tournament_id == Tournament.id,
            FlowNode.kind == FlowNodeKind.REGISTRATION.value,
            sign_up_open_clause(now),
            *node_conditions,
        )
        .correlate(Tournament)
        .exists()
    )

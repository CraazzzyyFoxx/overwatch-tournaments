"""Guards protecting tournament write-paths from conflicting draft state."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement

from shared.core import http_status as status
from shared.core.enums import DraftStatus
from shared.core.errors import BaseAPIException
from shared.models.draft import DraftSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = (
    "assert_no_active_draft_session",
    "has_unfinished_draft_on_node",
    "has_unfinished_draft_session",
    "unfinished_draft_clause",
    "unfinished_draft_session_status",
    "unfinished_draft_tournament_ids",
)

_TERMINAL_DRAFT_STATUSES = (DraftStatus.CANCELLED, DraftStatus.COMPLETED)


async def unfinished_draft_session_status(session: AsyncSession, tournament_id: int) -> str | None:
    """Status of the tournament's in-flight draft session, or ``None`` if there is none.

    The single place this SELECT lives. The guard needs the status to name the
    blocker in its error message; the read-side ``roster_locked_by_draft`` flag
    only needs its presence -- so the query returns the status and callers that
    want a boolean go through :func:`has_unfinished_draft_session`.
    """
    return await session.scalar(
        select(DraftSession.status)
        .where(DraftSession.tournament_id == tournament_id, unfinished_draft_clause())
        .limit(1)
    )


def unfinished_draft_clause() -> ColumnElement[bool]:
    """What "in flight" means, shared by the per-tournament and per-page reads."""
    return DraftSession.status.notin_(_TERMINAL_DRAFT_STATUSES)


async def has_unfinished_draft_session(session: AsyncSession, tournament_id: int) -> bool:
    """Whether a draft session is in flight, i.e. whether the roster shape is locked."""
    return await unfinished_draft_session_status(session, tournament_id) is not None


async def has_unfinished_draft_on_node(session: AsyncSession, formation_node_id: int) -> bool:
    """Whether a draft session of this formation node is in flight, i.e. whether its mode and format are locked."""
    return (
        await session.scalar(
            select(DraftSession.id)
            .where(DraftSession.formation_node_id == formation_node_id, unfinished_draft_clause())
            .limit(1)
        )
        is not None
    )


async def unfinished_draft_tournament_ids(session: AsyncSession, tournament_ids: Sequence[int]) -> set[int]:
    """Tournament ids in ``tournament_ids`` that currently have an in-flight draft.

    One statement for a page of tournaments so list serialization does not pay
    one ``has_unfinished_draft_session`` round-trip per row.
    """
    if not tournament_ids:
        return set()
    result = await session.scalars(
        select(DraftSession.tournament_id)
        .where(DraftSession.tournament_id.in_(tournament_ids), unfinished_draft_clause())
        .distinct()
    )
    return set(result.all())


async def assert_no_active_draft_session(session: AsyncSession, tournament_id: int, *, change: str) -> None:
    """Raise a business error when the tournament has an in-flight draft session.

    Changing the roster shape the draft is picking into while a draft is in
    flight would orphan the session, so callers invoke this before applying
    such a change. ``change`` names the edit in the error message.
    """
    active_status = await unfinished_draft_session_status(session, tournament_id)
    if active_status is not None:
        raise BaseAPIException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot change {change} while a draft session is active "
                f"(status: {active_status}). Cancel or complete the draft first."
            ),
        )

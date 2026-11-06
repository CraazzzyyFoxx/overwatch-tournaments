"""Sign-up and check-in gating of one registration node.

The node's status is the single source of truth for what is currently possible; its ``flow_node_schedule`` rows only
narrow the window inside the status (a missing row means the status decides) and the node's
``allow_late_registration`` lifts the ``open`` row's ``ends_at``. See :mod:`shared.services.registration_window` for
the rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import FlowNodeKind
from shared.domain.flow.config import RegistrationNodeConfig, parse_node_config
from shared.repository.flow_node import FlowNodeRepository
from shared.services.registration_window import (
    is_check_in_open,
    is_sign_up_open,
    sign_up_late_clause,
    sign_up_open_clause,
)

_flow_nodes = FlowNodeRepository()


def node_config(node: models.FlowNode) -> RegistrationNodeConfig:
    """The typed config of a registration node."""
    config = parse_node_config(FlowNodeKind.REGISTRATION, node.config)
    assert isinstance(config, RegistrationNodeConfig)
    return config


def is_sign_up_open_for(
    node: models.FlowNode,
    schedule: Sequence[models.FlowNodeSchedule],
    *,
    now: datetime | None = None,
) -> bool:
    """Whether self-service registration into ``node`` is open right now."""
    return is_sign_up_open(node.status, schedule, now, allow_late=node_config(node).allow_late_registration)


def is_check_in_open_for(
    node: models.FlowNode,
    schedule: Sequence[models.FlowNodeSchedule],
    *,
    now: datetime | None = None,
) -> bool:
    """Whether the node's check-in is possible right now."""
    return is_check_in_open(node.status, schedule, now)


class RegistrationWindowService:
    """The session-taking window reads; the predicates above stay pure."""

    async def load_schedule(self, session: AsyncSession, registration_node_id: int) -> list[models.FlowNodeSchedule]:
        rows = await session.scalars(
            sa.select(models.FlowNodeSchedule).where(models.FlowNodeSchedule.node_id == registration_node_id)
        )
        return list(rows)

    async def load_sign_up_state(self, session: AsyncSession, registration_node_id: int) -> tuple[bool, bool]:
        """``(is_open, is_late)`` of a node in ONE round trip.

        Two scalars off one row, from the same SQL clauses the aggregate readers use, so the per-node and in-query
        answers cannot drift apart.
        """
        row = (
            await session.execute(
                sa.select(sign_up_open_clause(), sign_up_late_clause()).where(
                    models.FlowNode.id == registration_node_id
                )
            )
        ).first()
        return (bool(row[0]), bool(row[1])) if row is not None else (False, False)

    async def load_sign_up_open(self, session: AsyncSession, registration_node_id: int) -> bool:
        return (await self.load_sign_up_state(session, registration_node_id))[0]

    async def load_check_in_open(self, session: AsyncSession, registration_node_id: int) -> bool:
        node = await _flow_nodes.get(session, registration_node_id)
        if node is None:
            return False
        return is_check_in_open_for(node, await self.load_schedule(session, registration_node_id))


windows_service = RegistrationWindowService()

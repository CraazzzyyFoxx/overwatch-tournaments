"""Resolve the per-workspace sub-role catalog for registration forms.

The ``PlayerSubRole`` table is the single source of truth for which sub-roles a
workspace allows. Registration (public wizard + admin builder) consumes the
catalog through :func:`resolve_subrole_catalog`, which returns the options keyed
by registration role code (tank/dps/support) so the frontend needs no hardcoded
lists.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.player_sub_roles import build_subrole_catalog

SubroleCatalog = dict[str, list[dict[str, str]]]


async def resolve_subrole_catalog(
    session: AsyncSession,
    workspace_id: int,
) -> SubroleCatalog:
    """Return ``{reg_role_code: [{"slug", "label"}]}`` for active sub-roles."""
    query = (
        sa.select(models.PlayerSubRole)
        .where(
            models.PlayerSubRole.workspace_id == workspace_id,
            models.PlayerSubRole.is_active.is_(True),
        )
        .order_by(
            models.PlayerSubRole.role.asc(),
            models.PlayerSubRole.sort_order.asc(),
            models.PlayerSubRole.label.asc(),
        )
    )
    rows = (await session.execute(query)).scalars().all()
    return build_subrole_catalog(rows)

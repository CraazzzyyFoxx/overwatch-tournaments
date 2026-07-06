"""Rank-signal sources for the registration rank autofill.

Loads and normalizes the candidate rank values the autofill chain picks from:
weekly OW rank-snapshot composites, past balancer-registration ranks
("division_history") and past tournament-participation ranks ("analytics"),
plus the grid normalization that maps historical ranks into the target
tournament's division grid. The stage resolution and orchestration live in
``rank_autofill``; everything here is re-exported by the ``admin`` facade.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.core.social import SocialProvider
from shared.division_grid import DivisionGrid
from shared.domain.player_sub_roles import REGISTRATION_TO_CANONICAL
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
    build_division_grid_normalizer,
)
from src import models
from src.services.registration.utils import normalize_battle_tag_key


@dataclass
class _RankData:
    """Resolved rank value for autofill, abstracting over snapshot and balancer history.

    ``rank_value`` is the *chosen* (suggested) value. The ``*_rank_value`` breakdown fields
    carry every candidate signal that was considered so the UI can surface why a value was
    picked, and ``used_source`` names the candidate that won.
    """

    rank_value: int | None
    platform: str | None = None
    division: str | None = None
    tier: int | None = None
    season: int | None = None
    captured_at: datetime | None = None
    source: str = "analytics"
    division_history_rank_value: int | None = None
    ow_rank_value: int | None = None
    ow_current_rank_value: int | None = None
    analytics_rank_value: int | None = None
    used_source: str | None = None


@dataclass
class _OwRankSignals:
    """Weekly OW rank signal for a single (battle_tag, role).

    ``composite_rank_value`` is ``round((max + mean) / 2)`` over the chosen weekly window of
    mapped OW ``rank_value`` snapshots (see ``_compute_ow_week_rank_value``). ``latest_snapshot``
    is the most recent snapshot, kept for display metadata (platform/division/season/captured_at)
    and for the contextual "OW current" value.
    """

    composite_rank_value: int | None = None
    latest_snapshot: models.UserRankSnapshot | Any | None = None


# Registration role code -> canonical RankRole value (e.g. dps -> damage). Single source of
# truth is shared.domain.player_sub_roles; aliased here for the autofill snapshot lookups.
RANK_ROLE_BY_REGISTRATION_ROLE = dict(REGISTRATION_TO_CANONICAL)
REGISTRATION_ROLE_LABELS = {
    "tank": "Tank",
    "dps": "Damage",
    "support": "Support",
}
# tournament.player.role is a HeroClass (Tank/Damage/Support); bridge it to the registration
# role codes (tank/dps/support) used to key balancer history and the per-role rank data.
HERO_CLASS_TO_REGISTRATION_ROLE = {
    enums.HeroClass.tank: "tank",
    enums.HeroClass.damage: "dps",
    enums.HeroClass.support: "support",
}
# Window for the OW rank source: aggregate snapshots captured within one week.
OW_RANK_WEEK_WINDOW = timedelta(days=7)


async def _load_tournament_for_autofill(
    session: AsyncSession,
    tournament_id: int,
) -> models.Tournament | None:
    result = await session.execute(
        sa.select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(selectinload(models.Tournament.division_grid_version).selectinload(models.DivisionGridVersion.tiers))
    )
    return result.scalar_one_or_none()


def _normalize_history_rank(
    normalizer: DivisionGridNormalizer | None,
    source_version_id: int | None,
    rank: int | None,
    target_grid: DivisionGrid,
) -> int | None:
    """Map a historical rank from its source tournament's grid version into the target grid.

    Returns the target tier's ``rank_min``. When no normalizer/source version is available the
    rank is returned unchanged; when a primary mapping is missing it falls back to matching the
    division *number* (stable across grids), mirroring the frontend ``safeNormalize``.
    """
    if rank is None:
        return None
    if normalizer is None or source_version_id is None:
        return rank
    try:
        return normalizer.normalize_division(source_version_id, rank).rank_min
    except DivisionGridNormalizationError:
        source_grid = normalizer.source_grids_by_version_id.get(source_version_id, target_grid)
        number = source_grid.resolve_division_number(rank)
        mapped = target_grid.resolve_rank_from_division(number)
        return mapped if mapped is not None else rank


async def _build_autofill_rank_normalizer(
    session: AsyncSession,
    tournament: models.Tournament | Any,
) -> DivisionGridNormalizer | None:
    """Build a normalizer targeting the tournament's grid version, or None if unavailable.

    ``require_complete=False`` so a workspace with partially-mapped grids still builds; per-rank
    misses are handled by ``_normalize_history_rank``'s division-number fallback.
    """
    target_version_id = getattr(tournament, "division_grid_version_id", None)
    if target_version_id is None:
        return None
    try:
        return await build_division_grid_normalizer(
            session,
            tournament.workspace_id,
            target_version_id=target_version_id,
            require_complete=False,
        )
    except DivisionGridNormalizationError:
        return None


async def _load_latest_ranks_from_balancer_history(
    session: AsyncSession,
    user_ids: list[int],
    current_tournament_id: int,
    workspace_id: int,
    normalizer: DivisionGridNormalizer | None,
    target_grid: DivisionGrid,
    min_tournament_number: int | None = None,
) -> dict[int, dict[str, int]]:
    """Return dict[user_id][role_code] → rank_value from past registration records.

    Searches the workspace's previous tournaments (excluding the current one), ordered
    by tournament number descending so the most recent entry wins. Ranks are normalized from
    each source tournament's grid version into the target grid. When ``min_tournament_number`` is
    set, only tournaments whose ``number`` is at least that cutoff are considered (recency window;
    rows with a ``NULL`` number naturally fall outside the window).
    """
    if not user_ids:
        return {}

    # Registrations are anchored on workspace_member; the domain player id is
    # the member's player_id. Inner join: member-less registrations have no
    # player identity and (as before, when user_id was NULL) never match.
    stmt = (
        sa.select(
            models.WorkspaceMember.player_id.label("user_id"),
            models.BalancerRegistrationRole.role,
            models.BalancerRegistrationRole.rank_value,
            models.Tournament.division_grid_version_id,
        )
        .select_from(models.BalancerRegistration)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.BalancerRegistration.workspace_member_id,
        )
        .join(
            models.BalancerRegistrationRole,
            models.BalancerRegistrationRole.registration_id == models.BalancerRegistration.id,
        )
        .join(
            models.Tournament,
            models.Tournament.id == models.BalancerRegistration.tournament_id,
        )
        .where(
            models.WorkspaceMember.player_id.in_(user_ids),
            models.Tournament.workspace_id == workspace_id,
            models.BalancerRegistration.tournament_id != current_tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistrationRole.is_active.is_(True),
            models.BalancerRegistrationRole.rank_value.is_not(None),
        )
        .order_by(
            models.WorkspaceMember.player_id,
            models.BalancerRegistrationRole.role,
            models.Tournament.number.desc().nullslast(),
            models.BalancerRegistration.tournament_id.desc(),
        )
    )
    if min_tournament_number is not None:
        stmt = stmt.where(models.Tournament.number >= min_tournament_number)

    rows = (await session.execute(stmt)).all()

    latest: dict[int, dict[str, int]] = {}
    for row in rows:
        user_map = latest.setdefault(row.user_id, {})
        if row.role not in user_map:
            normalized = _normalize_history_rank(normalizer, row.division_grid_version_id, row.rank_value, target_grid)
            if normalized is not None:
                user_map[row.role] = normalized
    return latest


async def _load_latest_ranks_from_tournament_history(
    session: AsyncSession,
    user_ids: list[int],
    current_tournament_id: int,
    workspace_id: int,
    normalizer: DivisionGridNormalizer | None,
    target_grid: DivisionGrid,
    min_tournament_number: int | None = None,
) -> dict[int, dict[str, int]]:
    """Return dict[user_id][registration_role_code] → rank from past tournament participation.

    This is the "analytics" source: actual ranks played in the workspace's previous tournaments
    (``tournament.player``), distinct from the balancer-registration history. Excludes the current
    tournament and substitution rows; the most recent tournament wins per role. ``Player.role`` is
    a HeroClass and is bridged to the registration role code (Damage → dps) to match keying. Ranks
    are normalized from each source tournament's grid version into the target grid. When
    ``min_tournament_number`` is set, only tournaments whose ``number`` is at least that cutoff are
    considered (recency window; rows with a ``NULL`` number naturally fall outside the window).
    """
    if not user_ids:
        return {}

    stmt = (
        sa.select(
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.role,
            models.Player.rank,
            models.Tournament.division_grid_version_id,
        )
        .join(
            models.Tournament,
            models.Tournament.id == models.Player.tournament_id,
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(
            models.WorkspaceMember.player_id.in_(user_ids),
            models.Tournament.workspace_id == workspace_id,
            models.Player.tournament_id != current_tournament_id,
            models.Player.role.is_not(None),
            models.Player.is_substitution.is_(False),
            models.Player.rank > 0,
        )
        .order_by(
            models.WorkspaceMember.player_id,
            models.Player.role,
            models.Tournament.number.desc().nullslast(),
            models.Player.tournament_id.desc(),
        )
    )
    if min_tournament_number is not None:
        stmt = stmt.where(models.Tournament.number >= min_tournament_number)

    rows = (await session.execute(stmt)).all()

    latest: dict[int, dict[str, int]] = {}
    for row in rows:
        role_code = HERO_CLASS_TO_REGISTRATION_ROLE.get(row.role)
        if role_code is None:
            continue
        user_map = latest.setdefault(row.user_id, {})
        if role_code not in user_map:
            normalized = _normalize_history_rank(normalizer, row.division_grid_version_id, row.rank, target_grid)
            if normalized is not None:
                user_map[role_code] = normalized
    return latest


async def load_user_balancer_rank_history(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> list[dict[str, Any]]:
    """Per (tournament, role) ranks from a user's past balancer registrations in a workspace.

    Newest tournament first; only active, ranked roles. Powers the balancer step of the
    PlayerEditSheet "Load from history" preview (source = "balancer").
    """
    rows = (
        await session.execute(
            sa.select(
                models.Tournament.id.label("tournament_id"),
                models.Tournament.number.label("tournament_number"),
                models.Tournament.name.label("tournament_name"),
                models.BalancerRegistrationRole.role,
                models.BalancerRegistrationRole.rank_value,
            )
            .join(
                models.BalancerRegistration,
                models.BalancerRegistration.id == models.BalancerRegistrationRole.registration_id,
            )
            .join(
                models.Tournament,
                models.Tournament.id == models.BalancerRegistration.tournament_id,
            )
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.BalancerRegistration.workspace_member_id,
            )
            .where(
                models.WorkspaceMember.player_id == user_id,
                models.Tournament.workspace_id == workspace_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistrationRole.is_active.is_(True),
                models.BalancerRegistrationRole.rank_value.is_not(None),
            )
            .order_by(
                models.Tournament.number.desc().nullslast(),
                models.BalancerRegistration.tournament_id.desc(),
            )
        )
    ).all()

    return [
        {
            "tournament_id": row.tournament_id,
            "tournament_number": row.tournament_number,
            "tournament_name": row.tournament_name,
            "role": row.role,
            "rank_value": row.rank_value,
        }
        for row in rows
    ]


async def _load_rank_autofill_registrations(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int] | None,
) -> list[models.BalancerRegistration]:
    query = (
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .options(selectinload(models.BalancerRegistration.roles))
        .order_by(
            models.BalancerRegistration.battle_tag_normalized.asc().nullslast(), models.BalancerRegistration.id.asc()
        )
    )
    if registration_ids is not None:
        if not registration_ids:
            return []
        query = query.where(models.BalancerRegistration.id.in_(registration_ids))
    result = await session.execute(query)
    return list(result.scalars().all())


async def _load_main_battle_tags_by_key(
    session: AsyncSession,
    registrations: list[models.BalancerRegistration],
) -> dict[str, models.SocialAccount]:
    """Map normalized battletag key → the battlenet ``social_account`` it belongs to.

    ``social_account.username_normalized`` (battlenet) is exactly
    ``normalize_battle_tag_key`` of the handle, so registration keys match directly.
    """
    tag_keys = {
        key
        for registration in registrations
        if (key := (registration.battle_tag_normalized or normalize_battle_tag_key(registration.battle_tag)))
    }
    if not tag_keys:
        return {}

    acc = models.SocialAccount
    result = await session.execute(
        sa.select(acc).where(
            acc.provider == SocialProvider.BATTLENET,
            acc.username_normalized.in_(tag_keys),
        )
    )
    return {account.username_normalized: account for account in result.scalars().all() if account.username_normalized}


async def _load_ow_rank_signals_by_social_account_id(
    session: AsyncSession,
    social_account_ids: list[int],
    now: datetime,
    week_window: timedelta = OW_RANK_WEEK_WINDOW,
) -> dict[int, dict[str, _OwRankSignals]]:
    """Return per (social_account_id, rank_role) the weekly OW rank composite + latest snapshot."""
    if not social_account_ids:
        return {}
    result = await session.execute(
        sa.select(models.UserRankSnapshot)
        .where(
            models.UserRankSnapshot.social_account_id.in_(social_account_ids),
            models.UserRankSnapshot.role.in_(set(RANK_ROLE_BY_REGISTRATION_ROLE.values())),
            models.UserRankSnapshot.rank_value.is_not(None),
            models.UserRankSnapshot.is_ranked.is_(True),
        )
        .order_by(models.UserRankSnapshot.captured_at.desc(), models.UserRankSnapshot.id.desc())
    )
    return _group_ow_rank_signals(result.scalars().all(), now, week_window)


def _group_ow_rank_signals(
    snapshots_newest_first: Iterable[models.UserRankSnapshot | Any],
    now: datetime,
    week_window: timedelta = OW_RANK_WEEK_WINDOW,
) -> dict[int, dict[str, _OwRankSignals]]:
    """Group newest-first snapshots into per (social_account_id, role) weekly OW signals.

    Pure (no DB) so the windowing logic can be unit-tested. For each (tag, role) the composite
    rank is ``round((max + mean) / 2)`` over the ``week_window`` (see ``_compute_ow_week_rank_value``);
    the first snapshot seen (newest) is kept as the latest for display metadata.
    """
    grouped: dict[int, dict[str, list[Any]]] = {}
    for snapshot in snapshots_newest_first:
        grouped.setdefault(snapshot.social_account_id, {}).setdefault(snapshot.role, []).append(snapshot)

    signals_by_tag_id: dict[int, dict[str, _OwRankSignals]] = {}
    for tag_id, role_map in grouped.items():
        out = signals_by_tag_id.setdefault(tag_id, {})
        for role, snaps in role_map.items():
            out[role] = _OwRankSignals(
                composite_rank_value=_compute_ow_week_rank_value(snaps, now, week_window),
                latest_snapshot=snaps[0] if snaps else None,
            )
    return signals_by_tag_id


def _compute_ow_week_rank_value(
    snapshots: Iterable[models.UserRankSnapshot | Any],
    now: datetime,
    week_window: timedelta = OW_RANK_WEEK_WINDOW,
) -> int | None:
    """Composite OW rank over a weekly window: ``round((max + mean) / 2)`` of mapped rank_value.

    Window selection (per role), using ``week_window`` (default 7 days):
      1. snapshots captured within the last ``week_window`` from ``now``;
      2. if none, snapshots within ``week_window`` of the player's most recent snapshot;
      3. if still none (no usable timestamps), the single most-recent snapshot.
    Returns ``None`` only when there are no snapshots carrying a ``rank_value``.
    """
    snaps = [s for s in snapshots if getattr(s, "rank_value", None) is not None]
    if not snaps:
        return None

    dated = [s for s in snaps if getattr(s, "captured_at", None) is not None]
    window = [s for s in dated if s.captured_at >= now - week_window]
    if not window and dated:
        latest_at = max(s.captured_at for s in dated)
        window = [s for s in dated if s.captured_at >= latest_at - week_window]
    if not window:
        window = [snaps[0]]

    values = [s.rank_value for s in window]
    return round((max(values) + sum(values) / len(values)) / 2)


def _build_priority_rank_data(
    order: Sequence[str],
    signals: _OwRankSignals | None,
    division_history_rank: int | None,
    analytics_rank: int | None,
    grid: DivisionGrid,
) -> _RankData | None:
    """Pick a rank by strict priority fallback over the given (enabled, ordered) source chain.

    ``order`` lists the enabled sources in priority order (subset of ``ow`` / ``division_history`` /
    ``analytics``). The first source carrying a value wins (no max blending). Returns ``None`` when
    no source in ``order`` carries a value (the role is then treated as missing).
    """
    latest_snapshot = signals.latest_snapshot if signals else None
    ow_rank = _map_ow_rank_value(signals.composite_rank_value, grid) if signals else None
    ow_current_rank = _map_ow_snapshot_rank(latest_snapshot, grid)

    candidates: dict[str, int | None] = {
        "ow": ow_rank,
        "division_history": division_history_rank,
        "analytics": analytics_rank,
    }

    used_source = next((source for source in order if candidates.get(source) is not None), None)
    if used_source is None:
        return None
    chosen = candidates[used_source]

    source = "balancer" if used_source == "division_history" else "analytics"
    return _RankData(
        rank_value=chosen,
        platform=getattr(latest_snapshot, "platform", None),
        division=getattr(latest_snapshot, "division", None),
        tier=getattr(latest_snapshot, "tier", None),
        season=getattr(latest_snapshot, "season", None),
        captured_at=getattr(latest_snapshot, "captured_at", None),
        source=source,
        division_history_rank_value=division_history_rank,
        ow_rank_value=ow_rank,
        ow_current_rank_value=ow_current_rank,
        analytics_rank_value=analytics_rank,
        used_source=used_source,
    )


def _map_ow_rank_value(ow_rank_value: int | None, grid: DivisionGrid) -> int | None:
    """Map an OW ``rank_value`` to a tournament division rank via the grid, or None if unmapped."""
    if ow_rank_value is None:
        return None
    tier = grid.resolve_division_from_ow_rank(ow_rank_value)
    return tier.rank_min if tier is not None else None


def _map_ow_snapshot_rank(snapshot: models.UserRankSnapshot | Any | None, grid: DivisionGrid) -> int | None:
    """Map a single OW snapshot to a tournament division rank via the grid, or None if unmapped."""
    if snapshot is None:
        return None
    return _map_ow_rank_value(getattr(snapshot, "rank_value", None), grid)

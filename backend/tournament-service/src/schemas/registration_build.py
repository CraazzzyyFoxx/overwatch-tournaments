"""Registration read-model builders and tournament-history aggregation.

Extracted verbatim from the decommissioned ``src/routes/registration.py`` so the
typed-RPC handlers in ``src/rpc/public_rpc.py`` build the SAME ``RegistrationRead``
/ ``RegistrationFormRead`` payloads and the SAME participant tournament-history
envelope. This module must NOT import fastapi.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import build_unknown_status_meta
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.hero_catalog import HeroCatalog, resolve_hero_catalog
from shared.services.division_grid_access import (
    get_effective_division_grid_version_id,
    load_division_grid_snapshot,
)
from src import models
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.registration import (
    RegistrationFormRead,
    RegistrationRead,
    RegistrationRoleRead,
    TournamentHistoryEntry,
)

# Max past-tournament history entries returned per participant. The public
# participants table only renders the most recent few (in a hover tooltip), so the
# full list is capped here and the true total is surfaced via ``tournament_history_count``.
HISTORY_LIMIT = 10

# HTTP 404 Not Found — raised below without importing fastapi so this module stays
# fastapi-free. The RPC ``_run`` envelope catches fastapi ``HTTPException`` by type,
# so we raise the genuine class via a lazy import to preserve the 404 contract.
_HTTP_404_NOT_FOUND = 404


def _http_exception(status_code: int, detail: str) -> Exception:
    """Build the canonical fastapi ``HTTPException`` without a module-level import.

    The RPC envelope (``public_rpc._run``) maps a fastapi ``HTTPException`` to the
    error code; raising the genuine class keeps the status-code contract intact
    while keeping this module free of a top-level fastapi import.
    """
    from shared.core.errors import BaseAPIException as HTTPException

    return HTTPException(status_code=status_code, detail=detail)


def _registration_player_id(reg: models.BalancerRegistration) -> int | None:
    """The registration's domain player id via its workspace_member anchor.

    Callers MUST eager-load ``BalancerRegistration.workspace_member``
    (``selectinload``) — accessing an unloaded relationship here would
    lazy-load outside the request's greenlet and raise ``MissingGreenlet``.
    """
    member = reg.workspace_member
    return member.player_id if member is not None else None


async def _resolve_tournament_workspace(session: AsyncSession, tournament_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        raise _http_exception(_HTTP_404_NOT_FOUND, "Tournament not found")
    return workspace_id


async def _resolve_top_heroes_config(
    session: AsyncSession,
    form: models.BalancerRegistrationForm,
) -> tuple[HeroCatalog | None, int | None]:
    """Resolve ``(hero_catalog, max_heroes)`` when the top-heroes field is enabled.

    Returns ``(None, None)`` when the field is absent or disabled, so heroes are
    neither validated nor persisted for that tournament.
    """
    config = (form.built_in_fields_json or {}).get("top_heroes")
    if not config or config.get("enabled", True) is False:
        return None, None
    raw_max = config.get("max_heroes")
    max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else None
    hero_catalog = await resolve_hero_catalog(session)
    return hero_catalog, max_heroes


def _form_to_read(
    form: models.BalancerRegistrationForm,
    *,
    subrole_catalog: dict[str, list[dict[str, str]]] | None = None,
) -> RegistrationFormRead:
    return RegistrationFormRead(
        id=form.id,
        tournament_id=form.tournament_id,
        workspace_id=form.workspace_id,
        is_open=form.is_open,
        auto_approve=form.auto_approve,
        require_open_profile=form.require_open_profile,
        open_profile_scope=form.open_profile_scope,
        show_ranks=form.show_ranks,
        built_in_fields=form.built_in_fields_json or {},
        custom_fields=form.custom_fields_json or [],
        subrole_catalog=subrole_catalog or {},
    )


def _reg_to_read(
    reg: models.BalancerRegistration,
    *,
    workspace_id: int,
    status_meta_map: dict[str, dict[str, dict[str, object]]] | None = None,
    show_ranks: bool = False,
    include_private: bool = True,
    profiles_open: bool | None = None,
) -> RegistrationRead:
    """Serialize a registration for public API responses.

    ``include_private=False`` is for anonymous/list contexts: it strips
    organizer-defined custom fields, which may contain PII and are only meant
    for the registrant themselves and admins. Free-text ``notes`` stay public:
    they are the participant-facing "anything you'd like organizers to know"
    form field and are rendered as a column on the public participants roster.
    Smurf tags stay public too: they are declared alternate battle tags, the
    same anti-smurf transparency class as ``battle_tag``/``discord_nick``/
    ``twitch_nick`` (all already public), and the participants roster exists
    precisely to surface them.
    """
    roles = (
        [
            RegistrationRoleRead(
                role=r.role,
                subrole=r.subrole,
                is_primary=r.is_primary,
                priority=r.priority,
                rank_value=r.rank_value if show_ranks else None,
                top_heroes=[he.hero.slug for he in sorted(r.hero_entries, key=lambda he: he.priority)],
            )
            for r in sorted(reg.roles, key=lambda r: (not r.is_primary, r.priority))
        ]
        if reg.roles
        else []
    )

    return RegistrationRead(
        id=reg.id,
        tournament_id=reg.tournament_id,
        workspace_id=workspace_id,
        # API shape preserved: user_id stays in the payload, derived from the
        # workspace_member anchor (callers eager-load it; see helper).
        user_id=_registration_player_id(reg),
        battle_tag=reg.battle_tag,
        smurf_tags_json=reg.smurf_tags_json,
        discord_nick=reg.discord_nick,
        twitch_nick=reg.twitch_nick,
        stream_pov=reg.stream_pov,
        roles=roles,
        notes=reg.notes,
        custom_fields_json=reg.custom_fields_json if include_private else None,
        status=reg.status,
        status_meta=(status_meta_map["registration"].get(reg.status) if status_meta_map is not None else None)
        or build_unknown_status_meta("registration", reg.status),
        balancer_status=reg.balancer_status,
        balancer_status_meta=(
            status_meta_map["balancer"].get(reg.balancer_status) if status_meta_map is not None else None
        )
        or build_unknown_status_meta("balancer", reg.balancer_status),
        checked_in=reg.checked_in,
        profiles_open=profiles_open,
        submitted_at=reg.submitted_at,
        reviewed_at=reg.reviewed_at,
    )


async def _build_tournament_history(
    session: AsyncSession,
    registrations: list[models.BalancerRegistration],
    current_tournament_id: int,
    workspace_id: int,
) -> tuple[
    dict[int, list[TournamentHistoryEntry]],
    dict[int, int],
    dict[str, DivisionGridVersionRead],
]:
    """Batch-query past tournament participation from the analytics system.

    Uses tournament.player (the analytics table) — if a player record exists,
    they definitely participated. No extra checks needed.

    The player id (players.user.id) is resolved via workspace_member ->
    player_id — the registration's only identity anchor since dbarch02
    dropped user_id.

    Callers must eager-load ``BalancerRegistration.workspace_member`` for the
    resolution to see anything (a lazy load here would run outside the
    request's greenlet).

    Returns a tuple of:
    - ``history_map``: registration_id -> most-recent-first history entries,
      capped at ``HISTORY_LIMIT`` and deduplicated by tournament.
    - ``count_map``: registration_id -> true (pre-cap) number of past tournaments.
    - ``division_grids``: stringified version_id -> ``DivisionGridVersionRead``,
      containing only the versions actually referenced by the returned entries.
    """
    # Build reverse map: analytics_user_id -> list of registration ids
    player_to_reg_ids: dict[int, list[int]] = {}
    for r in registrations:
        uid = _registration_player_id(r)
        if uid is not None:
            player_to_reg_ids.setdefault(uid, []).append(r.id)

    player_ids = list(player_to_reg_ids.keys())
    if not player_ids:
        return {}, {}, {}

    # --- Step 2: query tournament.player for participation history (columns only) ---
    # Select scalar columns rather than full ``Player`` ORM objects: avoids hydrating
    # thousands of rows and sidesteps any lazy-attribute access outside the greenlet.
    # Ordered most-recent-first so the per-registration cap keeps the latest entries.
    result = await session.execute(
        sa.select(
            models.Player.tournament_id,
            models.WorkspaceMember.player_id,
            models.Player.role,
            models.Player.rank,
            models.Tournament.name.label("tournament_name"),
        )
        .join(
            models.Tournament,
            models.Player.tournament_id == models.Tournament.id,
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(
            models.WorkspaceMember.player_id.in_(player_ids),
            models.Player.tournament_id != current_tournament_id,
            models.Tournament.workspace_id == workspace_id,
        )
        .order_by(
            models.Tournament.start_date.desc().nullslast(),
            models.Tournament.id.desc(),
        )
    )
    rows = result.all()

    # --- Step 3: resolve division-grid versions (Redis-cached, batched) ---
    # ``get_effective_division_grid_version_id`` is Redis-backed, so the many past
    # tournaments collapse to a handful of distinct version ids cheaply.
    tournament_ids_with_rank = {tournament_id for tournament_id, _uid, _role, rank, _name in rows if rank is not None}
    tournament_to_version: dict[int, int | None] = {}
    for tid in tournament_ids_with_rank:
        tournament_to_version[tid] = await get_effective_division_grid_version_id(
            session, workspace_id, tournament_id=tid
        )

    distinct_version_ids = {vid for vid in tournament_to_version.values() if vid is not None}

    # Runtime grids (for division-number resolution) come from the cached snapshot.
    runtime_grid_by_version: dict[int, DivisionGrid] = {}
    for vid in distinct_version_ids:
        snapshot = await load_division_grid_snapshot(session, vid)
        runtime_grid_by_version[vid] = snapshot.to_runtime_grid() if snapshot is not None else load_runtime_grid(None)

    # Full version metadata for the response map — ONE batched query, validated once.
    version_read_by_id: dict[int, DivisionGridVersionRead] = {}
    if distinct_version_ids:
        version_rows = await session.scalars(
            sa.select(models.DivisionGridVersion)
            .options(selectinload(models.DivisionGridVersion.tiers))
            .where(models.DivisionGridVersion.id.in_(distinct_version_ids))
        )
        for version in version_rows:
            version_read_by_id[int(version.id)] = DivisionGridVersionRead.model_validate(version, from_attributes=True)

    # --- Step 4: build per-registration history (deduped by tournament, capped) ---
    history_map: dict[int, list[TournamentHistoryEntry]] = {}
    count_map: dict[int, int] = {}
    seen_per_reg: dict[int, set[int]] = {}

    for tournament_id, user_id, role, rank, tournament_name in rows:
        reg_ids = player_to_reg_ids.get(user_id)
        if not reg_ids:
            continue

        role_str = role.value if role else None
        division = None
        version_id = None
        if rank is not None:
            version_id = tournament_to_version.get(tournament_id)
            grid = runtime_grid_by_version.get(version_id) if version_id is not None else None
            if grid is None:
                grid = load_runtime_grid(None)
            division = grid.resolve_division_number(rank)
            # Only reference versions we actually have metadata for.
            if version_id not in version_read_by_id:
                version_id = None

        entry = TournamentHistoryEntry(
            tournament_id=tournament_id,
            tournament_name=tournament_name,
            role=role_str,
            division=division,
            division_grid_version_id=version_id,
        )
        for reg_id in reg_ids:
            # A player can have multiple Player rows per tournament (e.g. substitution);
            # keep one entry per tournament per registration.
            seen = seen_per_reg.setdefault(reg_id, set())
            if tournament_id in seen:
                continue
            seen.add(tournament_id)
            count_map[reg_id] = count_map.get(reg_id, 0) + 1
            entries = history_map.setdefault(reg_id, [])
            if len(entries) < HISTORY_LIMIT:
                entries.append(entry)

    # Keep only the versions still referenced after capping.
    referenced_version_ids = {
        entry.division_grid_version_id
        for entries in history_map.values()
        for entry in entries
        if entry.division_grid_version_id is not None
    }
    division_grids = {str(vid): version_read_by_id[vid] for vid in referenced_version_ids if vid in version_read_by_id}

    return history_map, count_map, division_grids

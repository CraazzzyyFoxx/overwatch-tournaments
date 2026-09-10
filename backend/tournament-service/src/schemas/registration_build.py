"""Registration read-model builders and tournament-history aggregation.

Extracted verbatim from the decommissioned ``src/routes/registration.py`` so the
typed-RPC handlers in ``src/rpc/public_rpc.py`` build the SAME ``RegistrationRead``
/ ``RegistrationFormRead`` payloads and the SAME participant tournament-history
envelope. This module must NOT import fastapi.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import build_unknown_status_meta
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.domain.roster import PlayerRoster
from shared.hero_catalog import HeroCatalog, resolve_hero_catalog
from shared.services.admission.requirements.open_profile import KEY as OPEN_PROFILE_KEY
from shared.services.admission.requirements.subscription import KEY as SUBSCRIPTION_KEY
from shared.services.admission.types import AdmissionEvaluation
from shared.services.division_grid.access import (
    get_effective_division_grid_version_ids,
    load_division_grid_snapshots,
    load_division_grid_version_read_payloads,
)
from shared.services.roster import registration_load_options, roster_engine
from src import models
from src.schemas.admission import AdmissionRead
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.registration import (
    RegistrationFormRead,
    RegistrationRead,
    RegistrationRoleRead,
    RegistrationTeamBrief,
    TournamentHistoryEntry,
)


@dataclass(frozen=True, slots=True)
class AdmissionChips:
    """One evaluation, projected into the four fields a registration read carries.

    The three chip fields are NOT derived from ``decision`` -- they are the raw
    signals the requirements were evaluated FROM, which is why they stay separate
    columns on the read. They are lifted out of ``requirements[].detail`` rather
    than resolved a second time: the batch already paid for the
    ``battle_tag_state`` row and the entitlement pass, and a second resolution is
    precisely how the admin column and the player's own card came to disagree.

    Both list handlers -- public participants and admin registrations -- build
    their reads through here, so the ``detail`` key names live in one place and
    the two surfaces cannot drift apart.
    """

    admission: AdmissionRead
    profiles_open: bool | None = None
    subscription_outcome: str | None = None
    subscription_verdicts: dict[str, Any] | None = None

    @classmethod
    def of(cls, evaluation: AdmissionEvaluation | None) -> AdmissionChips:
        """Project one evaluation, or the ``unknown`` read when there is none.

        ``.get`` on ``detail``, not ``detail[...]``: a requirement this tournament
        switched off is present as ``not_applicable`` with an EMPTY detail, and the
        chips must then read ``None`` -- the value they have carried all along for a
        tournament that does not require the thing. An empty dict in that slot
        would make the client render an empty Subscription column instead of no
        column at all.
        """
        if evaluation is None:
            return cls(admission=AdmissionRead.unknown())
        profile = evaluation.requirement(OPEN_PROFILE_KEY)
        subscription = evaluation.requirement(SUBSCRIPTION_KEY)
        return cls(
            admission=AdmissionRead.of(evaluation),
            profiles_open=profile.detail.get("profiles_open") if profile is not None else None,
            subscription_outcome=subscription.detail.get("outcome") if subscription is not None else None,
            subscription_verdicts=subscription.detail.get("providers") if subscription is not None else None,
        )


def registration_read_loaders() -> tuple[Any, ...]:
    """Eager-load options every ``_reg_to_read`` caller must apply.

    Colocated with the serializer on purpose: these relationships are documented as
    "never lazy-loaded in async code", and forgetting one does not raise here — it
    silently serializes ``user_id=None`` or ``team=None``. Keeping the list next to
    the code that reads it is what stops the two from drifting.

    ``registration_load_options()`` is folded in because the same rows are handed
    to the roster engine for their ranks: it reads roles, their heroes and the
    member's player, and a lazy load there would raise ``MissingGreenlet``.
    """
    return (
        *registration_load_options(),
        selectinload(models.BalancerRegistration.registration_team),
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
    is_open: bool,
    subrole_catalog: dict[str, list[dict[str, str]]] | None = None,
    subscription_requirement: dict[str, Any] | None = None,
) -> RegistrationFormRead:
    """``subscription_requirement`` is the WORKSPACE's rule, passed in by the caller.

    An argument rather than a lookup because this stays sync and must not issue a
    second round trip per call; the async RPC handler already has the session and
    fetches it once alongside the sub-role catalog.

    ``is_open`` is passed in for the same reason, and is now DERIVED from the
    tournament's REGISTRATION schedule window rather than read off the form.
    """
    return RegistrationFormRead(
        id=form.id,
        tournament_id=form.tournament_id,
        workspace_id=form.workspace_id,
        is_open=is_open,
        auto_approve=form.auto_approve,
        require_open_profile=form.require_open_profile,
        open_profile_scope=form.open_profile_scope,
        show_ranks=form.show_ranks,
        max_substitutes=form.max_substitutes,
        require_subscription=form.require_subscription,
        subscription_stage=form.subscription_stage,
        subscription_requirement_json=subscription_requirement or {},
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
    admission: AdmissionRead | None = None,
    profiles_open: bool | None = None,
    subscription_outcome: str | None = None,
    subscription_verdicts: dict[str, Any] | None = None,
    roster: PlayerRoster | None = None,
) -> RegistrationRead:
    """Serialize a registration for public API responses.

    Everything the registration form collects is roster data: the participants
    table renders a column per built-in field and per organizer-defined custom
    field, and the organizer chooses what to ask. ``custom_fields_json`` used to
    be stripped here for anonymous callers, which left every custom column on
    the public roster permanently empty while the header advertised it.

    Free-text ``notes`` and smurf tags are public for the same reason: notes are
    the participant-facing "anything you'd like organizers to know" field, and
    declared alternate battle tags are the anti-smurf transparency the roster
    exists to surface.

    ``admission`` defaults to ``AdmissionRead.unknown()`` rather than staying
    ``None``: the single-registration write paths (create, self-update) return a
    read the caller refetches anyway, and a nullable object here would put a null
    branch in every consumer -- which is how the five client-side re-derivations
    of this answer got started.
    """
    if roster is not None:
        # The roster, not the rows: under ``all_roles``/``forced`` the engine
        # synthesizes the roles the DB never stored, and the public table used to
        # publish one role while the balancer and the draft acted on three.
        # ``is_primary``/``priority`` come from the same place for the same reason.
        roles = [
            RegistrationRoleRead(
                role=entry.role.slot_code,
                subrole=entry.subrole,
                is_primary=entry.is_primary,
                priority=entry.priority,
                # The engine's answer, or nothing: a role it did not rate is a role
                # the player cannot be picked on, and printing the raw column there
                # advertised a rating the balancer would never honour.
                rank_value=roster.rank_on(entry.role) if show_ranks else None,
                top_heroes=[hero.slug for hero in entry.top_heroes],
            )
            for entry in sorted(roster.roles, key=lambda entry: (not entry.is_primary, entry.priority))
        ]
    else:
        roles = [
            RegistrationRoleRead(
                role=r.role,
                subrole=r.subrole,
                is_primary=r.is_primary,
                priority=r.priority,
                rank_value=None,
                top_heroes=[he.hero.slug for he in sorted(r.hero_entries, key=lambda he: he.priority)],
            )
            for r in sorted(reg.roles or [], key=lambda r: (not r.is_primary, r.priority))
        ]

    # ``registration_team`` must be eager-loaded by the caller: the model marks it
    # "never lazy-loaded in async code", and a lazy load here would raise
    # MissingGreenlet inside a response serializer. Absent relationship == no team,
    # which is also the honest answer for every solo registration.
    team_row = reg.__dict__.get("registration_team")
    team = (
        RegistrationTeamBrief(
            id=team_row.id,
            name=team_row.name,
            status=team_row.status,
            slot_code=reg.team_slot_code,
            is_substitute=bool(reg.is_substitute),
            is_captain=team_row.captain_registration_id == reg.id,
        )
        if team_row is not None
        else None
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
        boosty_nick=getattr(reg, "boosty_nick", None),
        stream_pov=reg.stream_pov,
        roles=roles,
        notes=reg.notes,
        custom_fields_json=reg.custom_fields_json,
        status=reg.status,
        status_meta=(status_meta_map["registration"].get(reg.status) if status_meta_map is not None else None)
        or build_unknown_status_meta("registration", reg.status),
        balancer_status=reg.balancer_status,
        balancer_status_meta=(
            status_meta_map["balancer"].get(reg.balancer_status) if status_meta_map is not None else None
        )
        or build_unknown_status_meta("balancer", reg.balancer_status),
        checked_in=reg.checked_in,
        admission=admission if admission is not None else AdmissionRead.unknown(),
        profiles_open=profiles_open,
        subscription_outcome=subscription_outcome,
        subscription_verdicts=subscription_verdicts,
        team=team,
        submitted_at=reg.submitted_at,
        reviewed_at=reg.reviewed_at,
    )


async def _public_rosters(session: AsyncSession, registrations: Sequence[Any]) -> dict[int, PlayerRoster]:
    """Resolved rosters for the public participants list.

    Always resolved, rank publication or not: the ROLE list itself comes from the
    roster (``all_roles``/``forced`` synthesize roles no DB row names), and
    ``show_ranks`` only decides whether ``_reg_to_read`` prints the number.

    The workspace is resolved here rather than pushed onto all five call sites:
    every caller already has the registrations, and one tournament's worth of
    them shares a tenancy. Rows must carry ``registration_read_loaders()``, which
    folds in everything the engine reads.
    """
    if not registrations:
        return {}
    tournament_id = registrations[0].tournament_id
    workspace_id = await _resolve_tournament_workspace(session, tournament_id)
    return await roster_engine.resolve(session, registrations, workspace_id=workspace_id, tournament_id=tournament_id)


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

    History is capped in SQL (``ROW_NUMBER`` after deduping substitutions)
    and the pre-cap count is returned as a window column. Python still
    deduplicates and caps as a safety net; tests that mock 5-column rows keep
    the Python count.

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
    # Duplicate (player, tournament) rows (substitutions) are collapsed first; then
    # each player keeps the most recent ``HISTORY_LIMIT`` tournaments and a window
    # count of the true unique total.
    history_ranked = (
        sa.select(
            models.Player.tournament_id.label("tournament_id"),
            models.WorkspaceMember.player_id.label("player_id"),
            models.Player.role,
            models.Player.rank,
            models.Tournament.name.label("tournament_name"),
            models.Tournament.start_date.label("start_date"),
            sa.func.row_number()
            .over(
                partition_by=(models.WorkspaceMember.player_id, models.Player.tournament_id),
                order_by=(
                    models.Tournament.start_date.desc().nullslast(),
                    models.Tournament.id.desc(),
                    models.Player.id.desc(),
                ),
            )
            .label("dup_rn"),
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
    ).subquery("history_ranked")
    history_deduped = (
        sa.select(
            history_ranked.c.tournament_id,
            history_ranked.c.player_id,
            history_ranked.c.role,
            history_ranked.c.rank,
            history_ranked.c.tournament_name,
            sa.func.row_number()
            .over(
                partition_by=history_ranked.c.player_id,
                order_by=(
                    history_ranked.c.start_date.desc().nullslast(),
                    history_ranked.c.tournament_id.desc(),
                ),
            )
            .label("hist_rn"),
            sa.func.count().over(partition_by=history_ranked.c.player_id).label("history_count"),
        ).where(history_ranked.c.dup_rn == 1)
    ).subquery("history_deduped")
    result = await session.execute(
        sa.select(
            history_deduped.c.tournament_id,
            history_deduped.c.player_id,
            history_deduped.c.role,
            history_deduped.c.rank,
            history_deduped.c.tournament_name,
            history_deduped.c.history_count,
        )
        .where(history_deduped.c.hist_rn <= HISTORY_LIMIT)
        .order_by(history_deduped.c.player_id, history_deduped.c.hist_rn)
    )
    rows = result.all()

    # --- Step 3: resolve division-grid versions for every distinct historical
    # tournament in one batch -- a constant number of Redis/DB round trips no
    # matter how many distinct tournaments this player's history spans (was a
    # sequential per-tournament await; see get_effective_division_grid_version_ids's
    # docstring for why that can't just be asyncio.gather'd instead).
    tournament_ids_with_rank = {row[0] for row in rows if row[3] is not None}
    tournament_to_version = await get_effective_division_grid_version_ids(
        session, workspace_id, tournament_ids_with_rank
    )

    distinct_version_ids = {vid for vid in tournament_to_version.values() if vid is not None}

    # Runtime grids (for division-number resolution) come from the cached snapshots.
    snapshot_by_version = await load_division_grid_snapshots(session, distinct_version_ids)
    runtime_grid_by_version: dict[int, DivisionGrid] = {
        vid: (snapshot_by_version[vid].to_runtime_grid() if vid in snapshot_by_version else load_runtime_grid(None))
        for vid in distinct_version_ids
    }

    # Full version metadata for the response map — cached (see
    # load_division_grid_version_read_payloads's docstring): a query only runs
    # for the versions this cache hasn't seen yet, not on every rebuild.
    version_read_by_id: dict[int, DivisionGridVersionRead] = {}
    if distinct_version_ids:
        version_payloads = await load_division_grid_version_read_payloads(session, distinct_version_ids)
        for vid, payload in version_payloads.items():
            version_read_by_id[vid] = DivisionGridVersionRead.model_validate(payload)

    # --- Step 4: build per-registration history (deduped by tournament, capped) ---
    history_map: dict[int, list[TournamentHistoryEntry]] = {}
    count_map: dict[int, int] = {}
    seen_per_reg: dict[int, set[int]] = {}

    for row in rows:
        tournament_id = row[0]
        user_id = row[1]
        role = row[2]
        rank = row[3]
        tournament_name = row[4]
        sql_history_count = int(row[5]) if len(row) > 5 and row[5] is not None else None
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
            if sql_history_count is None:
                count_map[reg_id] = count_map.get(reg_id, 0) + 1
            else:
                count_map[reg_id] = sql_history_count
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

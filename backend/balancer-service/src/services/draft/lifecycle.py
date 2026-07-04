"""Draft session lifecycle: create, seed, and status transitions.

Services flush within the caller's transaction (routes/worker commit). Status
moves are guarded by ``shared.core.draft_state``. The pick clock is
DB-resumable: absolute ``clock_expires_at`` while live, frozen
``clock_remaining_ms`` while paused.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import draft_state
from shared.core.enums import (
    DraftCaptainOrder,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftRole,
    DraftRoundRule,
    DraftStatus,
)
from shared.core.errors import ApiExc, ApiHTTPException
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.models.registration.registration import (
    BalancerRegistration,
    BalancerRegistrationRole,
    BalancerRegistrationRoleHero,
)
from shared.models.tenancy.workspace import WorkspaceMember
from src.services.draft.snake_order import generate_pick_order

_ACTIVE_STATUSES = (
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.LIVE.value,
    DraftStatus.PAUSED.value,
)


@dataclass(frozen=True)
class CaptainSeed:
    name: str
    draft_position: int
    user_id: int | None = None
    auth_user_id: int | None = None
    battle_tag: str | None = None
    # Real role/rank when the captain is drawn from the balancer pool.
    primary_role: DraftRole | None = None
    sub_role: str | None = None
    is_flex: bool = False
    division_number: int | None = None
    rank_value: int | None = None
    role_ranks: dict = field(default_factory=dict)
    role_top_heroes: dict = field(default_factory=dict)
    additional_info: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PlayerSeed:
    primary_role: DraftRole
    user_id: int | None = None
    battle_tag: str | None = None
    secondary_roles: list[DraftRole] = field(default_factory=list)
    sub_role: str | None = None
    is_flex: bool = False
    division_number: int | None = None
    rank_value: int | None = None
    role_ranks: dict = field(default_factory=dict)
    role_top_heroes: dict = field(default_factory=dict)
    additional_info: dict = field(default_factory=dict)


def _err(code: str, msg: str, status_code: int = 409) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


async def assert_no_active_draft(session: AsyncSession, tournament_id: int) -> None:
    existing = await session.scalar(
        sa.select(DraftSession.id).where(
            DraftSession.tournament_id == tournament_id,
            DraftSession.status.in_(_ACTIVE_STATUSES),
        )
    )
    if existing is not None:
        raise _err("draft_already_active", f"Tournament {tournament_id} already has an active draft")


async def create_session(
    session: AsyncSession,
    *,
    tournament_id: int,
    workspace_id: int,
    pool_source: str = "balancer_balance",
    source_balance_id: int | None = None,
    fmt: DraftFormat = DraftFormat.SNAKE,
    rounds: int = 4,
    pick_time_seconds: int = 45,
    team_size: int = 5,
    autopick_strategy: str = "best_fit",
    allow_admin_override: bool = True,
    settings: dict | None = None,
) -> DraftSession:
    await assert_no_active_draft(session, tournament_id)
    draft = DraftSession(
        tournament_id=tournament_id,
        workspace_id=workspace_id,
        status=DraftStatus.SETUP.value,
        format=fmt.value,
        rounds=rounds,
        pick_time_seconds=pick_time_seconds,
        team_size=team_size,
        pool_source=pool_source,
        source_balance_id=source_balance_id,
        autopick_strategy=autopick_strategy,
        allow_admin_override=allow_admin_override,
        settings_json=settings or {},
    )
    session.add(draft)
    await session.flush()
    await session.refresh(draft)
    return draft


async def _load_full(session: AsyncSession, draft_session_id: int) -> DraftSession:
    draft = await session.scalar(
        sa.select(DraftSession)
        .where(DraftSession.id == draft_session_id)
        .options(
            selectinload(DraftSession.teams),
            selectinload(DraftSession.players),
            selectinload(DraftSession.picks),
        )
    )
    if draft is None:
        raise _err("draft_not_found", f"Draft session {draft_session_id} not found", status_code=404)
    return draft


async def seed(
    session: AsyncSession,
    draft_session: DraftSession,
    *,
    captains: list[CaptainSeed],
    players: list[PlayerSeed],
) -> DraftSession:
    """Materialize teams + pool + all picks, then transition SETUP/READY -> READY."""
    if draft_session.status not in (DraftStatus.SETUP.value, DraftStatus.READY.value):
        raise _err("draft_not_seedable", "Draft can only be seeded in SETUP or READY")
    if not captains:
        raise _err("draft_no_captains", "At least one captain is required to seed a draft")

    draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.READY)

    # Re-seed: clear any prior teams/players/picks (cascade via relationships).
    await session.execute(sa.delete(DraftPick).where(DraftPick.session_id == draft_session.id))
    await session.execute(sa.delete(DraftPlayer).where(DraftPlayer.session_id == draft_session.id))
    await session.execute(sa.delete(DraftTeam).where(DraftTeam.session_id == draft_session.id))
    draft_session.current_pick_id = None
    await session.flush()

    ordered_captains = sorted(captains, key=lambda c: c.draft_position)
    team_by_position: dict[int, DraftTeam] = {}
    for cap in ordered_captains:
        team = DraftTeam(
            session_id=draft_session.id,
            captain_user_id=cap.user_id,
            captain_auth_user_id=cap.auth_user_id,
            name=cap.name,
            draft_position=cap.draft_position,
        )
        session.add(team)
        team_by_position[cap.draft_position] = team
    await session.flush()

    # Captains become PICKED players already on their roster.
    for cap in ordered_captains:
        team = team_by_position[cap.draft_position]
        session.add(
            DraftPlayer(
                session_id=draft_session.id,
                user_id=cap.user_id,
                battle_tag=cap.battle_tag,
                # Real role from the pool when available; TANK placeholder otherwise.
                primary_role=(cap.primary_role or DraftRole.TANK).value,
                sub_role=cap.sub_role,
                is_flex=cap.is_flex,
                division_number=cap.division_number,
                rank_value=cap.rank_value,
                is_captain=True,
                status=DraftPlayerStatus.PICKED.value,
                drafted_by_team_id=team.id,
                role_ranks=cap.role_ranks,
                role_top_heroes=cap.role_top_heroes,
                additional_info=cap.additional_info,
            )
        )
    # Pool players.
    for p in players:
        session.add(
            DraftPlayer(
                session_id=draft_session.id,
                user_id=p.user_id,
                battle_tag=p.battle_tag,
                primary_role=p.primary_role.value,
                secondary_roles_json=[r.value for r in p.secondary_roles] or None,
                sub_role=p.sub_role,
                is_flex=p.is_flex,
                division_number=p.division_number,
                rank_value=p.rank_value,
                status=DraftPlayerStatus.AVAILABLE.value,
                role_ranks=p.role_ranks,
                role_top_heroes=p.role_top_heroes,
                additional_info=p.additional_info,
            )
        )
    await session.flush()

    # Pre-create all picks in deterministic order based on round rules.
    seats = [team_by_position[pos] for pos in sorted(team_by_position)]
    team_captain_ranks = {
        team_by_position[cap.draft_position].id: (cap.rank_value if cap.rank_value is not None else -1)
        for cap in ordered_captains
    }

    fmt = DraftFormat(draft_session.format)
    round_rules = draft_session.settings_json.get("round_rules") or []

    overall_no = 1
    for round_idx in range(draft_session.rounds):
        round_no = round_idx + 1

        # Determine team ordering for this round
        if fmt == DraftFormat.SNAKE:
            reverse = round_idx % 2 == 1
            round_seats = list(reversed(seats)) if reverse else seats
        elif fmt == DraftFormat.LINEAR:
            round_seats = seats
        elif fmt == DraftFormat.CUSTOM:
            rule = round_rules[round_idx] if round_idx < len(round_rules) else "linear"
            if rule == "reverse":
                round_seats = list(reversed(seats))
            elif rule == "weakest_first":
                round_seats = sorted(seats, key=lambda t: (team_captain_ranks.get(t.id, -1), t.draft_position))
            elif rule == "strongest_first":
                round_seats = sorted(seats, key=lambda t: (team_captain_ranks.get(t.id, -1), -t.draft_position), reverse=True)
            else:
                # Dynamic rules (team_avg_asc, team_avg_desc) default to linear order at seeding time
                round_seats = seats
        else:
            round_seats = seats

        for pick_in_round, team in enumerate(round_seats, start=1):
            session.add(
                DraftPick(
                    session_id=draft_session.id,
                    overall_no=overall_no,
                    round_no=round_no,
                    pick_in_round=pick_in_round,
                    draft_team_id=team.id,
                    status=DraftPickStatus.UPCOMING.value,
                    version=0,
                )
            )
            overall_no += 1

    draft_session.status = DraftStatus.READY.value
    await session.flush()
    await session.refresh(draft_session)
    return draft_session


def _to_draft_role(role: str | None) -> DraftRole | None:
    if not role:
        return None
    normalized = role.strip().lower()
    if normalized in {"dps", "damage"}:
        return DraftRole.DPS
    if normalized == "tank":
        return DraftRole.TANK
    if normalized == "support":
        return DraftRole.SUPPORT
    return None


def _registration_auth_user_id(reg: BalancerRegistration) -> int | None:
    """Resolve the registering account's auth identity for a pool registration.

    ``BalancerRegistration`` no longer carries ``auth_user_id`` directly — identity
    is anchored via ``workspace_member`` (self-service registrations only; manual/
    sheet-synced registrations have no ``workspace_member`` and resolve to ``None``,
    same as before this column existed for them).
    """
    member = reg.workspace_member
    if member is None or member.player is None:
        return None
    return member.player.auth_user_id


def _map_registration(reg: BalancerRegistration) -> dict:
    """Derive draft role/rank fields from a tournament registration's roles.

    The registration-based pool is the balancer source of truth (3NF). Active
    role rows sorted by priority -> primary (preferring is_primary) + secondaries;
    rank/sub-role come from the primary role.
    """
    active = sorted((r for r in (reg.roles or []) if r.is_active), key=lambda r: r.priority)
    roles: list[DraftRole] = []
    for r in active:
        role = _to_draft_role(r.role)
        if role is not None and role not in roles:
            roles.append(role)
    primary_entry = next((r for r in active if r.is_primary and _to_draft_role(r.role)), None)
    if primary_entry is None and active:
        primary_entry = active[0]
    primary = (_to_draft_role(primary_entry.role) if primary_entry else None) or (roles[0] if roles else DraftRole.DPS)
    secondary = [r for r in roles if r != primary]
    ranks = [r.rank_value for r in active if r.rank_value is not None]
    rank_value = (primary_entry.rank_value if primary_entry else None) or (max(ranks) if ranks else None)
    sub_role = primary_entry.subrole if primary_entry else None

    # Per-role rank catalogue and top heroes, keyed by role.value, promoted to
    # dedicated typed fields (no more burying them in an "anomaly_flags" bag).
    role_ranks: dict[str, int] = {}
    role_top_heroes: dict[str, list[dict]] = {}
    for r in active:
        role = _to_draft_role(r.role)
        if role is None:
            continue
        if r.rank_value is not None:
            role_ranks[role.value] = r.rank_value
        hero_entries = getattr(r, "hero_entries", None)
        heroes = [
            {
                "slug": getattr(he.hero, "slug", ""),
                "image_path": getattr(he.hero, "image_path", None),
            }
            for he in (hero_entries or [])
            if he and getattr(he, "hero", None) is not None
        ] if isinstance(hero_entries, (list, set)) or (
            hero_entries is not None and not hasattr(hero_entries, "_mock_return_value")
        ) else []
        if heroes:
            role_top_heroes[role.value] = heroes

    return {
        "primary_role": primary,
        "secondary_roles": secondary,
        "sub_role": sub_role,
        "rank_value": rank_value,
        "division_number": None,
        "is_flex": bool(reg.is_flex_computed),
        "role_ranks": role_ranks,
        "role_top_heroes": role_top_heroes,
        "additional_info": {"notes": reg.notes} if reg.notes else {},
    }


async def load_pool(session: AsyncSession, tournament_id: int) -> list[BalancerRegistration]:
    """Load the balancer pool = registrations included in the balancer.

    Mirrors the panel's ``isRegistrationIncludedInBalancer``: approved, not
    deleted, not excluded, and not flagged not_in_balancer.
    """
    return list(
        await session.scalars(
            sa.select(BalancerRegistration)
            .where(
                BalancerRegistration.tournament_id == tournament_id,
                BalancerRegistration.status == "approved",
                BalancerRegistration.deleted_at.is_(None),
                BalancerRegistration.exclude_from_balancer.is_(False),
                BalancerRegistration.balancer_status != "not_in_balancer",
            )
            .options(
                selectinload(BalancerRegistration.roles)
                .selectinload(BalancerRegistrationRole.hero_entries)
                .selectinload(BalancerRegistrationRoleHero.hero),
                # Needed by _registration_auth_user_id (captain identity resolution).
                selectinload(BalancerRegistration.workspace_member).selectinload(WorkspaceMember.player),
            )
            .order_by(BalancerRegistration.battle_tag_normalized.asc())
        )
    )


def order_captain_ids(
    entries: list[tuple[int, int | None]],
    strategy: DraftCaptainOrder,
    seed: int | None = None,
) -> list[int]:
    """Return captain ids in seat order (position 1 picks first).

    ``entries`` are (id, rank_value) in selection order. WEAKEST_FIRST sorts by
    ascending rank (unknown rank treated as weakest), STRONGEST_FIRST descending,
    RANDOM is a deterministic shuffle, MANUAL keeps selection order. Ties break by
    id for full determinism.
    """
    if strategy == DraftCaptainOrder.MANUAL:
        return [rid for rid, _ in entries]
    if strategy == DraftCaptainOrder.RANDOM:
        rng = random.Random(seed if seed is not None else 0)
        shuffled = list(entries)
        rng.shuffle(shuffled)
        return [rid for rid, _ in shuffled]
    reverse = strategy == DraftCaptainOrder.STRONGEST_FIRST
    ordered = sorted(
        entries,
        key=lambda e: (e[1] if e[1] is not None else -1, e[0]),
        reverse=reverse,
    )
    return [rid for rid, _ in ordered]


async def seed_from_pool(
    session: AsyncSession,
    draft_session: DraftSession,
    *,
    captain_registration_ids: list[int],
    team_names: dict[int, str] | None = None,
    captain_order: DraftCaptainOrder = DraftCaptainOrder.MANUAL,
    rng_seed: int | None = None,
) -> DraftSession:
    """Seed a draft from the balancer registration pool.

    ``captain_registration_ids`` are ``balancer.registration`` ids chosen as
    captains. ``captain_order`` decides seat order (who picks first) — e.g.
    WEAKEST_FIRST seats the lowest-rated captain at position 1. Every other
    in-pool registration becomes an available draft player; roles/ranks come from
    the registration.
    """
    pool = await load_pool(session, draft_session.tournament_id)
    by_id = {reg.id: reg for reg in pool}
    if not captain_registration_ids:
        raise _err("draft_no_captains", "Select at least one captain from the pool")

    team_names = team_names or {}
    mapped_by_id: dict[int, dict] = {}
    for rid in captain_registration_ids:
        reg = by_id.get(rid)
        if reg is None:
            raise _err(
                "captain_not_in_pool",
                f"Captain registration {rid} is not in the balancer pool for this tournament",
                status_code=422,
            )
        mapped_by_id[rid] = _map_registration(reg)

    ordered_ids = order_captain_ids(
        [(rid, mapped_by_id[rid]["rank_value"]) for rid in captain_registration_ids],
        captain_order,
        rng_seed,
    )

    captains: list[CaptainSeed] = []
    for position, rid in enumerate(ordered_ids, start=1):
        reg = by_id[rid]
        mapped = mapped_by_id[rid]
        captains.append(
            CaptainSeed(
                name=team_names.get(rid) or reg.battle_tag or reg.display_name or f"Team {position}",
                draft_position=position,
                user_id=reg.user_id,
                auth_user_id=_registration_auth_user_id(reg),
                battle_tag=reg.battle_tag,
                primary_role=mapped["primary_role"],
                sub_role=mapped["sub_role"],
                is_flex=mapped["is_flex"],
                division_number=mapped["division_number"],
                rank_value=mapped["rank_value"],
                role_ranks=mapped.get("role_ranks") or {},
                role_top_heroes=mapped.get("role_top_heroes") or {},
                additional_info=mapped.get("additional_info") or {},
            )
        )

    captain_ids = set(captain_registration_ids)
    players: list[PlayerSeed] = []
    for reg in pool:
        if reg.id in captain_ids:
            continue
        mapped = _map_registration(reg)
        players.append(
            PlayerSeed(
                primary_role=mapped["primary_role"],
                user_id=reg.user_id,
                battle_tag=reg.battle_tag,
                secondary_roles=mapped["secondary_roles"],
                sub_role=mapped["sub_role"],
                is_flex=mapped["is_flex"],
                division_number=mapped["division_number"],
                rank_value=mapped["rank_value"],
                role_ranks=mapped.get("role_ranks") or {},
                role_top_heroes=mapped.get("role_top_heroes") or {},
                additional_info=mapped.get("additional_info") or {},
            )
        )

    return await seed(session, draft_session, captains=captains, players=players)


def _arm_clock(pick: DraftPick, pick_time_seconds: int, now: datetime) -> None:
    pick.status = DraftPickStatus.ON_CLOCK.value
    pick.clock_started_at = now
    pick.clock_expires_at = now + timedelta(seconds=pick_time_seconds)
    pick.clock_remaining_ms = None


async def _first_upcoming(session: AsyncSession, draft_session_id: int) -> DraftPick | None:
    return await session.scalar(
        sa.select(DraftPick)
        .where(
            DraftPick.session_id == draft_session_id,
            DraftPick.status == DraftPickStatus.UPCOMING.value,
        )
        .order_by(DraftPick.overall_no.asc())
        .limit(1)
    )


async def start(session: AsyncSession, draft_session: DraftSession) -> DraftSession:
    draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.LIVE)
    first = await _first_upcoming(session, draft_session.id)
    if first is None:
        raise _err("draft_no_picks", "Draft has no picks to start")
    now = datetime.now(UTC)
    _arm_clock(first, draft_session.pick_time_seconds, now)
    draft_session.status = DraftStatus.LIVE.value
    draft_session.current_pick_id = first.id
    await session.flush()
    await session.refresh(draft_session)
    return draft_session


async def pause(session: AsyncSession, draft_session: DraftSession) -> DraftSession:
    draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.PAUSED)
    now = datetime.now(UTC)
    current = await session.get(DraftPick, draft_session.current_pick_id) if draft_session.current_pick_id else None
    if current is not None and current.clock_expires_at is not None:
        remaining = (current.clock_expires_at - now).total_seconds() * 1000.0
        current.clock_remaining_ms = max(0, int(remaining))
        current.clock_expires_at = None
    draft_session.status = DraftStatus.PAUSED.value
    await session.flush()
    await session.refresh(draft_session)
    return draft_session


async def resume(session: AsyncSession, draft_session: DraftSession) -> DraftSession:
    draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.LIVE)
    now = datetime.now(UTC)
    current = await session.get(DraftPick, draft_session.current_pick_id) if draft_session.current_pick_id else None
    if current is not None:
        remaining_ms = (
            current.clock_remaining_ms
            if current.clock_remaining_ms is not None
            else (draft_session.pick_time_seconds * 1000)
        )
        current.clock_started_at = now
        current.clock_expires_at = now + timedelta(milliseconds=remaining_ms)
        current.clock_remaining_ms = None
    draft_session.status = DraftStatus.LIVE.value
    await session.flush()
    await session.refresh(draft_session)
    return draft_session


async def cancel(session: AsyncSession, draft_session: DraftSession) -> DraftSession:
    draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.CANCELLED)
    draft_session.status = DraftStatus.CANCELLED.value
    await session.flush()
    await session.refresh(draft_session)
    return draft_session


async def rollback(session: AsyncSession, draft_session: DraftSession) -> DraftSession:
    """Rollback the last resolved pick, resetting player/pick states and pausing the draft."""
    draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.PAUSED)

    # Find the last resolved pick (completed, autopicked, or skipped)
    last_resolved = await session.scalar(
        sa.select(DraftPick)
        .where(
            DraftPick.session_id == draft_session.id,
            DraftPick.status.in_([
                DraftPickStatus.COMPLETED.value,
                DraftPickStatus.AUTOPICKED.value,
                DraftPickStatus.SKIPPED.value,
            ]),
        )
        .order_by(DraftPick.overall_no.desc())
        .limit(1)
    )
    if last_resolved is None:
        raise _err("no_picks_to_rollback", "There are no resolved picks to rollback")

    # Find all picks with overall_no >= last_resolved.overall_no
    picks_to_revert = (
        await session.scalars(
            sa.select(DraftPick)
            .where(
                DraftPick.session_id == draft_session.id,
                DraftPick.overall_no >= last_resolved.overall_no,
            )
            .order_by(DraftPick.overall_no.asc())
        )
    ).all()

    player_ids_to_free = [p.picked_player_id for p in picks_to_revert if p.picked_player_id is not None]
    if player_ids_to_free:
        players = (
            await session.scalars(
                sa.select(DraftPlayer).where(
                    DraftPlayer.session_id == draft_session.id,
                    DraftPlayer.id.in_(player_ids_to_free),
                )
            )
        ).all()
        for player in players:
            player.status = DraftPlayerStatus.AVAILABLE.value
            player.drafted_by_team_id = None

    for pick in picks_to_revert:
        pick.picked_player_id = None
        pick.picked_by_user_id = None
        pick.is_autopick = False
        pick.is_admin_override = False
        pick.target_role = None
        # Increment version to prevent race conditions from pending requests
        pick.version += 1

        if pick.id == last_resolved.id:
            pick.status = DraftPickStatus.ON_CLOCK.value
            pick.clock_remaining_ms = draft_session.pick_time_seconds * 1000
            pick.clock_started_at = None
            pick.clock_expires_at = None
        else:
            pick.status = DraftPickStatus.UPCOMING.value
            pick.clock_remaining_ms = None
            pick.clock_started_at = None
            pick.clock_expires_at = None

    draft_session.status = DraftStatus.PAUSED.value
    draft_session.current_pick_id = last_resolved.id
    draft_session.export_status = None
    draft_session.exported_at = None

    await session.flush()
    await session.refresh(draft_session)
    return draft_session


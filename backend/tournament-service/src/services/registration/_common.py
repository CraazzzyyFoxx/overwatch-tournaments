"""Shared helpers for the registration admin subsystems.

Cross-cutting building blocks used by more than one of the admin modules
(``sheet_parsing`` / ``sheet_sync`` / ``rank_autofill`` / ``lifecycle`` /
``export``): tournament/form lookups, division-grid resolution, role
replacement and the balancer-status verdict.

Nothing here derives a role's rank or playability any more: that answer comes
from :mod:`shared.services.roster`, and the ``ready``/``incomplete`` verdict is
a straight read of :attr:`~shared.domain.roster.PlayerRoster.is_ranked_complete`.
What stays local is the WRITE side (``apply_all_roles`` /
``replace_registration_roles``), which the engine never touches.
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import get_builtin_status_values, is_balancer_status_excluded
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES, normalize_sub_role
from shared.domain.roster import FlexRoleMode, PlayerRoster
from shared.hero_catalog import HeroCatalog
from shared.repository import RegistrationFormRepository, TournamentRepository
from shared.services.realtime import Resource, Scope, emit
from shared.services.roster import roster_engine
from src import models
from src.domain.registration.utils import DEFAULT_SORT_PRIORITY_SENTINEL
from src.schemas.registration import CustomFieldDefinition

VALID_REGISTRATION_STATUSES = get_builtin_status_values("registration")
VALID_BALANCER_STATUSES = get_builtin_status_values("balancer")

# The only two balancer statuses the system derives from role/rank
# completeness -- every other status (not_in_balancer, excluded, any custom
# slug) is exclusively admin-managed and must never be touched by
# `sync_included_balancer_status`.
AUTO_MANAGED_BALANCER_STATUSES = frozenset({"incomplete", "ready"})
NOT_ADDED_BALANCER_STATUS = "not_in_balancer"
EXCLUDED_BALANCER_STATUS = "excluded"


def get_tournament_grid_from_rows(
    tournament_row: models.Tournament | None,
    workspace_row: models.Workspace | None,
    fallback_version: models.DivisionGridVersion | None = None,
) -> DivisionGrid:
    if tournament_row and tournament_row.division_grid_version is not None:
        return load_runtime_grid(tournament_row.division_grid_version)
    if workspace_row and workspace_row.default_division_grid_version is not None:
        return load_runtime_grid(workspace_row.default_division_grid_version)
    return load_runtime_grid(fallback_version)


def form_custom_field_defs(
    form: models.BalancerRegistrationForm | None,
) -> list[CustomFieldDefinition]:
    """Coerce a form's stored custom-field JSON into typed definitions."""
    raw = getattr(form, "custom_fields_json", None) or []
    defs: list[CustomFieldDefinition] = []
    for value in raw:
        if isinstance(value, CustomFieldDefinition):
            defs.append(value)
        else:
            defs.append(CustomFieldDefinition.model_validate(value or {}))
    return defs


def apply_all_roles(
    entries: list[models.BalancerRegistrationRole],
    *,
    force_primary: bool,
) -> list[models.BalancerRegistrationRole]:
    """Backfill the role set to all three, optionally forcing every role primary.

    Both non-optional modes need the SET normalized, whichever path produced the
    entries — public form, admin panel, API key or Google Sheets sync.
    Normalizing here rather than rejecting an incomplete payload is what makes
    that hold for a stale client and for the sheet sync, neither of which knows
    about the mode.

    ``force_primary`` separates the two modes: ``forced`` marks every role
    primary (yielding ``PlayerRoster.is_full_flex``), ``all_roles`` leaves the registrant's
    own choice alone and backfills the missing roles as non-primary. It cannot
    invent that choice, so a payload naming no priority stays invalid — see
    ``validation.py``.

    Only the role SET and (under ``force_primary``) ``is_primary`` are touched.
    ``is_active`` and ``rank_value`` stay exactly as the calling path set them:
    the max-rank policy is derived at read time, because the public form submits
    no ranks at all and ``rank_autofill`` would overwrite anything flattened
    into the rows.
    """
    present = {entry.role for entry in entries}
    result = list(entries)
    result.extend(
        models.BalancerRegistrationRole(role=role_code)
        for role_code in REGISTRATION_ROLE_CODES
        if role_code not in present
    )
    for priority, entry in enumerate(result):
        if force_primary:
            entry.is_primary = True
        entry.priority = priority
    return result


def replace_registration_roles(
    registration: models.BalancerRegistration,
    roles: list[dict[str, Any]],
    *,
    hero_catalog: HeroCatalog | None = None,
    max_heroes: int | None = None,
    mode: FlexRoleMode = "optional",
) -> None:
    existing_by_role = {existing.role: existing for existing in registration.roles}
    next_roles: list[models.BalancerRegistrationRole] = []
    seen_roles: set[str] = set()

    for index, role in enumerate(sorted(roles, key=lambda item: item.get("priority", DEFAULT_SORT_PRIORITY_SENTINEL))):
        role_code = role.get("role")
        if role_code not in {"tank", "dps", "support"} or role_code in seen_roles:
            continue
        seen_roles.add(role_code)

        registration_role = existing_by_role.pop(role_code, None)
        if registration_role is None:
            registration_role = models.BalancerRegistrationRole(role=role_code)

        registration_role.role = role_code
        registration_role.subrole = normalize_sub_role(role.get("subrole"))
        registration_role.is_primary = bool(role.get("is_primary", index == 0))
        registration_role.priority = index
        registration_role.rank_value = role.get("rank_value")
        registration_role.is_active = bool(role.get("is_active", role.get("rank_value") is not None))

        if hero_catalog is not None:
            top_heroes = role.get("top_heroes")
            if top_heroes is not None:
                from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, build_hero_entries

                registration_role.hero_entries = build_hero_entries(
                    top_heroes,
                    hero_catalog=hero_catalog,
                    max_heroes=max_heroes or DEFAULT_MAX_TOP_HEROES,
                )

        next_roles.append(registration_role)

    if mode in ("all_roles", "forced"):
        next_roles = apply_all_roles(next_roles, force_primary=mode == "forced")

    registration.roles[:] = next_roles


async def resolve_roster(
    session: AsyncSession,
    registration: models.BalancerRegistration | Any,
) -> PlayerRoster | None:
    """The resolved roster of ONE registration, straight from the engine.

    Write paths mutate roles and then want the ``ready``/``incomplete`` verdict.
    They hold a row loaded for their own reasons, which need not carry
    ``registration_load_options()``, so the roster is re-read through the engine's
    own query instead: autoflush publishes the pending role writes first, which
    is also what makes the verdict reflect the edit that just happened.
    """
    rosters = await roster_engine.for_tournament(
        session,
        registration.tournament_id,
        registration_ids=[registration.id],
        include_deleted=True,
    )
    return rosters.get(registration.id)


def included_balancer_status(roster: PlayerRoster | None) -> str:
    """The pool verdict: ``ready`` once every declared role carries a rank.

    No roster at all (a registration the engine did not resolve) reads as
    ``incomplete`` -- the same answer the old role-less case gave.
    """
    return "ready" if roster is not None and roster.is_ranked_complete else "incomplete"


def sync_included_balancer_status(
    registration: models.BalancerRegistration | Any,
    roster: PlayerRoster | None,
) -> None:
    """Recompute `ready`/`incomplete` from the resolved roster -- the only two
    balancer statuses a role edit is allowed to change. `not_in_balancer`,
    `excluded` and any custom status are exclusively admin-managed: they can
    no longer be picked FOR ready/incomplete (see `set_balancer_status`), so
    there is nothing left for a role-driven resync to fight over.
    """
    current_balancer_status = getattr(registration, "balancer_status", None)
    if (
        getattr(registration, "status", None) == "approved"
        and current_balancer_status in AUTO_MANAGED_BALANCER_STATUSES
    ):
        registration.balancer_status = included_balancer_status(roster)


def is_included_in_balancer(
    registration: models.BalancerRegistration | Any,
    status_meta_map: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Whether `registration` currently counts as part of the balancer pool.

    Single source of truth: the *current status's* `excludes_from_balancer`
    flag -- true for the builtin `not_in_balancer`/`excluded` statuses, false
    for `ready`/`incomplete`, and workspace-configurable for a custom status.
    Pass the resolved `status_meta_map` (see `get_status_metas_map`) when one
    is already in hand -- callers without it (no custom-status catalog
    loaded) still get the correct answer for every builtin status.
    """
    if getattr(registration, "deleted_at", None) is not None:
        return False
    balancer_status = getattr(registration, "balancer_status", None)
    if status_meta_map is not None:
        meta = status_meta_map.get("balancer", {}).get(balancer_status)
        if meta is not None:
            return not meta["excludes_from_balancer"]
    return not is_balancer_status_excluded(balancer_status)


class RegistrationCommonService:
    """Cross-cutting registration lookups shared by the admin subsystems."""

    def __init__(
        self,
        *,
        form_repo: RegistrationFormRepository = RegistrationFormRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.form_repo = form_repo
        self.tournament_repo = tournament_repo

    async def _register_registration_changed(
        self,
        session: AsyncSession,
        registration: models.BalancerRegistration,
    ) -> None:
        await emit(
            session,
            scope=Scope.tournament(registration.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
            # A row created in this same transaction has no id until it flushes;
            # entity_ids is optional precision, so no id just means no narrowing.
            entity_ids={"registration_ids": [registration.id]} if registration.id is not None else None,
        )

    async def get_tournament_grid(self, session: AsyncSession, tournament_id: int) -> DivisionGrid:
        # Analytical, not CRUD: the fallback is a join + order + limit across two
        # tables, and the second read returns a (Tournament, Workspace) pair with
        # nested eager loads. Neither fits behind a repository method.
        fallback_version = await session.scalar(
            sa.select(models.DivisionGridVersion)
            .join(models.DivisionGrid, models.DivisionGrid.id == models.DivisionGridVersion.grid_id)
            .options(selectinload(models.DivisionGridVersion.tiers))
            .where(models.DivisionGrid.workspace_id.is_(None))
            .order_by(models.DivisionGridVersion.id.asc())
            .limit(1)
        )
        result = await session.execute(
            sa.select(models.Tournament, models.Workspace)
            .join(models.Workspace, models.Workspace.id == models.Tournament.workspace_id)
            .options(
                selectinload(models.Tournament.division_grid_version).selectinload(models.DivisionGridVersion.tiers),
                selectinload(models.Workspace.default_division_grid_version).selectinload(
                    models.DivisionGridVersion.tiers
                ),
            )
            .where(models.Tournament.id == tournament_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        tournament_row, workspace_row = row
        return get_tournament_grid_from_rows(tournament_row, workspace_row, fallback_version)

    async def ensure_tournament_exists(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        return tournament

    async def get_registration_form(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerRegistrationForm | None:
        return await self.form_repo.get_by_tournament(session, tournament_id)

    async def get_form_custom_field_defs(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[CustomFieldDefinition]:
        form = await self.get_registration_form(session, tournament_id)
        return form_custom_field_defs(form)


_common_service = RegistrationCommonService()

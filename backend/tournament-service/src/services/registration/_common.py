"""Shared helpers for the registration admin subsystems.

Cross-cutting building blocks used by more than one of the admin modules
(``sheet_parsing`` / ``sheet_sync`` / ``rank_autofill`` / ``lifecycle`` /
``export``): tournament/form lookups, division-grid resolution, role
replacement and the active-role / balancer-status predicates. Everything here
is re-exported by the ``admin`` facade.
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from shared.balancer_registration_statuses import get_builtin_status_values
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.domain.player_sub_roles import normalize_sub_role
from shared.hero_catalog import HeroCatalog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.schemas.registration import CustomFieldDefinition
from src.services.registration.utils import DEFAULT_SORT_PRIORITY_SENTINEL
from src.services.tournament.realtime_commit import register_tournament_realtime_update

VALID_REGISTRATION_STATUSES = get_builtin_status_values("registration")
VALID_BALANCER_STATUSES = get_builtin_status_values("balancer")


def _register_registration_changed(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> None:
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")

BATTLE_TAG_RE = re.compile(r"[\w][\w ]{0,30}#[0-9]{3,}", re.UNICODE)


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


async def get_tournament_grid(session: AsyncSession, tournament_id: int) -> DivisionGrid:
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
            selectinload(models.Workspace.default_division_grid_version).selectinload(models.DivisionGridVersion.tiers),
        )
        .where(models.Tournament.id == tournament_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    tournament_row, workspace_row = row
    return get_tournament_grid_from_rows(tournament_row, workspace_row, fallback_version)


async def ensure_tournament_exists(session: AsyncSession, tournament_id: int) -> models.Tournament:
    result = await session.execute(sa.select(models.Tournament).where(models.Tournament.id == tournament_id))
    tournament = result.scalar_one_or_none()
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


async def get_registration_form(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationForm | None:
    result = await session.execute(
        sa.select(models.BalancerRegistrationForm).where(models.BalancerRegistrationForm.tournament_id == tournament_id)
    )
    return result.scalar_one_or_none()


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


async def get_form_custom_field_defs(
    session: AsyncSession,
    tournament_id: int,
) -> list[CustomFieldDefinition]:
    form = await get_registration_form(session, tournament_id)
    return form_custom_field_defs(form)


def replace_registration_roles(
    registration: models.BalancerRegistration,
    roles: list[dict[str, Any]],
    *,
    hero_catalog: HeroCatalog | None = None,
    max_heroes: int | None = None,
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

    registration.roles[:] = next_roles



def _active_roles(registration: models.BalancerRegistration | Any) -> list[Any]:
    return [r for r in getattr(registration, "roles", []) if getattr(r, "is_active", False)]


def registration_has_active_roles(registration: models.BalancerRegistration | Any) -> bool:
    return len(_active_roles(registration)) > 0


def active_roles_all_ranked(registration: models.BalancerRegistration | Any) -> bool:
    roles = _active_roles(registration)
    return len(roles) > 0 and all(getattr(r, "rank_value", None) is not None for r in roles)


def included_balancer_status(registration: models.BalancerRegistration | Any) -> str:
    return "ready" if active_roles_all_ranked(registration) else "incomplete"


def sync_included_balancer_status(registration: models.BalancerRegistration | Any) -> None:
    current_balancer_status = getattr(registration, "balancer_status", None)
    if (
        getattr(registration, "status", None) == "approved"
        and current_balancer_status in VALID_BALANCER_STATUSES
        and current_balancer_status != "not_in_balancer"
    ):
        registration.balancer_status = included_balancer_status(registration)

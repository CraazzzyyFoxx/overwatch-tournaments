from __future__ import annotations

from typing import Any

from shared.division_grid import DEFAULT_GRID, DivisionGrid
from shared.domain.player_sub_roles import normalize_sub_role
from shared.services.division_grid_resolution import resolve_tournament_division
from src.services.admin.balancer_utils import DEFAULT_SORT_PRIORITY_SENTINEL, VALID_ROLES


def resolve_rank_from_division(
    division_number: int | None,
    grid: DivisionGrid = DEFAULT_GRID,
) -> int | None:
    if division_number is None:
        return None
    return grid.resolve_rank_from_division(division_number)


def resolve_division_from_rank(
    rank_value: int | None,
    grid: DivisionGrid = DEFAULT_GRID,
) -> int | None:
    if rank_value is None:
        return None
    return resolve_tournament_division(rank_value, tournament_grid=grid)


def normalize_role_entries(role_entries: list[Any] | None) -> list[dict[str, Any]]:
    normalized_entries: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    prepared_entries: list[dict[str, Any]] = []

    for entry in role_entries or []:
        if isinstance(entry, dict):
            prepared_entries.append(entry)
        elif hasattr(entry, "model_dump"):
            prepared_entries.append(entry.model_dump())

    prepared_entries.sort(
        key=lambda item: (
            item.get("priority")
            if item.get("priority") is not None
            else DEFAULT_SORT_PRIORITY_SENTINEL
        )
    )

    for entry in prepared_entries:
        role = entry.get("role")
        if role not in VALID_ROLES or role in seen_roles:
            continue

        is_active_raw = entry.get("is_active")
        if is_active_raw is None:
            is_active_raw = entry.get("isActive")
        is_active = bool(True if is_active_raw is None else is_active_raw)

        subtype = normalize_sub_role(entry.get("subtype"))
        division_number = entry.get("division_number")
        rank_value = entry.get("rank_value")

        if division_number is not None and rank_value is None:
            rank_value = resolve_rank_from_division(int(division_number))
        elif rank_value is not None and division_number is None:
            division_number = resolve_division_from_rank(int(rank_value))

        normalized_entries.append(
            {
                "role": role,
                "subtype": subtype,
                "priority": len(normalized_entries) + 1,
                "division_number": (
                    int(division_number) if division_number is not None else None
                ),
                "rank_value": int(rank_value) if rank_value is not None else None,
                "is_active": is_active,
            }
        )
        seen_roles.add(role)

    return normalized_entries

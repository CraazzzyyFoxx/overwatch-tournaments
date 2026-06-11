from __future__ import annotations

import random
import typing

from loguru import logger

from src.services.balancer.algorithm.player_loader import load_players_from_dict
from src.services.balancer.algorithm.result_serializer import _build_response_payload
from src.services.balancer.config.defaults import AlgorithmConfig
from src.services.balancer.algorithm.captain_assignment_service import assign_captains
from src.services.balancer.config.provider import normalize_config_overrides
from src.services.balancer.algorithm.determinism import build_balancer_seed, derive_balancer_seed
from src.services.balancer.algorithm.feasibility_analyzer import analyze_feasibility
from src.services.balancer.algorithm.moo_backend import run_moo_optimizer
from src.services.balancer.algorithm.progress import ProgressCallback, emit_progress
from src.services.balancer.algorithm.rating_normalizer import RatingNormalizer
from src.services.balancer.algorithm.role_assignment_service import find_feasible_role_assignment


def _filter_valid_players_and_role_counts(
    all_players: list,
    needed_roles: list[str],
) -> tuple[list, dict[str, int]]:
    valid_players: list = []
    role_capable_counts: dict[str, int] = dict.fromkeys(needed_roles, 0)

    for player in all_players:
        player_roles: list[str] = []
        for role in needed_roles:
            if player.can_play(role):
                role_capable_counts[role] += 1
                player_roles.append(role)
        if player_roles:
            valid_players.append(player)

    return valid_players, role_capable_counts


def _prepare_balance_context(
    input_data: dict[str, typing.Any],
    config_overrides: dict[str, typing.Any] | None,
    progress_callback: ProgressCallback | None,
) -> tuple[AlgorithmConfig, list, int, bool, dict[str, str], int]:
    """Prepare config, players and role assignment for balancer flows."""
    config = AlgorithmConfig()
    has_applied_overrides = False

    emit_progress(
        progress_callback,
        status="running",
        stage="validating_input",
        message="Validating request payload",
    )

    if config_overrides:
        normalized_config_overrides = normalize_config_overrides(config_overrides)
        logger.info(f"Applying configuration overrides: {list(normalized_config_overrides.keys())}")

        for key, value in normalized_config_overrides.items():
            if value is None:
                continue
            if hasattr(config, key):
                setattr(config, key, value)
                logger.debug(f"Set {key} = {value}")
                has_applied_overrides = True
            else:
                logger.warning(f"Unknown config parameter '{key}' ignored")

    mask = config.role_mask
    emit_progress(
        progress_callback,
        status="running",
        stage="loading_players",
        message=f"Loading players with role mask {mask}",
    )
    logger.info(f"Loading players with mask: {mask}")

    all_players = load_players_from_dict(input_data, mask)
    needed_roles = [role for role, count in mask.items() if count > 0]
    valid_players, role_capable_counts = _filter_valid_players_and_role_counts(all_players, needed_roles)

    if not valid_players:
        logger.error("No valid players found after filtering")
        raise ValueError("No valid players found")

    emit_progress(
        progress_callback,
        status="running",
        stage="checking_roles",
        message="Checking role availability constraints",
    )

    for role, count in mask.items():
        if count <= 0:
            continue
        capable_count = role_capable_counts.get(role, 0)
        logger.info(f"Role '{role}' requires {count} per team, {capable_count} players can play it")
        if capable_count <= 0:
            raise ValueError(f"No players can play required role '{role}'")

    players_per_team = sum(mask.values())
    if players_per_team <= 0:
        raise ValueError("Role mask defines zero players per team")

    if len(valid_players) % players_per_team != 0:
        raise ValueError(
            f"Player count must be divisible by team size. "
            f"Got {len(valid_players)} players, team size is {players_per_team} "
            f"(mask {mask}). Remove {len(valid_players) % players_per_team} "
            f"players or add {players_per_team - len(valid_players) % players_per_team} "
            f"to form complete teams."
        )

    num_teams = len(valid_players) // players_per_team
    if num_teams == 0:
        raise ValueError(
            f"Not enough players to form even one team. "
            f"Need at least {players_per_team} players, got {len(valid_players)}."
        )

    base_seed = build_balancer_seed(valid_players, num_teams, config)

    if config.use_captains:
        assign_captains(valid_players, num_teams, mask)
        captain_count = sum(1 for player in valid_players if player.is_captain)
        logger.info(f"Assigned {captain_count} captains")
        emit_progress(
            progress_callback,
            status="running",
            stage="forming_teams",
            message=f"Assigned {captain_count} captains",
        )

    shortages = {
        role: (count * num_teams) - role_capable_counts.get(role, 0)
        for role, count in mask.items()
        if count > 0 and role_capable_counts.get(role, 0) < count * num_teams
    }
    if shortages:
        shortage_desc = ", ".join(f"'{role}' short by {missing}" for role, missing in shortages.items())
        raise ValueError(
            f"Cannot form {num_teams} full teams — not enough role coverage: "
            f"{shortage_desc}. Add more players capable of these roles or remove "
            f"enough players to shrink the team count."
        )

    role_assignment = find_feasible_role_assignment(
        valid_players,
        num_teams,
        mask,
        rng=random.Random(derive_balancer_seed(base_seed, "role_assignment")),
    )
    if role_assignment is None:
        raise ValueError(
            f"Cannot form {num_teams} full teams: either players cannot cover "
            f"the required role overlap, or too many captains are pinned to "
            f"the same role (see logs for details)."
        )

    logger.info(f"Forming {num_teams} teams with {len(valid_players)} players")
    emit_progress(
        progress_callback,
        status="running",
        stage="forming_teams",
        message=f"Forming {num_teams} teams",
    )

    return config, valid_players, num_teams, has_applied_overrides, role_assignment, derive_balancer_seed(
        base_seed,
        "moo_optimizer",
    )


def balance_teams_moo(
    input_data: dict[str, typing.Any],
    config_overrides: dict[str, typing.Any] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, typing.Any]]:
    """Return a Pareto front of balance solutions for the same payload format."""
    config, valid_players, num_teams, has_applied_overrides, role_assignment, optimizer_seed = _prepare_balance_context(
        input_data,
        config_overrides,
        progress_callback,
    )
    mask = config.role_mask

    feasibility = analyze_feasibility(valid_players, mask, num_teams)
    if feasibility.structural_min_off_role > 0:
        logger.info(
            f"Dataset has structural minimum {feasibility.structural_min_off_role} "
            f"off-role assignments out of {feasibility.total_slots} slots — "
            f"any balance solution must include at least this many."
        )

    normalizer = RatingNormalizer(target_max=config.rating_scale_ceiling)
    normalizer.fit(valid_players)
    if not normalizer.is_identity:
        logger.info(
            f"Normalizing input ratings to canonical ceiling "
            f"{config.rating_scale_ceiling} (scale factor {normalizer.scale:.4f})"
        )
        normalizer.apply(valid_players)

    emit_progress(
        progress_callback,
        status="running",
        stage="optimizing",
        message="Running moo optimizer",
    )

    try:
        pareto_solutions = run_moo_optimizer(
            valid_players,
            num_teams,
            config,
            progress_callback,
            role_assignment=role_assignment,
            seed=optimizer_seed,
        )
    finally:
        normalizer.restore_players(valid_players)

    if not pareto_solutions:
        raise ValueError("MOO optimizer returned no Pareto solutions.")

    if not normalizer.is_identity:
        for result_teams, _ in pareto_solutions:
            normalizer.refresh_team_stats(result_teams)

    payloads = [
        _build_response_payload(
            result,
            valid_players,
            mask,
            config,
            has_applied_overrides,
            metrics,
            feasibility=feasibility,
        )
        for result, metrics in pareto_solutions
    ]

    emit_progress(
        progress_callback,
        status="running",
        stage="finalizing",
        message=f"Prepared {len(payloads)} Pareto variants",
    )
    return payloads

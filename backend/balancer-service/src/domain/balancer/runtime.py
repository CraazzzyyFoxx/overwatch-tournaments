from __future__ import annotations

import dataclasses
import random
import typing

from loguru import logger

from src.domain.balancer.backends import get_backend
from src.domain.balancer.captain_assignment_service import assign_captains
from src.domain.balancer.determinism import build_balancer_seed, derive_balancer_seed
from src.domain.balancer.entities import Player
from src.domain.balancer.feasibility_analyzer import analyze_feasibility
from src.domain.balancer.player_loader import load_players_from_dict
from src.domain.balancer.progress import ProgressCallback, emit_progress
from src.domain.balancer.rating_normalizer import RatingNormalizer
from src.domain.balancer.result_serializer import _build_response_payload
from src.domain.balancer.role_assignment_service import find_feasible_role_assignment
from src.services.balancer.config.defaults import AlgorithmConfig
from src.services.balancer.config.provider import normalize_config_overrides


@dataclasses.dataclass(slots=True)
class BalanceContext:
    """Shared, algorithm-agnostic setup produced once per balance run.

    Replaces the 7-element positional tuple ``_prepare_balance_context`` used
    to return: every one of its five call sites (this module, two tests, the
    benchmark script) had to keep that field order in sync by hand.
    """

    config: AlgorithmConfig
    players: list[Player]
    num_teams: int
    has_applied_overrides: bool
    role_assignment: dict[str, str] | None
    optimizer_seed: int
    overflow_benched: list[Player]


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
    role_mask: dict[str, int] | None = None,
    *,
    max_teams: int | None = None,
) -> BalanceContext:
    """Prepare config, players and role assignment for balancer flows.

    ``role_mask`` is the tournament's resolved roster shape. It is not a config
    override but the shape of the thing being built, so it is applied after the
    overrides and cannot be contradicted by a saved config.
    """
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

    if role_mask:
        config.role_mask = role_mask

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

    num_teams = len(valid_players) // players_per_team
    if num_teams == 0:
        raise ValueError(
            f"Not enough players to form even one team. "
            f"Need at least {players_per_team} players, got {len(valid_players)}."
        )
    if max_teams is not None and num_teams > max_teams:
        logger.info(
            f"Capping to {max_teams} team(s) for this algorithm (the pool divides evenly "
            f"into {num_teams}); the rest sit out like any other overflow."
        )
        num_teams = max_teams

    # A player count that isn't an exact multiple of the team size no longer
    # blocks the run: the leftover players just sit out, exactly like a host
    # manually benching someone. A ``must_play`` player is never among them
    # unless there are more of them than team slots exist -- they are moved to
    # the front before the tail is cut, so trimming always reaches for an
    # optional player first, and within the optional group ``rotation_priority``
    # (ascending, default 0.0) breaks the tie -- the tournament balancer never
    # sets it, so ``sorted``'s stability leaves that group's input order
    # untouched, exactly as before this field existed.
    usable_count = num_teams * players_per_team
    if usable_count < len(valid_players):
        must_play_players = [player for player in valid_players if player.must_play]
        if len(must_play_players) > usable_count:
            raise ValueError(
                f"{len(must_play_players)} players are marked 'must play' but only "
                f"{usable_count} team slots exist for {len(valid_players)} players. "
                f"Unflag {len(must_play_players) - usable_count} of them or add more players."
            )
        optional_players = sorted(
            (player for player in valid_players if not player.must_play),
            key=lambda player: player.rotation_priority,
        )
        ordered = must_play_players + optional_players
        valid_players, overflow_benched = ordered[:usable_count], ordered[usable_count:]
        valid_players, role_capable_counts = _filter_valid_players_and_role_counts(valid_players, needed_roles)
        logger.info(
            f"{len(overflow_benched)} player(s) sit out: only {usable_count} of "
            f"{usable_count + len(overflow_benched)} players fit into {num_teams} team(s) of {players_per_team}."
        )
    else:
        overflow_benched = []

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

    return BalanceContext(
        config=config,
        players=valid_players,
        num_teams=num_teams,
        has_applied_overrides=has_applied_overrides,
        role_assignment=role_assignment,
        optimizer_seed=derive_balancer_seed(base_seed, "tournament_balancer_optimizer"),
        overflow_benched=overflow_benched,
    )


def balance_teams(
    input_data: dict[str, typing.Any],
    config_overrides: dict[str, typing.Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    role_mask: dict[str, int] | None = None,
    *,
    algorithm: str = "tournament_balancer",
) -> list[dict[str, typing.Any]]:
    """Return ranked balance solutions for the same payload format.

    Backend-agnostic: prepares the shared context once (player loading,
    must-play/bench trimming, captain assignment, role-assignment
    feasibility -- none of it specific to any one engine), then dispatches to
    whichever ``OptimizerBackend`` ``algorithm`` names (see
    ``domain/balancer/backends``). ``"tournament_balancer"`` returns a Pareto front;
    other backends return whatever ranking they naturally produce.
    """
    backend = get_backend(algorithm)

    context = _prepare_balance_context(
        input_data, config_overrides, progress_callback, role_mask, max_teams=backend.max_teams
    )
    mask = context.config.role_mask

    if backend.max_teams is not None and context.num_teams != backend.max_teams:
        raise ValueError(
            f"Algorithm '{algorithm}' needs exactly {backend.max_teams} team(s) worth of players "
            f"(got enough for only {context.num_teams} from {len(context.players)} players / "
            f"{sum(mask.values())} per team)."
        )

    feasibility = analyze_feasibility(context.players, mask, context.num_teams)
    if feasibility.structural_min_off_role > 0:
        logger.info(
            f"Dataset has structural minimum {feasibility.structural_min_off_role} "
            f"off-role assignments out of {feasibility.total_slots} slots — "
            f"any balance solution must include at least this many."
        )

    normalizer = RatingNormalizer(target_max=context.config.rating_scale_ceiling)
    normalizer.fit(context.players)
    if not normalizer.is_identity:
        logger.info(
            f"Normalizing input ratings to canonical ceiling "
            f"{context.config.rating_scale_ceiling} (scale factor {normalizer.scale:.4f})"
        )
        normalizer.apply(context.players)

    emit_progress(
        progress_callback,
        status="running",
        stage="optimizing",
        message=f"Running {backend.name} optimizer",
    )

    try:
        solutions = backend.solve(
            context.players,
            context.num_teams,
            context.config,
            context.role_assignment,
            context.optimizer_seed,
            progress_callback,
        )
    finally:
        normalizer.restore_players(context.players)

    if not solutions:
        raise ValueError(f"{backend.name} backend returned no balance solutions.")

    if not normalizer.is_identity:
        # Both the team stats and the backend's own rating-unit metrics were
        # produced on the canonical scale; put both back into the caller's
        # rating units so a reported metric is comparable to a team total.
        inverse_scale = 1.0 / normalizer.scale
        for solution in solutions:
            normalizer.refresh_team_stats(solution.teams)
        solutions = [
            dataclasses.replace(solution, metrics=solution.metrics.rescale_ratings(inverse_scale))
            for solution in solutions
        ]

    payloads = [
        _build_response_payload(
            solution.teams,
            context.players + context.overflow_benched,
            mask,
            context.config,
            context.has_applied_overrides,
            solution.metrics,
            feasibility=feasibility,
        )
        for solution in solutions
    ]

    emit_progress(
        progress_callback,
        status="running",
        stage="finalizing",
        message=f"Prepared {len(payloads)} variants",
    )
    return payloads


def balance_teams_tournament(
    input_data: dict[str, typing.Any],
    config_overrides: dict[str, typing.Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    role_mask: dict[str, int] | None = None,
) -> list[dict[str, typing.Any]]:
    """Return a Pareto front of balance solutions for the same payload format."""
    return balance_teams(input_data, config_overrides, progress_callback, role_mask, algorithm="tournament_balancer")

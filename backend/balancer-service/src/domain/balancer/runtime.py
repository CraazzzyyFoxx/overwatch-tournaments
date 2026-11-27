from __future__ import annotations

import dataclasses
import random
import typing

from loguru import logger

from shared.domain.player_sub_roles import workspace_sub_role_code
from shared.domain.roles import Ontology
from shared.domain.team_format import TeamFormat
from src.domain.balancer.backends import get_backend
from src.domain.balancer.captain_assignment_service import assign_captains
from src.domain.balancer.config.defaults import AlgorithmConfig, apply_config_overrides, default_role_settings
from src.domain.balancer.config.public_contract import normalize_config_payload
from src.domain.balancer.determinism import build_balancer_seed, derive_balancer_seed
from src.domain.balancer.entities import Player
from src.domain.balancer.feasibility_analyzer import analyze_feasibility
from src.domain.balancer.mix_rules import lane_layout
from src.domain.balancer.player_loader import load_players_from_dict
from src.domain.balancer.progress import ProgressCallback, emit_progress
from src.domain.balancer.rating_normalizer import RatingNormalizer
from src.domain.balancer.result_serializer import _build_response_payload
from src.domain.balancer.role_assignment_service import find_feasible_role_assignment
from src.domain.mix_lobby_split import seated_set


@dataclasses.dataclass(slots=True)
class BalanceContext:
    """Shared, algorithm-agnostic setup produced once per balance run."""

    config: AlgorithmConfig
    players: list[Player]
    num_teams: int
    has_applied_overrides: bool
    role_assignment: dict[str, str] | None
    optimizer_seed: int
    overflow_benched: list[Player]
    original_subclasses: dict[str, dict[str, str]] = dataclasses.field(default_factory=dict)


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
    team_format: TeamFormat | None = None,
    ontology: Ontology | None = None,
    discipline: str | None = None,
) -> BalanceContext:
    """Prepare config, players and role assignment for balancer flows.

    ``role_mask`` is the tournament's resolved roster shape. It is not a config
    override but the shape of the thing being built, so it is applied after the
    overrides and cannot be contradicted by a saved config. The role weights a run
    starts from are its game's declaration (the owner format's game, else the
    ``discipline`` a payload names); a run that names no game weighs every role neutrally.
    """
    game = team_format.discipline if team_format is not None else discipline
    config = AlgorithmConfig(role_settings=default_role_settings(game))

    emit_progress(
        progress_callback,
        status="running",
        stage="validating_input",
        message="Validating request payload",
    )

    # ``normalize_config_payload`` guarantees non-None knobs.
    overrides = normalize_config_payload(config_overrides) if config_overrides else {}
    if overrides:
        logger.info(f"Applying configuration overrides: {overrides}")
        apply_config_overrides(config, overrides)
    has_applied_overrides = bool(overrides)

    if role_mask:
        config.role_mask = role_mask
    config.lane_layout = lane_layout(team_format)

    mask = config.role_mask
    if not mask:
        raise ValueError("role_mask is required: the run carries no roster shape")
    emit_progress(
        progress_callback,
        status="running",
        stage="loading_players",
        message=f"Loading players with role mask {mask}",
    )
    logger.info(f"Loading players with mask: {mask}")

    all_players = load_players_from_dict(input_data, mask)
    original_subclasses = {}
    if team_format is not None and ontology is not None:
        recommendations = [
            rule
            for rule in team_format.rules
            if (rule.recommended_min is not None or rule.recommended_max is not None)
            and ontology.node(rule.dimension, rule.role).parent_id is not None
        ]
        if recommendations:
            penalized = {
                rule.role
                for rule in recommendations
                if rule.dimension == ontology.rated.code
                and team_format.mode(rule.dimension) != "off"
                and rule.recommended_max is not None
                and rule.recommended_max <= 1
            }
            if not penalized:
                config.sub_role_collision_weight = 0
            for player in all_players:
                original_subclasses[player.uuid] = player.subclasses
                player.subclasses = {
                    role: subtype
                    for role, subtype in player.subclasses.items()
                    if workspace_sub_role_code(role, subtype) in penalized
                }
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

    # Players past the last full team sit out. ``must_play`` players move to the
    # front before the tail is cut, so trimming reaches an optional player first
    # unless there are more must-play players than slots; among optional players
    # ``rotation_priority`` (ascending) breaks the tie, and input order -- the
    # loader's uuid order -- after it. A player the seats' roles can no longer
    # take sits out instead of the next one in that order, so a pool that can
    # fill the teams is never refused for whoever sorts last. ``seated_set`` is
    # that one rule, shared with the lobby splitter and a mix draft's seated set.
    usable_count = num_teams * players_per_team
    if usable_count < len(valid_players):
        must_play_players = [player for player in valid_players if player.must_play]
        if len(must_play_players) > usable_count:
            raise ValueError(
                f"{len(must_play_players)} players are marked 'must play' but only "
                f"{usable_count} team slots exist for {len(valid_players)} players. "
                f"Unflag {len(must_play_players) - usable_count} of them or add more players."
            )
        valid_players, overflow_benched = seated_set(
            valid_players, [role for role, count in mask.items() for _ in range(count * num_teams)]
        )
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
        original_subclasses=original_subclasses,
    )


def balance_teams(
    input_data: dict[str, typing.Any],
    config_overrides: dict[str, typing.Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    role_mask: dict[str, int] | None = None,
    *,
    algorithm: str = "tournament_balancer",
    team_format: TeamFormat | None = None,
    ontology: Ontology | None = None,
    discipline: str | None = None,
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
        input_data,
        config_overrides,
        progress_callback,
        role_mask,
        max_teams=backend.max_teams,
        team_format=team_format,
        ontology=ontology,
        discipline=discipline,
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
        for player in context.players + context.overflow_benched:
            if player.uuid in context.original_subclasses:
                player.subclasses = context.original_subclasses[player.uuid]

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
            team_format=team_format,
            ontology=ontology,
            annotations=solution.annotations,
        )
        for solution in solutions
    ]
    # Keep the backend's ordering between distinct objectives; recommendations
    # only break exact objective ties (before response metrics are rounded).
    objective_ranks = {}
    ranking = []
    for index, (solution, payload) in enumerate(zip(solutions, payloads, strict=True)):
        objective = (solution.metrics.composite_score, solution.metrics.mix_balancer_quality_total)
        rank = index if objective == (None, None) else objective_ranks.setdefault(objective, index)
        ranking.append((rank, sum(len(team["format_advisories"]) for team in payload["teams"]), index))
    payloads = [payloads[index] for _, _, index in sorted(ranking)]

    emit_progress(
        progress_callback,
        status="running",
        stage="finalizing",
        message=f"Prepared {len(payloads)} variants",
    )
    return payloads

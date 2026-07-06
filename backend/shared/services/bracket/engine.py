from shared.core.enums import StageType

from . import double_elimination, round_robin, single_elimination, swiss
from .types import AdvancementEdge, BracketSkeleton, Pairing


def generate_bracket(
    stage_type: StageType,
    team_ids: list[int],
    *,
    swiss_standings: list[swiss.SwissStanding] | None = None,
    swiss_played_pairs: set[frozenset[int]] | None = None,
    swiss_round_number: int = 1,
    swiss_bye_history: set[int] | None = None,
    de_include_reset: bool = False,
    lower_bracket_team_ids: list[int] | None = None,
) -> BracketSkeleton:
    """Dispatch bracket generation to the appropriate algorithm.

    Args:
        stage_type: The type of bracket to generate.
        team_ids: List of team IDs to seed into the bracket.
        swiss_standings: Required for SWISS — current standings.
        swiss_played_pairs: Required for SWISS — set of already-played pairs.
        swiss_round_number: For SWISS — which round to generate.
        swiss_bye_history: For SWISS — set of team_ids that already received a bye.
        de_include_reset: For DE — whether to pre-materialise Grand Final Reset.

    Returns:
        :class:`BracketSkeleton` with all generated pairings and advancement edges.
    """
    if not team_ids:
        raise ValueError("team_ids must be non-empty")
    combined_ids = team_ids + list(lower_bracket_team_ids or [])
    if len(set(combined_ids)) != len(combined_ids):
        raise ValueError("team_ids must be unique within a stage item")

    if stage_type == StageType.ROUND_ROBIN:
        return round_robin.generate(team_ids)

    if stage_type == StageType.SINGLE_ELIMINATION:
        return single_elimination.generate(team_ids)

    if stage_type == StageType.DOUBLE_ELIMINATION:
        return double_elimination.generate(
            team_ids,
            lower_bracket_team_ids=lower_bracket_team_ids,
            include_reset=de_include_reset,
        )

    if stage_type == StageType.SWISS:
        if swiss_standings is None:
            swiss_standings = [swiss.SwissStanding(team_id=tid, points=0.0) for tid in team_ids]
        return swiss.generate_round(
            standings=swiss_standings,
            played_pairs=swiss_played_pairs or set(),
            round_number=swiss_round_number,
            bye_history=swiss_bye_history,
        )

    raise ValueError(f"Unsupported stage type: {stage_type}")


__all__ = [
    "generate_bracket",
    "BracketSkeleton",
    "Pairing",
    "AdvancementEdge",
]

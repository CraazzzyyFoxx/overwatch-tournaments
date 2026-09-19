"""What the outside world may write into a balancer config, and how it is read.

Everything here is derived from :class:`AlgorithmConfig`: the writable key set,
the :class:`ConfigOverrides` request schema, and the one normalizer every write
path goes through. There used to be a second hand-written copy of all ~35 knobs
in ``src/schemas/balancer.py`` plus five differently-named wrappers around a
single normalize step; a knob missing from either list was accepted by the API
and then silently dropped.
"""

from __future__ import annotations

import functools
import operator
import types
import typing
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic.fields import FieldInfo

from src.services.balancer.config.defaults import AlgorithmConfig

# Not the operator's to set, so absent from the write allowlist:
#   * ``role_mask`` is a projection of the tournament roster shape, resolved per
#     run by ``_prepare_balance_context`` -- a saved config must not be able to
#     contradict the shape the tournament actually fields.
#   * ``rating_scale_ceiling`` is a rating-normalisation constant applied
#     Python-side by ``RatingNormalizer``, not a solver knob.
NON_WRITABLE_CONFIG_KEYS = frozenset({"role_mask", "rating_scale_ceiling"})

#: Keys a saved config or an API request may carry.
PUBLIC_CONFIG_KEYS = frozenset(AlgorithmConfig.model_fields) - NON_WRITABLE_CONFIG_KEYS

# Accepted and silently dropped instead of rejected, on the paths that write a
# stored config: a config saved before these keys stopped being writable is
# still in the database and must stay loadable.
#   * ``role_mask`` / ``rating_scale_ceiling`` -- see above
#   * ``intra_team_variance_weight`` / ``role_spread_weight`` -- never read by
#     the cost function; the live weights are ``intra_team_std_weight`` and
#     ``internal_role_spread_weight``
#   * the rest belonged to the removed pure-Python genetic solver
#
# ``algorithm`` is deliberately NOT here: it names a solver that no longer
# exists, so an operator writing it gets a 422 rather than silence. Read paths
# still tolerate it -- it is simply not a field, so the allowlist filter below
# drops it.
RETIRED_CONFIG_KEYS = NON_WRITABLE_CONFIG_KEYS | frozenset(
    {
        "input_role_mapping",
        "elitism_rate",
        "stagnation_threshold",
        "intra_team_variance_weight",
        "role_spread_weight",
    }
)


def _as_optional(field: FieldInfo) -> tuple[typing.Any, FieldInfo]:
    """The same knob, but omissible: constraints and description kept, default ``None``.

    ``json_schema_extra`` is deliberately not carried over -- the ``knob`` block
    is drawer metadata for ``GET /config``, not part of the public request schema.
    """
    annotation = field.annotation
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        # ``time_limit_ms`` is already ``int | None``; unwrap before re-wrapping
        # so the constraints below land on ``int``, not on the nullable union.
        annotation = functools.reduce(
            operator.or_, (arg for arg in typing.get_args(annotation) if arg is not type(None))
        )
    if field.metadata:
        annotation = typing.Annotated[(annotation, *field.metadata)]
    return (annotation | None, Field(None, description=field.description))


#: Public write schema: every :class:`AlgorithmConfig` knob, optional.
#:
#: ``extra="forbid"`` so a misspelled knob is a 422 rather than a silently
#: ignored field on a request whose whole point is being self-describing.
ConfigOverrides: type[BaseModel] = create_model(
    "ConfigOverrides",
    __doc__="Optional public configuration overrides for the balancing algorithm.",
    __module__=__name__,
    __config__=ConfigDict(extra="forbid"),
    **{name: _as_optional(field) for name, field in AlgorithmConfig.model_fields.items() if name in PUBLIC_CONFIG_KEYS},
)


def normalize_config_payload(config_payload: Mapping[str, typing.Any] | None) -> dict[str, typing.Any]:
    """Validate a config blob from any source into the canonical stored shape.

    The gate for every lenient path -- API request overrides, a saved balance, a
    preset, mix preferences. Anything that is not a current writable knob is
    dropped; what is left must validate. The strict counterpart, used for the
    operator-facing tournament config, is
    ``provider.normalize_tournament_config_payload``.
    """
    sanitized_payload = {key: value for key, value in (config_payload or {}).items() if key in PUBLIC_CONFIG_KEYS}
    if not sanitized_payload:
        return {}

    return ConfigOverrides.model_validate(sanitized_payload).model_dump(exclude_none=True)


def serialize_algorithm_config(config: AlgorithmConfig | Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    """Project a resolved config down to the keys a client is allowed to see back."""
    payload = config.model_dump() if hasattr(config, "model_dump") else dict(config)
    return {key: value for key, value in payload.items() if key in PUBLIC_CONFIG_KEYS and value is not None}


# Balances saved before the result payload was renamed to snake_case still sit in
# ``balancer_balance.result_json``; reads upgrade them in place so old rows stay
# loadable (the current schema itself stays snake_case-only).
_LEGACY_TEAM_KEYS = {
    "avgMMR": "average_mmr",
    "variance": "rating_variance",
    "totalDiscomfort": "total_discomfort",
    "maxDiscomfort": "max_discomfort",
}
_LEGACY_PLAYER_KEYS = {
    "rating": "assigned_rating",
    "discomfort": "role_discomfort",
    "isCaptain": "is_captain",
    "preferences": "role_preferences",
    "allRatings": "all_ratings",
    "isFlex": "is_flex",
    "subRole": "sub_role",
}
_LEGACY_STATISTICS_KEYS = {
    "averageMMR": "average_mmr",
    "mmrStdDev": "mmr_std_dev",
    "totalTeams": "total_teams",
    "playersPerTeam": "players_per_team",
    "offRoleCount": "off_role_count",
    "subRoleCollisionCount": "sub_role_collision_count",
    "unbalancedCount": "unbalanced_count",
}
_LEGACY_ROOT_KEYS = {
    "benchedPlayers": "benched_players",
    "appliedConfig": "applied_config",
}


def _rename_legacy_keys(payload: Mapping[str, typing.Any], legacy_keys: Mapping[str, str]) -> dict[str, typing.Any]:
    upgraded = {key: value for key, value in payload.items() if key not in legacy_keys}
    for legacy_key, key in legacy_keys.items():
        if legacy_key in payload and key not in upgraded:
            upgraded[key] = payload[legacy_key]
    return upgraded


def _upgrade_legacy_player(player: typing.Any) -> typing.Any:
    if not isinstance(player, Mapping):
        return player
    return _rename_legacy_keys(player, _LEGACY_PLAYER_KEYS)


def _upgrade_legacy_team(team: typing.Any) -> typing.Any:
    if not isinstance(team, Mapping):
        return team
    upgraded = _rename_legacy_keys(team, _LEGACY_TEAM_KEYS)
    roster = upgraded.get("roster")
    if isinstance(roster, Mapping):
        upgraded["roster"] = {
            role: [_upgrade_legacy_player(player) for player in players] if isinstance(players, list) else players
            for role, players in roster.items()
        }
    return upgraded


def upgrade_legacy_balance_payload(balance_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    upgraded = _rename_legacy_keys(balance_payload, _LEGACY_ROOT_KEYS)
    teams = upgraded.get("teams")
    if isinstance(teams, list):
        upgraded["teams"] = [_upgrade_legacy_team(team) for team in teams]
    benched = upgraded.get("benched_players")
    if isinstance(benched, list):
        upgraded["benched_players"] = [_upgrade_legacy_player(player) for player in benched]
    statistics = upgraded.get("statistics")
    if isinstance(statistics, Mapping):
        upgraded["statistics"] = _rename_legacy_keys(statistics, _LEGACY_STATISTICS_KEYS)
    return upgraded


def normalize_balance_response_payload(balance_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    from src.schemas.balancer import BalanceResponse

    validated = BalanceResponse.model_validate(upgrade_legacy_balance_payload(balance_payload))
    return validated.model_dump(exclude_none=True)


def normalize_balance_job_result_payload(result_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    from src.schemas.balancer import BalanceJobResult

    validated = BalanceJobResult.model_validate(dict(result_payload))
    return validated.model_dump(exclude_none=True)

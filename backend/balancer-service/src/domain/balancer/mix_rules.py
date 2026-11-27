"""The mix engine's soft rules (``native/balancer_native/src/mix/rules.rs``) on the Python side.

Host knobs (``AlgorithmConfig.mix_rules``) plus the run's format become the engine's
``config.mix_rules``; the engine's per-variant verdicts become
``statistics.mix_balancer_rules`` and ``variant.annotations[kind]``. An annotation keeps
the spec it was scored with, so a host's seat swap re-scores exactly the rule the run
used (:func:`evaluate_variant_rules`), whatever the host's preferences say by then.

A new rule is a ``RuleSpec`` variant in Rust, a field of ``MixRules`` and a branch in
:func:`resolve_mix_rules`; everything downstream is keyed by the rule's ``kind``.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping, Sequence

from loguru import logger

from shared.disciplines import DISCIPLINES
from shared.domain.team_format import TeamFormat
from src.domain.balancer import native
from src.domain.balancer.config.defaults import AlgorithmConfig

__all__ = ("evaluate_variant_rules", "lane_layout", "resolve_mix_rules", "variant_annotations")


def lane_layout(team_format: TeamFormat | None) -> tuple[int, ...]:
    """Seats per lane of the format's preset; ``()`` for a format without a known preset."""
    if team_format is None or team_format.preset_code is None or team_format.discipline not in DISCIPLINES:
        return ()
    try:
        return DISCIPLINES[team_format.discipline].preset(team_format.preset_code).lanes
    except LookupError:
        return ()


def resolve_mix_rules(config: AlgorithmConfig) -> list[dict[str, typing.Any]]:
    """The engine's ``config.mix_rules``: every enabled rule this run's shape fits."""
    rules: list[dict[str, typing.Any]] = []
    lanes = config.mix_rules.lane_matchup
    team_size = sum(slots for slots in config.role_mask.values() if slots > 0)
    if lanes.enabled and config.lane_layout and sum(config.lane_layout) == team_size:
        rules.append(
            {
                "kind": "lane_matchup",
                "layout": list(config.lane_layout),
                "weight": lanes.weight,
                "cohesion_weight": lanes.cohesion_weight,
            }
        )
    return rules


def variant_annotations(
    rules: Sequence[Mapping[str, typing.Any]],
    verdicts: Mapping[str, typing.Any],
    team_ids: Sequence[int],
) -> dict[str, dict[str, typing.Any]]:
    """One variant's verdicts -> ``{kind: {rule, teams: {team_id: groups}}}``.

    Keyed by team id because the response orders teams strongest first
    (``teams_to_json``); ``_build_response_payload`` lays them out in that order.
    """
    return {
        str(rule["kind"]): {
            "rule": dict(rule),
            "teams": dict(zip(team_ids, verdicts[rule["kind"]]["teams"], strict=True)),
        }
        for rule in rules
        if rule["kind"] in verdicts
    }


def evaluate_variant_rules(variant: dict[str, typing.Any], players: Mapping[str, typing.Any]) -> None:
    """Re-score a hand-edited variant's rules in place: its annotations and ``mix_balancer_rules``.

    ``players`` is the lobby document's ``players`` map; ratings are the document's,
    which for a ranker mix are the open ranks shown, not the hidden ones the run used.
    A variant the engine cannot read loses its rule verdicts: stale lanes would be
    worse than none.
    """
    annotations = variant.get("annotations")
    if not isinstance(annotations, dict) or not annotations:
        return
    statistics = variant.setdefault("statistics", {})
    try:
        rosters = [team["roster"] for team in variant["teams"]]
        seated = sorted({str(uuid) for roster in rosters for uuids in roster.values() for uuid in uuids})
        request = {
            "request": {
                "players": [
                    {
                        "uuid": uuid,
                        "name": str(players[uuid].get("name") or uuid),
                        "ratings": {role: round(value) for role, value in (players[uuid].get("ratings") or {}).items()},
                        "preferences": [],
                        "subclasses": {},
                        "is_captain": False,
                        "is_flex": False,
                        "seed_role": None,
                    }
                    for uuid in seated
                ],
                "num_teams": len(rosters),
                "seed": 0,
                "roles": [{"name": role, "slots": len(uuids), "weight": 1.0} for role, uuids in rosters[0].items()],
                "config": {
                    "max_result_variants": 1,
                    "mix_rules": [annotation["rule"] for annotation in annotations.values()],
                },
            },
            "teams": rosters,
        }
        verdicts = native.evaluate_mix_rules(request)["rules"]
    except KeyError, TypeError, ValueError:
        logger.exception("Mix rules could not re-score a hand-edited variant; dropping its rule verdicts")
        variant.pop("annotations", None)
        statistics.pop("mix_balancer_rules", None)
        return
    for kind, annotation in annotations.items():
        annotation["teams"] = verdicts[kind]["teams"]
    statistics["mix_balancer_rules"] = {kind: round(verdict["penalty"], 4) for kind, verdict in verdicts.items()}

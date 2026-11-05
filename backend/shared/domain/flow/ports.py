"""The port catalogue (spec §6): each node kind's named inputs and outputs and how their unit is decided."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from shared.core.enums import FlowNodeKind, FlowUnit, StageType

__all__ = (
    "PORT_CATALOGUE",
    "KindPorts",
    "PortSpec",
    "UnitRule",
    "concrete_outputs",
    "port_unit",
)

#: How a port's unit is decided: fixed, by the stage type, by the node config, or inherited from the input.
UnitRule = Literal["players", "teams", "stage", "config", "input"]


@dataclass(frozen=True, slots=True)
class PortSpec:
    name: str
    unit: UnitRule
    multi: bool = False  #: an input that accepts any number of edges
    repeated: bool = False  #: an output that expands to ``<name>_1 … <name>_k``


@dataclass(frozen=True, slots=True)
class KindPorts:
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]


PORT_CATALOGUE: Mapping[FlowNodeKind, KindPorts] = MappingProxyType(
    {
        FlowNodeKind.REGISTRATION: KindPorts((), (PortSpec("participants", "players"),)),
        FlowNodeKind.FORMATION: KindPorts((PortSpec("players", "players"),), (PortSpec("teams", "teams"),)),
        FlowNodeKind.STAGE: KindPorts((PortSpec("participants", "stage"),), (PortSpec("ranking", "stage"),)),
        FlowNodeKind.FILTER: KindPorts((PortSpec("ranking", "input"),), (PortSpec("passed", "input"),)),
        FlowNodeKind.MERGE: KindPorts((PortSpec("inputs", "input", multi=True),), (PortSpec("merged", "input"),)),
        FlowNodeKind.SPLIT: KindPorts((PortSpec("ranking", "input"),), (PortSpec("bucket", "input", repeated=True),)),
        FlowNodeKind.AGGREGATE: KindPorts(
            (PortSpec("inputs", "config", multi=True),), (PortSpec("ranking", "config"),)
        ),
        FlowNodeKind.LEADERBOARD: KindPorts((PortSpec("ranking", "input"),), (PortSpec("ranking", "input"),)),
    }
)


def concrete_outputs(kind: FlowNodeKind, config: Mapping[str, Any]) -> tuple[PortSpec, ...]:
    """The kind's outputs with a repeated port expanded to one port per configured bucket."""
    count = len(config.get("buckets") or [])
    return tuple(
        port
        for spec in PORT_CATALOGUE[kind].outputs
        for port in (
            (PortSpec(f"{spec.name}_{i}", spec.unit, spec.multi) for i in range(1, count + 1))
            if spec.repeated
            else (spec,)
        )
    )


def port_unit(
    rule: UnitRule,
    *,
    stage_type: StageType | None,
    config: Mapping[str, Any],
    input_unit: FlowUnit | None,
) -> FlowUnit | None:
    match rule:
        case "players":
            return FlowUnit.PLAYERS
        case "teams":
            return FlowUnit.TEAMS
        case "stage":
            if stage_type is None:
                return None
            return FlowUnit.PLAYERS if stage_type == StageType.INDIVIDUAL_SWISS else FlowUnit.TEAMS
        case "config":
            try:
                return FlowUnit(config["unit"])
            except (KeyError, ValueError):
                return None
        case "input":
            return input_unit

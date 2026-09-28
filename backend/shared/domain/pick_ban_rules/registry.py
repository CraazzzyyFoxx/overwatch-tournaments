"""Condition leaves, constraint specs and the tree evaluator.

Same shape as the achievements condition registry
(``parser-service/.../engine/conditions``): a decorator registers an evaluator
together with its contract, and the contract is what the constructor UI renders
forms from. Unlike achievements the params are TYPED (:class:`ParamSpec`), so
the frontend generates the right widget without a hardcoded table.

Design: ``docs/plans/2026-09-28-pick-ban-constructor.md`` §2, §10.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

ConditionContext = Literal["round", "item", "pool"]
ParamKind = Literal["enum", "int", "bool", "item_list", "group_list", "group"]

#: Groups of the hero catalog: a hero's class, lowercased. Compared
#: case-insensitively everywhere, so ``Hero.type`` ("Tank") and the roster role
#: spelling ("tank") both answer to the same group.
HERO_GROUPS: tuple[str, ...] = ("tank", "damage", "support")

MAX_TREE_DEPTH = 20
MAX_TREE_NODES = 200


def normalize_group(value: object) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower() or None


# ── contracts ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    kind: ParamKind
    required: bool = True
    #: Closed value set for ``kind="enum"``.
    values: tuple[str, ...] | None = None
    min: int | None = None
    max: int | None = None
    #: Whether ``null`` is an accepted value.
    nullable: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
            "values": list(self.values) if self.values is not None else None,
            "min": self.min,
            "max": self.max,
            "nullable": self.nullable,
        }


@dataclass(frozen=True, slots=True)
class LeafSpec:
    type: str
    contexts: tuple[ConditionContext, ...]
    kinds: tuple[str, ...]
    params: tuple[ParamSpec, ...] = ()
    #: Only valid inside a step that has a ``target``.
    requires_target: bool = False
    #: Reads the acting side (``self``/``opponent``) — not usable in a pool filter.
    relative: bool = False
    evaluator: Callable[[Mapping[str, Any], Any], bool] | None = field(default=None, compare=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "contexts": list(self.contexts),
            "kinds": list(self.kinds),
            "params": [param.to_json() for param in self.params],
            "requires_target": self.requires_target,
            "relative": self.relative,
        }


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    type: str
    params: tuple[ParamSpec, ...] = ()
    requires_target: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "params": [param.to_json() for param in self.params],
            "requires_target": self.requires_target,
        }


LEAVES: dict[str, LeafSpec] = {}


def leaf(
    *,
    type: str,
    contexts: tuple[ConditionContext, ...],
    kinds: tuple[str, ...] = ("map", "hero"),
    params: tuple[ParamSpec, ...] = (),
    requires_target: bool = False,
    relative: bool = False,
) -> Callable[[Callable[[Mapping[str, Any], Any], bool]], Callable[[Mapping[str, Any], Any], bool]]:
    """Register a leaf evaluator together with its contract."""

    def decorator(fn: Callable[[Mapping[str, Any], Any], bool]) -> Callable[[Mapping[str, Any], Any], bool]:
        if type in LEAVES:
            raise ValueError(f"duplicate leaf {type!r}")
        LEAVES[type] = LeafSpec(
            type=type,
            contexts=contexts,
            kinds=kinds,
            params=params,
            requires_target=requires_target,
            relative=relative,
            evaluator=fn,
        )
        return fn

    return decorator


def get_leaf(type: str) -> LeafSpec | None:
    return LEAVES.get(type)


# ── evaluation contexts ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AppliedItem:
    """One item the board already shows (revealed, or visible on an open step)."""

    step_index: int
    round: int | None
    #: ``home``/``away``/``system``.
    side: str
    action: str
    item_id: int


@dataclass(frozen=True, slots=True)
class History:
    """Applied items the relative leaves read. ``current_step_index`` is
    excluded from every answer: a step never sees its own submissions, so a
    blind step's two sides cannot leak into each other's eligibility."""

    items: tuple[AppliedItem, ...] = ()
    current_step_index: int | None = None

    def contains(
        self,
        *,
        item_id: int,
        actions: tuple[str, ...],
        by: str,
        side: str | None,
        scope: str,
        round: int | None,
    ) -> bool:
        for applied in self.items:
            if applied.item_id != item_id or applied.action not in actions:
                continue
            if self.current_step_index is not None and applied.step_index == self.current_step_index:
                continue
            if by == "self" and applied.side != side:
                continue
            if by == "opponent" and (applied.side == "system" or applied.side == side or side is None):
                continue
            if scope == "round" and applied.round != round:
                continue
            if scope == "previous_round" and (round is None or applied.round != round - 1):
                continue
            return True
        return False


@dataclass(frozen=True, slots=True)
class RoundCtx:
    """Context of a phase's ``when``."""

    round: int
    best_of: int
    kind: str


@dataclass(frozen=True, slots=True)
class ItemCtx:
    """Context of a step's ``eligible`` / a phase's ``pool_filter``.

    ``side`` is the acting side (``None`` in a pool filter, where relative
    leaves are rejected by validation); ``target_role`` is the role of the
    opponent player the item would be named for, or ``None``.
    """

    item_id: int
    group: str | None
    kind: str
    side: str | None = None
    target_role: str | None = None
    round: int | None = None
    history: History = History()


# ── leaves ──────────────────────────────────────────────────────────────────

_OP = ParamSpec("op", "enum", values=("==", "!=", ">=", ">", "<=", "<"))
_VALUE = ParamSpec("value", "int", min=1)
_BY = ParamSpec("by", "enum", values=("self", "opponent", "any"))
_SCOPE = ParamSpec("scope", "enum", values=("series", "round", "previous_round"))

_COMPARATORS: dict[str, Callable[[int, int], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
}


def _compare(left: int, op: object, right: Any) -> bool:
    comparator = _COMPARATORS.get(str(op))
    if comparator is None:
        raise ValueError(f"unknown operator {op!r}")
    return comparator(int(left), int(right))


@leaf(type="map_index", contexts=("round",), params=(_OP, _VALUE))
def _map_index(params: Mapping[str, Any], ctx: RoundCtx) -> bool:
    return _compare(ctx.round, params["op"], params["value"])


@leaf(type="best_of", contexts=("round",), params=(_OP, _VALUE))
def _best_of(params: Mapping[str, Any], ctx: RoundCtx) -> bool:
    return _compare(ctx.best_of, params["op"], params["value"])


@leaf(type="is_last_map", contexts=("round",))
def _is_last_map(params: Mapping[str, Any], ctx: RoundCtx) -> bool:
    return ctx.round == ctx.best_of


@leaf(type="item_in", contexts=("item", "pool"), params=(ParamSpec("item_ids", "item_list"),))
def _item_in(params: Mapping[str, Any], ctx: ItemCtx) -> bool:
    return ctx.item_id in set(params.get("item_ids") or ())


@leaf(type="item_group", contexts=("item", "pool"), params=(ParamSpec("groups", "group_list"),))
def _item_group(params: Mapping[str, Any], ctx: ItemCtx) -> bool:
    if ctx.group is None:
        return False
    wanted = {normalize_group(group) for group in params.get("groups") or ()}
    return normalize_group(ctx.group) in wanted


@leaf(type="target_role_match", contexts=("item",), kinds=("hero",), requires_target=True)
def _target_role_match(params: Mapping[str, Any], ctx: ItemCtx) -> bool:
    #: A role-less (flex) player constrains nothing: every hero matches.
    target_role = normalize_group(ctx.target_role)
    if target_role is None or target_role == "flex":
        return True
    return normalize_group(ctx.group) == target_role


@leaf(type="banned_by", contexts=("item", "pool"), params=(_BY, _SCOPE), relative=True)
def _banned_by(params: Mapping[str, Any], ctx: ItemCtx) -> bool:
    return ctx.history.contains(
        item_id=ctx.item_id,
        actions=("ban",),
        by=str(params["by"]),
        side=ctx.side,
        scope=str(params["scope"]),
        round=ctx.round,
    )


@leaf(type="picked_by", contexts=("item", "pool"), params=(_BY, _SCOPE), relative=True)
def _picked_by(params: Mapping[str, Any], ctx: ItemCtx) -> bool:
    return ctx.history.contains(
        item_id=ctx.item_id,
        actions=("pick", "decider"),
        by=str(params["by"]),
        side=ctx.side,
        scope=str(params["scope"]),
        round=ctx.round,
    )


# ── constraints ─────────────────────────────────────────────────────────────

CONSTRAINTS: dict[str, ConstraintSpec] = {
    "one_per_target": ConstraintSpec("one_per_target", (), requires_target=True),
    "max_per_group": ConstraintSpec(
        "max_per_group",
        (
            ParamSpec("max", "int", min=1),
            ParamSpec("scope", "enum", values=("step", "round")),
            ParamSpec("group", "group", required=False, nullable=True),
        ),
    ),
    "min_per_group": ConstraintSpec(
        "min_per_group",
        (ParamSpec("min", "int", min=1), ParamSpec("group", "group")),
    ),
}


# ── evaluator ───────────────────────────────────────────────────────────────


def evaluate(tree: Mapping[str, Any] | None, ctx: RoundCtx | ItemCtx) -> bool:
    """Evaluate a validated condition tree. ``{}``/``None`` = true.

    Raises ``ValueError`` on a malformed tree — every stored tree went through
    :func:`validate.validate_ruleset` first, so that is a bug, not input.
    """
    if not tree:
        return True
    if "AND" in tree:
        return all(evaluate(child, ctx) for child in tree["AND"])
    if "OR" in tree:
        return any(evaluate(child, ctx) for child in tree["OR"])
    if "NOT" in tree:
        return not evaluate(tree["NOT"], ctx)
    spec = LEAVES.get(str(tree.get("type")))
    if spec is None or spec.evaluator is None:
        raise ValueError(f"unknown condition leaf {tree.get('type')!r}")
    return spec.evaluator(tree.get("params") or {}, ctx)


def catalog(groups: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    """The constructor's catalog payload (§10): every leaf and constraint
    contract, the selectable groups per kind, and the built-in presets."""
    from .presets import PRESETS

    resolved = dict(groups or {})
    return {
        "leaves": [LEAVES[name].to_json() for name in sorted(LEAVES)],
        "constraints": [CONSTRAINTS[name].to_json() for name in sorted(CONSTRAINTS)],
        "groups": {
            "hero": list(resolved.get("hero") or HERO_GROUPS),
            "map": list(resolved.get("map") or ()),
        },
        "presets": [preset.to_json() for preset in PRESETS],
    }

"""Condition tree evaluator.

Recursively evaluates a JSON condition tree (AND / OR / NOT / leaf)
and returns a set of qualifying tuples.

Tuple shapes depend on grain:
  - user grain:            (user_id,)
  - user_tournament grain: (user_id, tournament_id)
  - user_match grain:      (user_id, tournament_id, match_id)
"""

from __future__ import annotations

from functools import reduce
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.achievement_validation import GRAIN_ARITY, infer_grain, leaf_grain

from .context import EvalContext

# Type alias for result sets — tuples of ints with variable length.
ResultSet = set[tuple[int, ...]]


class GrainMismatchError(ValueError):
    """AND/OR/NOT or a leaf produced keys of mixed or unexpected grain."""


async def evaluate(
    session: AsyncSession,
    condition: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Evaluate a condition tree node and return qualifying tuples."""

    if "AND" in condition:
        children = condition["AND"]
        if not children:
            return set()
        sets = [await evaluate(session, child, context) for child in children]
        _require_uniform_arity(sets, "AND")
        return reduce(set.intersection, sets)

    if "OR" in condition:
        children = condition["OR"]
        if not children:
            return set()
        sets = [await evaluate(session, child, context) for child in children]
        _require_uniform_arity(sets, "OR")
        return reduce(set.union, sets)

    if "NOT" in condition:
        from .conditions import get_eligible_keys

        matching = await evaluate(session, condition["NOT"], context)
        grain = infer_grain(condition["NOT"])
        universe = await get_eligible_keys(session, context, grain)
        _require_uniform_arity([matching, universe], "NOT")
        return universe - matching

    # Leaf condition
    condition_type = condition.get("type")
    if not condition_type:
        logger.warning(f"Condition node missing 'type': {condition}")
        return set()

    from .conditions import execute_leaf

    params = condition.get("params", {})
    results = await execute_leaf(session, condition_type, params, context)
    expected = leaf_grain(condition_type, params if isinstance(params, dict) else None)
    if expected is not None:
        arity = GRAIN_ARITY[expected]
        if any(len(key) != arity for key in results):
            raise GrainMismatchError(f"{condition_type} must return {expected.value} keys of length {arity}")
    return results


def _require_uniform_arity(sets: list[ResultSet], op: str) -> None:
    arities = {len(key) for result in sets for key in result}
    if len(arities) > 1:
        raise GrainMismatchError(
            f"{op} cannot combine result keys of different grain (tuple lengths {sorted(arities)})"
        )

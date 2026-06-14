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

from .context import EvalContext

# Type alias for result sets — tuples of ints with variable length.
ResultSet = set[tuple[int, ...]]


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
        return reduce(set.intersection, sets)

    if "OR" in condition:
        children = condition["OR"]
        if not children:
            return set()
        sets = [await evaluate(session, child, context) for child in children]
        return reduce(set.union, sets)

    if "NOT" in condition:
        from .conditions import get_all_eligible_users

        all_eligible = await get_all_eligible_users(session, context)
        matching = await evaluate(session, condition["NOT"], context)
        # Align tuple lengths: keep only the user_id component for complement
        matching_user_ids = {t[0] for t in matching}
        return {t for t in all_eligible if t[0] not in matching_user_ids}

    # Leaf condition
    condition_type = condition.get("type")
    if not condition_type:
        logger.warning(f"Condition node missing 'type': {condition}")
        return set()

    from .conditions import execute_leaf

    params = condition.get("params", {})
    return await execute_leaf(session, condition_type, params, context)

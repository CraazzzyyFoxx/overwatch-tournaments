import typing

import sqlalchemy as sa
from sqlalchemy.orm.strategy_options import _AbstractLoad

__all__ = (
    "prepare_entities",
    "remove_from_entities",
    "find_entities",
    "join_entity",
    "selectin_entity",
)


def prepare_entities(in_entities: list[str], parent: str) -> list[str]:
    """Extract sub-entities for a given parent prefix.

    Example: prepare_entities(["players.user", "players.team", "tournament"], "players")
             -> ["user", "team"]
    """
    entities: list[str] = []
    for entity in in_entities:
        if entity.startswith(f"{parent}."):
            entities.append(entity.replace(f"{parent}.", ""))
    return entities


def remove_from_entities(in_entities: list[str], parent: str) -> list[str]:
    """Remove all entities that start with a given parent prefix."""
    return [entity for entity in in_entities if not entity.startswith(f"{parent}.")]


def find_entities(in_entities: list[str], parent: str) -> list[str]:
    """Find all entities that start with a given parent prefix."""
    return [entity for entity in in_entities if entity.startswith(f"{parent}.")]


def join_entity(child: typing.Any, entity: typing.Any) -> _AbstractLoad:
    """Build a joinedload chain, optionally nested under a parent load."""
    if child:
        return child.joinedload(entity)  # noqa
    return sa.orm.joinedload(entity)


def selectin_entity(child: typing.Any, entity: typing.Any) -> _AbstractLoad:
    """Build a selectinload chain, optionally nested under a parent load.

    Why: joinedload on to-many relationships multiplies the result set
    (one row per descendant). For nested collections like
    Encounter -> matches and Team -> players, this becomes a cartesian
    explosion that blows up memory and stalls workers. selectinload
    issues a follow-up IN(...) query per collection level instead.
    """
    if child:
        return child.selectinload(entity)  # noqa
    return sa.orm.selectinload(entity)

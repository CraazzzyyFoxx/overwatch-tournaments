"""Minimal map query surface for tournament-service.

Only the loader-options helper survives here; the full map read layer
(listing, per-user map stats) lives in app-service.
"""

import typing

from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models
from src.core import utils

__all__ = ("map_entities",)


def map_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Generates a list of SQLAlchemy loading options for related entities of a map.

    Parameters:
        in_entities (list[str]): A list of entity names to load (e.g., ["gamemode"]).
        child (typing.Any | None): Optional child entity for nested loading.

    Returns:
        list[_AbstractLoad]: A list of SQLAlchemy loading options.
    """
    entities = []
    if "gamemode" in in_entities:
        entities.append(utils.join_entity(child, models.Map.gamemode))

    return entities

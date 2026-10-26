"""Minimal map read-model surface for tournament-service.

Map statistics/top-user flows live in stats-service; encounter flows only need
``map_to_read`` to embed a map into match read models.
"""

from shared import models
from shared.schemas.catalog import CatalogEntityRead


def map_to_read(map: models.CatalogEntity, entities: list[str]) -> CatalogEntityRead:
    """The native catalog read of a map; ``parent`` (its mode) requires the parent already loaded."""
    return CatalogEntityRead.from_entity(map, with_parent="parent" in entities)

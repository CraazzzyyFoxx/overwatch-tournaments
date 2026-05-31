"""Resolve the hero catalog used to validate and persist registration top-hero picks.

Heroes are global (not workspace-scoped), so the catalog is a flat mapping from
hero slug to a light reference carrying the hero id and class. The public
registration path uses it to (a) validate that submitted slugs exist and match
the role's class and (b) translate slugs into ``hero_id`` foreign keys when
persisting ``balancer.registration_role_hero`` rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums

DEFAULT_MAX_TOP_HEROES = 5


@dataclass(frozen=True)
class HeroCatalogEntry:
    id: int
    slug: str
    hero_class: enums.HeroClass


HeroCatalog = dict[str, HeroCatalogEntry]


async def resolve_hero_catalog(session: AsyncSession) -> HeroCatalog:
    """Return ``{hero_slug: HeroCatalogEntry}`` for every hero."""
    rows = (await session.execute(sa.select(models.Hero.id, models.Hero.slug, models.Hero.type))).all()
    return {slug: HeroCatalogEntry(id=hero_id, slug=slug, hero_class=hero_class) for hero_id, slug, hero_class in rows}

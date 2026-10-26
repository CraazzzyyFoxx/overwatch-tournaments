"""Slug generation for the public tournament URL (``/tournaments/{slug}``).

The slug is generated once from ``Tournament.name`` at creation and frozen
afterward (see ``shared.models.tournament.tournament.Tournament.slug``); an
explicit admin rename goes through ``TournamentRepository`` and writes the
outgoing slug to ``TournamentSlugRedirect`` so links already shared keep resolving.

Uniqueness is GLOBAL (not per-workspace): the public tournament route carries
no workspace segment, so two organizers' "season-1" would otherwise collide.
A retired slug counts as taken too: the public resolver prefers a current slug
over a redirect, so reusing one would hijack the renamed tournament's old links.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.tournament_slug import slugify

__all__ = ("generate_unique_tournament_slug",)


async def generate_unique_tournament_slug(session: AsyncSession, name: str) -> str:
    """``slugify(name)``, disambiguated with a ``-2``, ``-3``, ... suffix while the
    candidate is a current slug or a redirect's old one."""
    base = slugify(name)
    candidate = base
    suffix = 2
    while await session.scalar(
        sa.select(
            sa.or_(
                sa.exists().where(models.Tournament.slug == candidate),
                sa.exists().where(models.TournamentSlugRedirect.old_slug == candidate),
            )
        )
    ):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate

"""Slug generation for the public tournament URL (``/tournaments/{slug}``).

The slug is generated once from ``Tournament.name`` at creation and frozen
afterward (see ``shared.models.tournament.tournament.Tournament.slug``); an
explicit admin rename goes through ``TournamentRepository`` and writes the old
value to ``TournamentSlugRedirect`` so links already shared keep resolving.

Uniqueness is GLOBAL (not per-workspace): the public tournament route carries
no workspace segment, so two organizers' "season-1" would otherwise collide.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.tournament_slug import slugify
from shared.repository.tournament import TournamentRepository

__all__ = ("generate_unique_tournament_slug",)


async def generate_unique_tournament_slug(
    session: AsyncSession,
    name: str,
    *,
    tournament_repo: TournamentRepository,
) -> str:
    """``slugify(name)``, disambiguated with a ``-2``, ``-3``, ... suffix on collision."""
    base = slugify(name)
    candidate = base
    suffix = 2
    while await tournament_repo.get_by_slug(session, candidate) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate

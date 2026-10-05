"""Fill in the Push/Clash map scores the match log cannot carry.

Load and apply around ``shared.domain.objectiveless_maps.resolve_scores``, which
owns the rules. Runs whenever the evidence can change: a log of the encounter
was parsed (``MatchLogProcessor.start``) or the encounter completed
(``serve.process_tournament_encounter_completed``).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.objectiveless_maps import (
    OBJECTIVELESS_GAMEMODES,
    AcceptedGame,
    LoggedMap,
    Series,
    resolve_scores,
)
from src import models
from src.core import enums

__all__ = ("resolve_encounter_maps",)


async def resolve_encounter_maps(session: AsyncSession, encounter_id: int) -> bool:
    """Rewrite the encounter's Push/Clash match scores; ``True`` if any changed.

    Flushes nothing and commits nothing: the caller owns the transaction.
    """
    # Analytical: the gamemode slug rides along with each match row.
    rows = (
        await session.execute(
            sa.select(models.Match, models.Gamemode.slug)
            .join(models.Map, models.Map.id == models.Match.map_id)
            .join(models.Gamemode, models.Gamemode.id == models.Map.gamemode_id)
            .where(models.Match.encounter_id == encounter_id)
        )
    ).all()
    if not any(slug in OBJECTIVELESS_GAMEMODES for _, slug in rows):
        return False

    encounter = await session.get(models.Encounter, encounter_id)
    if encounter is None:
        return False
    games = (
        await session.scalars(
            sa.select(models.EncounterGame).where(
                models.EncounterGame.encounter_id == encounter_id,
                models.EncounterGame.state == enums.EncounterGameState.CONFIRMED,
                models.EncounterGame.format == "duel",
            )
        )
    ).all()

    scores = resolve_scores(
        Series(
            home_team_id=encounter.home_team_id,
            away_team_id=encounter.away_team_id,
            completed=encounter.status == enums.EncounterStatus.COMPLETED,
            home_score=encounter.home_score,
            away_score=encounter.away_score,
        ),
        [
            LoggedMap(
                match_id=match.id,
                map_id=match.map_id,
                home_team_id=match.home_team_id,
                home_score=match.home_score,
                away_score=match.away_score,
                objectiveless=slug in OBJECTIVELESS_GAMEMODES,
            )
            for match, slug in rows
        ],
        [
            AcceptedGame(map_id=game.map_id, home_score=game.accepted_home_score, away_score=game.accepted_away_score)
            for game in games
        ],
    )

    changed = False
    for match, _slug in rows:
        score = scores.get(match.id)
        if score is not None and (match.home_score, match.away_score) != score:
            match.home_score, match.away_score = score
            changed = True
    return changed

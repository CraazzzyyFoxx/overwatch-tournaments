"""ORM → narrow DTO conversion helpers for achievements/ flows."""

from __future__ import annotations

from shared import models
from shared.repository.stats_reads import MatchReadContext
from shared.services.match_reads import participant_reads
from src import schemas


def to_tournament_link(
    tournament: models.Tournament,
) -> schemas.AchievementTournamentLink:
    return schemas.AchievementTournamentLink(
        id=tournament.id,
        name=tournament.name,
    )


def to_match_link(context: MatchReadContext) -> schemas.AchievementMatchLink:
    return schemas.AchievementMatchLink(
        id=context.match.id,
        encounter_id=context.encounter.id,
        map_id=context.match.map_entity_id,
        log_name=context.display_filename,
        duration_s=context.match.duration_s,
        participants=participant_reads(context),
    )


def to_entity_read(entity: models.CatalogEntity) -> schemas.CatalogEntityRead:
    """A rule's linked character as the catalog's own entity DTO (never expands ``parent``: a character has none)."""
    return schemas.CatalogEntityRead.from_entity(entity, with_parent=False)

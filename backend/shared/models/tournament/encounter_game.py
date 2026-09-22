"""One position of an encounter's series and its accepted result.

A ``Match`` (``matches.match``) is what a parsed log OBSERVED; this row is what
the tournament DECIDED for series position ``position``. The two are linked only
by ``encounter_game_log`` (Vertical 3); nothing here reads or writes ``Match``.
See docs/plans/2026-09-20-pregame-results-statistics-separation.md §5.1.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.catalog.map import Map
from shared.models.tournament.encounter import Encounter

__all__ = ("EncounterGame", "ENCOUNTER_GAME_STATE_ENUM", "ENCOUNTER_GAME_RESULT_SOURCE_ENUM")

ENCOUNTER_GAME_STATE_ENUM = Enum(
    enums.EncounterGameState,
    values_callable=lambda e: [x.value for x in e],
    name="encountergamestate",
    schema="tournament",
    create_type=False,
)
ENCOUNTER_GAME_RESULT_SOURCE_ENUM = Enum(
    enums.EncounterGameResultSource,
    values_callable=lambda e: [x.value for x in e],
    name="encountergameresultsource",
    schema="tournament",
    create_type=False,
)


class EncounterGame(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_game"
    __table_args__ = (
        # A cancelled game keeps its position as history; the live series has at
        # most one game per position.
        Index(
            "uq_encounter_game_encounter_position",
            "encounter_id",
            "position",
            unique=True,
            postgresql_where=text("state != 'cancelled'"),
        ),
        CheckConstraint("position >= 1", name="ck_encounter_game_position"),
        CheckConstraint(
            "accepted_home_score IS NULL OR accepted_home_score >= 0", name="ck_encounter_game_home_score"
        ),
        CheckConstraint(
            "accepted_away_score IS NULL OR accepted_away_score >= 0", name="ck_encounter_game_away_score"
        ),
        # confirmed => the whole accepted shape is present. Cancelled rows keep
        # whatever they had, which is why this is one-directional.
        CheckConstraint(
            "state != 'confirmed' OR (accepted_home_score IS NOT NULL AND accepted_away_score IS NOT NULL "
            "AND result_source IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_encounter_game_confirmed_shape",
        ),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer())
    # RESTRICT, not CASCADE: deleting a catalog map must not silently erase a
    # played position's identity (spec §5.1).
    map_id: Mapped[int | None] = mapped_column(ForeignKey(Map.id, ondelete="RESTRICT"), nullable=True, index=True)
    state: Mapped[enums.EncounterGameState] = mapped_column(
        ENCOUNTER_GAME_STATE_ENUM,
        default=enums.EncounterGameState.PLANNED,
        server_default=enums.EncounterGameState.PLANNED.value,
    )
    accepted_home_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    accepted_away_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    result_source: Mapped[enums.EncounterGameResultSource | None] = mapped_column(
        ENCOUNTER_GAME_RESULT_SOURCE_ENUM, nullable=True
    )
    # Bumped on every accepted-result write (confirm, correction). Clients and
    # events compare it; it never decreases.
    result_version: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    confirmed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    encounter: Mapped[Encounter] = relationship(back_populates="games")
    map: Mapped[Map | None] = relationship()

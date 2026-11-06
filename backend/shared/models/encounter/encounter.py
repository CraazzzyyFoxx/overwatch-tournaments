"""One meeting of N participants: the root of the match layer.

The bracket position lives in ``tournament.bracket_encounter``; a duel is
just ``slot_count = 2``.
"""

from __future__ import annotations

import typing
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums

if typing.TYPE_CHECKING:
    from shared.models.encounter.audit import EncounterResultAudit
    from shared.models.encounter.game import EncounterGame
    from shared.models.encounter.team import EncounterTeam
    from shared.models.stats.match import StatsMatch
    from shared.models.tournament.tournament import Tournament

__all__ = ("Encounter", "ENCOUNTER_STATUS_ENUM", "ENCOUNTER_RESULT_STATUS_ENUM")


ENCOUNTER_RESULT_STATUS_ENUM = Enum(
    enums.EncounterResultStatus,
    values_callable=lambda e: [x.value for x in e],
    name="encounterresultstatus",
    schema="encounter",
    create_type=False,
)

# NB: deliberately NO values_callable -- this type has always persisted the
# member NAMEs (COMPLETED/PENDING/OPEN), not the lowercase .value (see the
# status column comment below). Lives in the encounter schema since enclayer01
# moved it there with the table (dbarch01 had moved it out of public).
ENCOUNTER_STATUS_ENUM = Enum(
    enums.EncounterStatus,
    name="encounterstatus",
    schema="encounter",
    create_type=False,
)


class Encounter(db.TimeStampIntegerMixin):
    __tablename__ = "encounter"

    __table_args__ = (
        # Created CONCURRENTLY by perfidx04: status is filtered on 10+ read
        # paths (live/upcoming feeds, standings, Challonge export).
        Index("ix_encounter_tournament_status", "tournament_id", "status"),
        Index(
            "ix_encounter_status_live_upcoming",
            "tournament_id",
            "status",
            # NB: predicate uses uppercase enum NAMEs; the type moved to the
            # encounter schema with the table. The DB index created by perfidx04
            # against the then-public type keeps working -- pg stores type OIDs,
            # not names, in index predicates.
            postgresql_where=text(
                "status IN ('PENDING'::encounter.encounterstatus, 'OPEN'::encounter.encounterstatus)"
            ),
        ),
        Index("ix_encounter_workspace_id", "workspace_id"),
        Index("ix_encounter_custom_game_id", "custom_game_id"),
        Index("ix_encounter_scheduled_at", "scheduled_at"),
        Index("ix_encounter_started_at", "started_at"),
        Index("ix_encounter_ended_at", "ended_at"),
        # Target of the participations' and the bracket row's composite FKs.
        UniqueConstraint("id", "tournament_id", name="uq_encounter_id_tournament"),
        # Owner, workspace and discipline in one key: a copied column can
        # never disagree with the tournament it was copied from.
        ForeignKeyConstraint(
            ["tournament_id", "workspace_id", "discipline"],
            ["tournament.tournament.id", "tournament.tournament.workspace_id", "tournament.tournament.discipline"],
            ondelete="CASCADE",
            name="fk_encounter_owner",
        ),
        # The pickup-mix owner: same workspace and discipline as the mix.
        ForeignKeyConstraint(
            ["custom_game_id", "workspace_id", "discipline"],
            ["mix.custom_game.id", "mix.custom_game.workspace_id", "mix.custom_game.discipline"],
            ondelete="CASCADE",
            name="fk_encounter_custom_game",
        ),
        CheckConstraint("num_nonnulls(tournament_id, custom_game_id) = 1", name="ck_encounter_owner"),
        # Deferred: deleting a workspace removes its rules and its encounters in
        # one statement, and an immediate check would fire between the two.
        ForeignKeyConstraint(
            ["scoring_rule_id", "workspace_id"],
            ["encounter.scoring_rule.id", "encounter.scoring_rule.workspace_id"],
            name="fk_encounter_scoring_rule",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("best_of >= 1", name="ck_encounter_best_of"),
        CheckConstraint("slot_count >= 2", name="ck_encounter_slot_count"),
        CheckConstraint("result_version >= 0", name="ck_encounter_result_version"),
        CheckConstraint(
            "result_source IN ('games', 'series_claim', 'admin', 'import', 'host')", name="ck_encounter_result_source"
        ),
        CheckConstraint(
            "(result_status = 'confirmed') = (status = 'COMPLETED')", name="ck_encounter_confirmed_completed"
        ),
        CheckConstraint(
            "result_status <> 'confirmed' OR result_source IS NOT NULL", name="ck_encounter_confirmed_source"
        ),
        {"schema": "encounter"},
    )

    #: Copy of the owner's workspace; carried so every child key can be scoped
    #: without a join and so ``fk_encounter_owner`` can check it.
    workspace_id: Mapped[int] = mapped_column(BigInteger())
    #: Copy of the owner's discipline (``catalog.discipline.code``).
    discipline: Mapped[str] = mapped_column(String(32))
    tournament_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    #: The mix that recorded this round; exactly one of the two owners is set.
    custom_game_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    scoring_rule_id: Mapped[int] = mapped_column(BigInteger())
    name: Mapped[str] = mapped_column(String())
    #: How many slots this encounter seats: a duel is 2, a lobby is N.
    slot_count: Mapped[int] = mapped_column(Integer())
    #: How many games: the length of a Bo-N series, or a lobby's game count.
    best_of: Mapped[int] = mapped_column(Integer(), default=3, server_default="3")
    # ENCOUNTER_STATUS_ENUM persists the member NAME (COMPLETED/PENDING/OPEN), not
    # its .value (completed/pending/open) -- there is no values_callable, so any
    # raw SQL/partial-index predicate against `status` must use the uppercase NAME
    # labels (see migrations/versions/perfidx04_encounter_status_indexes.py).
    status: Mapped[enums.EncounterStatus] = mapped_column(ENCOUNTER_STATUS_ENUM, default=enums.EncounterStatus.OPEN)
    result_status: Mapped[enums.EncounterResultStatus] = mapped_column(
        ENCOUNTER_RESULT_STATUS_ENUM,
        default=enums.EncounterResultStatus.NONE,
        server_default=enums.EncounterResultStatus.NONE.value,
    )
    #: ``enums.EncounterResultSource``, or NULL while no official result exists --
    #: readers then show the running total of the confirmed games. Plain
    #: text + CHECK.
    result_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Bumped by every result write, under the row's own lock.
    result_version: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    current_game_position: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    closeness: Mapped[float | None] = mapped_column(Float(), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    # ``confirmed_at`` is the only provenance kept on the row: it is the sole
    # timestamp an admin confirmation with zero reports leaves behind, and lists
    # sort/filter on it without joining the journal. Who did it -- and every
    # earlier decision -- lives in ``result_audit``.
    confirmed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    if typing.TYPE_CHECKING:
        # Derived from game-bound native observations in ``stats/match.py``.
        has_logs: Mapped[bool]
        # Derived from the scoring rule via ``column_property`` (see
        # ``shared/models/encounter/scoring_rule.py``): ``wins`` or ``points``.
        scoring_preset: Mapped[str]

    # Joined on the owner's id alone, although the constraint behind it is the
    # three-column owner key: a many-to-one on a non-primary key cannot use the
    # identity map, so every ``encounter.tournament`` touch would emit a SELECT
    # -- including inside a delete, and inside async paths that cannot do IO on
    # attribute access.
    tournament: Mapped[Tournament] = relationship(
        primaryjoin="Encounter.tournament_id == Tournament.id",
        foreign_keys=[tournament_id],
    )
    teams: Mapped[list[EncounterTeam]] = relationship(
        back_populates="encounter",
        foreign_keys="[EncounterTeam.encounter_id]",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterTeam.slot",
    )
    games: Mapped[list[EncounterGame]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterGame.position",
    )
    result_audit: Mapped[list[EncounterResultAudit]] = relationship(
        back_populates="encounter",
        foreign_keys="[EncounterResultAudit.encounter_id]",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterResultAudit.created_at.desc()",
    )
    matches: Mapped[list[StatsMatch]] = relationship(
        "StatsMatch",
        primaryjoin="Encounter.id == StatsMatch.encounter_id",
        foreign_keys="[StatsMatch.encounter_id]",
        viewonly=True,
        order_by="StatsMatch.id",
    )

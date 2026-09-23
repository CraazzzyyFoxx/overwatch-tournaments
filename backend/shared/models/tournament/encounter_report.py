"""Per-captain encounter result reports + per-map replay codes.

Each encounter captain submits their own report independently (series score +
closeness rating), instead of the old single-slot submit/confirm flow. The final
encounter result is derived: both reports with matching scores auto-confirm the
encounter (closeness = average of the two ratings); a score mismatch marks it
disputed. Per-map match/replay codes hang off a report and, when a map-veto pool
exists, softly resolve to the picked ``overwatch.map`` at that pick order.

``EncounterReportForm`` holds the per-tournament configuration of which of those
report fields are offered and which are mandatory, plus organizer-defined custom
text fields.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.catalog.map import Map
from shared.models.identity.user import User
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.team import Team

if TYPE_CHECKING:
    pass

__all__ = (
    "EncounterCaptainReport",
    "EncounterMapCode",
    "EncounterMapReport",
    "EncounterReportForm",
)


class EncounterCaptainReport(db.TimeStampIntegerMixin):
    """One captain's independent report of an encounter's result.

    Unique per ``(encounter_id, team_id)`` — a captain re-submitting upserts this
    row (allowed until the encounter is confirmed). ``home_score``/``away_score``
    are in the encounter's home/away orientation (not the reporter's), so the two
    reports' scores compare directly for auto-confirmation.
    """

    __tablename__ = "encounter_captain_report"
    __table_args__ = (
        UniqueConstraint("encounter_id", "team_id", name="uq_encounter_captain_report_encounter_team"),
        # Still valid with a nullable ``closeness``: a SQL CHECK passes on NULL.
        CheckConstraint("closeness BETWEEN 1 AND 10", name="ck_encounter_captain_report_closeness"),
        CheckConstraint("home_score >= 0 AND away_score >= 0", name="ck_encounter_captain_report_scores"),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    # Domain player (players.user) linked to the submitting captain; SET NULL so a
    # deleted account leaves the report intact.
    reporter_user_id: Mapped[int | None] = mapped_column(ForeignKey(User.id, ondelete="SET NULL"), nullable=True)
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())
    # Nullable because the tournament's report form may disable the field entirely.
    closeness: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Organizer-defined text answers, keyed by the definition's ``key``.
    custom_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)

    encounter: Mapped[Encounter] = relationship(back_populates="captain_reports")
    team: Mapped[Team] = relationship()
    reporter: Mapped[User | None] = relationship()
    # Eager (selectin) so a report loaded by a QUERY carries its codes and no
    # later attribute touch emits IO -- that would be MissingGreenlet under async
    # SQLAlchemy. Reports are only loaded in low-volume captain endpoints, never
    # bulk on the hot encounter list, so always loading codes with a report is
    # cheap. It is not a guarantee for an instance the session merely flushed:
    # selectin is a query-time strategy, so a first touch there still falls back
    # to a lazy load and the writer must seed the collection itself (see
    # ``captain.submit_captain_report``).
    map_codes: Mapped[list[EncounterMapCode]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterMapCode.map_index",
        lazy="selectin",
    )


class EncounterMapCode(db.TimeStampIntegerMixin):
    """One per-map replay/match code within a captain's report.

    ``map_index`` is 1-based within the series. ``map_id`` is a soft link to the
    picked map when a completed veto pool exists (resolved by pick order); it is
    NULL when there is no pool or the index is beyond the picked count.
    """

    __tablename__ = "encounter_map_code"
    __table_args__ = (
        UniqueConstraint("report_id", "map_index", name="uq_encounter_map_code_report_index"),
        CheckConstraint("map_index >= 1", name="ck_encounter_map_code_index"),
        {"schema": "tournament"},
    )

    report_id: Mapped[int] = mapped_column(ForeignKey(EncounterCaptainReport.id, ondelete="CASCADE"), index=True)
    map_index: Mapped[int] = mapped_column(Integer())
    map_id: Mapped[int | None] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(32))

    report: Mapped[EncounterCaptainReport] = relationship(back_populates="map_codes")
    map: Mapped[Map | None] = relationship()


class EncounterMapReport(db.TimeStampIntegerMixin):
    """One captain side's independent claim of ONE game's score.

    Filed right after the map ends. Two agreeing claims accept the game's result
    (``EncounterGame.accepted_*``); disagreeing ones mark it ``disputed`` for an
    admin. Keyed by the GAME, never by map id: a series may play the same map
    twice. See docs/plans/2026-09-20-pregame-results-statistics-separation.md §5.2.
    """

    __tablename__ = "encounter_map_report"
    __table_args__ = (
        UniqueConstraint("game_id", "side", name="uq_encounter_map_report_game_side"),
        CheckConstraint("home_score >= 0 AND away_score >= 0", name="ck_encounter_map_report_scores"),
        CheckConstraint("side IN ('home', 'away')", name="ck_encounter_map_report_side"),
        {"schema": "tournament"},
    )

    game_id: Mapped[int] = mapped_column(ForeignKey(EncounterGame.id, ondelete="CASCADE"), index=True)
    # 'home' | 'away' in the encounter's orientation; the reporting TEAM is the
    # encounter's team on that side at confirmation time, not stored here.
    side: Mapped[str] = mapped_column(String(16))
    reporter_user_id: Mapped[int | None] = mapped_column(ForeignKey(User.id, ondelete="SET NULL"), nullable=True)
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())

    game: Mapped[EncounterGame] = relationship()
    reporter: Mapped[User | None] = relationship()


class EncounterReportForm(db.TimeStampIntegerMixin):
    """Per-tournament configuration of the captain match-report form.

    Absent row means "all defaults"; the row is created lazily on the first
    organizer save. ``built_in_fields_json`` maps a built-in field name
    (``closeness``/``map_codes``/``comment``) to ``{enabled, required}``;
    ``custom_fields_json`` is an ordered list of text-field definitions.
    """

    __tablename__ = "encounter_report_form"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_encounter_report_form_tournament"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    built_in_fields_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}", default=dict
    )
    custom_fields_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, server_default="[]", default=list
    )

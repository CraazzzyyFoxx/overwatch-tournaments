"""Per-captain encounter result reports + per-map replay codes.

Each encounter captain submits their own report independently (series score +
closeness rating), instead of the old single-slot submit/confirm flow. The final
encounter result is derived: both reports with matching scores auto-confirm the
encounter (closeness = average of the two ratings); a score mismatch marks it
disputed. Per-map match/replay codes hang off a report and, when a map-veto pool
exists, softly resolve to the picked ``overwatch.map`` at that pick order.
"""

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.catalog.map import Map
from shared.models.identity.user import User
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.team import Team

if TYPE_CHECKING:
    pass

__all__ = (
    "EncounterCaptainReport",
    "EncounterMapCode",
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
        CheckConstraint("closeness BETWEEN 1 AND 10", name="ck_encounter_captain_report_closeness"),
        CheckConstraint("home_score >= 0 AND away_score >= 0", name="ck_encounter_captain_report_scores"),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    # Domain player (players.user) linked to the submitting captain; SET NULL so a
    # deleted account leaves the report intact.
    reporter_user_id: Mapped[int | None] = mapped_column(
        ForeignKey(User.id, ondelete="SET NULL"), nullable=True
    )
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())
    closeness: Mapped[int] = mapped_column(Integer())

    encounter: Mapped[Encounter] = relationship(back_populates="captain_reports")
    team: Mapped[Team] = relationship()
    reporter: Mapped["User | None"] = relationship()
    map_codes: Mapped[list["EncounterMapCode"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterMapCode.map_index",
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

    report_id: Mapped[int] = mapped_column(
        ForeignKey(EncounterCaptainReport.id, ondelete="CASCADE"), index=True
    )
    map_index: Mapped[int] = mapped_column(Integer())
    map_id: Mapped[int | None] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(32))

    report: Mapped[EncounterCaptainReport] = relationship(back_populates="map_codes")
    map: Mapped["Map | None"] = relationship()

import typing

from sqlalchemy import Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums

if typing.TYPE_CHECKING:
    from shared.models.encounter import Encounter

__all__ = ("EncounterLink",)


ENCOUNTER_LINK_ROLE_ENUM = Enum(
    enums.EncounterLinkRole,
    values_callable=lambda e: [x.value for x in e],
    name="encounterlinkrole",
    schema="tournament",
    create_type=False,
)

ENCOUNTER_LINK_SLOT_ENUM = Enum(
    enums.EncounterLinkSlot,
    values_callable=lambda e: [x.value for x in e],
    name="encounterlinkslot",
    schema="tournament",
    create_type=False,
)


class EncounterLink(db.TimeStampIntegerMixin):
    """Directed edge describing winner/loser advancement between encounters.

    Introduced in Phase C to replace the implicit ``round``-sign based
    advancement ("round > 0 = upper, round < 0 = lower"). Makes bracket
    structure explicit, enables automatic slot filling on score change,
    and is preserved across bracket-engine regenerations via (stage_id,
    source_local_id, role) uniqueness.
    """

    __tablename__ = "encounter_link"
    __table_args__ = (
        UniqueConstraint(
            "source_encounter_id", "role", name="uq_encounter_link_source_role"
        ),
        {"schema": "tournament"},
    )

    source_encounter_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tournament.encounter.id", ondelete="CASCADE"),
        index=True,
    )
    target_encounter_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tournament.encounter.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[enums.EncounterLinkRole] = mapped_column(ENCOUNTER_LINK_ROLE_ENUM)
    target_slot: Mapped[enums.EncounterLinkSlot] = mapped_column(
        ENCOUNTER_LINK_SLOT_ENUM
    )

    source_encounter: Mapped["Encounter"] = relationship(
        foreign_keys=[source_encounter_id]
    )
    target_encounter: Mapped["Encounter"] = relationship(
        foreign_keys=[target_encounter_id]
    )

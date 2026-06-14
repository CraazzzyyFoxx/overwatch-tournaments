from sqlalchemy import Enum, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.encounter import Encounter
from shared.models.map import Map
from shared.models.stage import Stage
from shared.models.tournament import Tournament

__all__ = (
    "EncounterMapPool",
    "MapVetoConfig",
)


MAP_PICK_SIDE_ENUM = Enum(
    enums.MapPickSide,
    values_callable=lambda e: [x.value for x in e],
    name="mappickside",
    schema="tournament",
    create_type=False,
)

MAP_POOL_ENTRY_STATUS_ENUM = Enum(
    enums.MapPoolEntryStatus,
    values_callable=lambda e: [x.value for x in e],
    name="mappoolentrystatus",
    schema="tournament",
    create_type=False,
)


class EncounterMapPool(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_map_pool"
    __table_args__ = ({"schema": "tournament"},)

    encounter_id: Mapped[int] = mapped_column(
        ForeignKey(Encounter.id, ondelete="CASCADE"), index=True
    )
    map_id: Mapped[int] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="CASCADE"), index=True
    )
    order: Mapped[int] = mapped_column(Integer(), default=0)
    picked_by: Mapped[enums.MapPickSide | None] = mapped_column(
        MAP_PICK_SIDE_ENUM,
        nullable=True,
    )
    status: Mapped[enums.MapPoolEntryStatus] = mapped_column(
        MAP_POOL_ENTRY_STATUS_ENUM,
        default=enums.MapPoolEntryStatus.AVAILABLE,
        server_default=enums.MapPoolEntryStatus.AVAILABLE.value,
    )

    encounter: Mapped[Encounter] = relationship()
    map: Mapped[Map] = relationship()


class MapVetoConfig(db.TimeStampIntegerMixin):
    __tablename__ = "map_veto_config"
    __table_args__ = ({"schema": "tournament"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey(Stage.id, ondelete="CASCADE"), nullable=True
    )
    veto_sequence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    map_pool_ids: Mapped[list] = mapped_column(JSON, nullable=False)

    tournament: Mapped[Tournament] = relationship()
    stage: Mapped["Stage | None"] = relationship()

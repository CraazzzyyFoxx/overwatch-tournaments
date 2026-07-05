from sqlalchemy import JSON, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.catalog.map import Map
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.stage import Stage
from shared.models.tournament.tournament import Tournament

__all__ = (
    "EncounterMapPool",
    "MapVetoConfig",
    "MapVetoConfigMap",
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
    # Draft/ban step list (e.g. ["ban_home", "pick_away", "decider"]). This is a
    # template-shaped ordered list of opaque step tokens, not a set of FK ids, so
    # it stays JSON (see dbarch05 rationale). ``map_pool_ids`` (formerly a JSON
    # array of overwatch.map ids with no FK) was normalized into the
    # ``map_veto_config_map`` child table by dbarch05.
    veto_sequence_json: Mapped[list] = mapped_column(JSON, nullable=False)

    tournament: Mapped[Tournament] = relationship()
    stage: Mapped["Stage | None"] = relationship()
    map_pool: Mapped[list["MapVetoConfigMap"]] = relationship(
        back_populates="config",
        order_by="MapVetoConfigMap.sort_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MapVetoConfigMap(db.TimeStampIntegerMixin):
    """One map in a :class:`MapVetoConfig`'s pool.

    Normalized replacement for the old ``MapVetoConfig.map_pool_ids`` JSON
    array (a bare list of ``overwatch.map`` ids with no referential integrity).
    ``sort_order`` preserves the array position.
    """

    __tablename__ = "map_veto_config_map"
    __table_args__ = (
        UniqueConstraint(
            "map_veto_config_id", "map_id", name="uq_map_veto_config_map_config_map"
        ),
        {"schema": "tournament"},
    )

    map_veto_config_id: Mapped[int] = mapped_column(
        ForeignKey(MapVetoConfig.id, ondelete="CASCADE"), index=True
    )
    map_id: Mapped[int] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="0", default=0
    )

    config: Mapped[MapVetoConfig] = relationship(back_populates="map_pool")
    map: Mapped[Map] = relationship()

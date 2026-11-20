"""Organizer configuration of a pick-ban flow: the pool and the rules.

The rooms that run on this configuration -- sessions, boards and the submission
log -- live in the match layer (``shared.models.encounter.pick_ban``); what
stays here belongs to the tournament, not to any one encounter.
"""

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.encounter.pick_ban import PICK_BAN_KIND_ENUM
from shared.models.tournament.stage import Stage
from shared.models.tournament.tournament import Tournament

__all__ = (
    "PickBanConfig",
    "PickBanConfigItem",
    "PickBanConfigSlot",
    "PickBanConfigSlotItem",
)


# ``kind`` is the one type a config shares with the room it configures, so it
# is imported rather than redeclared. ``mode``/``rotation`` stay in the
# tournament schema: nothing in the match layer reads them.
PICK_BAN_MODE_ENUM = Enum(
    enums.MapVetoMode,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanmode",
    schema="tournament",
)

PICK_BAN_ROTATION_ENUM = Enum(
    enums.FirstBanRotation,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanrotation",
    schema="tournament",
)


class PickBanConfig(db.TimeStampIntegerMixin):
    """Organizer config for one pick-ban flow (map veto or hero bans).

    Same ``(tournament_id, stage_id, round, third_place)`` cascade as ``MapVetoConfig``, now
    partitioned additionally by ``kind`` — a tournament may run a map config and
    a hero config at the same cascade level side by side.
    """

    __tablename__ = "pick_ban_config"
    __table_args__ = (
        CheckConstraint("round IS NULL OR stage_id IS NOT NULL", name="ck_pick_ban_config_round_requires_stage"),
        CheckConstraint("NOT third_place OR round IS NOT NULL", name="ck_pick_ban_config_third_place_requires_round"),
        # No ``slots``/``preset`` cross-check any more: v2 expresses a slot veto
        # as a phase generator, so mode and ruleset cannot disagree the way the
        # v1 preset column could.
        Index(
            "uq_pick_ban_config_level",
            "tournament_id",
            "kind",
            "stage_id",
            "round",
            "third_place",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    kind: Mapped[enums.PickBanKind] = mapped_column(PICK_BAN_KIND_ENUM)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"), nullable=True)
    round: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # The bronze match shares its round with the final; this makes the config its own round-level scope.
    third_place: Mapped[bool] = mapped_column(Boolean(), default=False, server_default=sa.false())
    mode: Mapped[enums.MapVetoMode] = mapped_column(
        PICK_BAN_MODE_ENUM,
        default=enums.MapVetoMode.POOL,
        server_default=enums.MapVetoMode.POOL.value,
    )
    first_pick_rule: Mapped[enums.FirstPickRule] = mapped_column(
        Enum(
            enums.FirstPickRule,
            values_callable=lambda e: [x.value for x in e],
            name="pickbanfirstpickrule",
            schema="tournament",
        ),
        default=enums.FirstPickRule.HIGHER_SEED,
        server_default=enums.FirstPickRule.HIGHER_SEED.value,
    )
    first_ban_rotation: Mapped[enums.FirstBanRotation] = mapped_column(
        PICK_BAN_ROTATION_ENUM,
        default=enums.FirstBanRotation.FIXED,
        server_default=enums.FirstBanRotation.FIXED.value,
    )
    # Ruleset v2: phases with
    # a ``when`` round condition, a ``pool_filter``, and either a generator
    # (bracket/slot_veto, map kind) or explicit steps. Parsed and validated by
    # ``shared.domain.pick_ban_rules``; the DB keeps it opaque.
    ruleset_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    tournament: Mapped[Tournament] = relationship()
    stage: Mapped[Stage | None] = relationship()
    items: Mapped[list[PickBanConfigItem]] = relationship(
        back_populates="config",
        order_by="PickBanConfigItem.sort_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    slots: Mapped[list[PickBanConfigSlot]] = relationship(
        back_populates="config",
        order_by="PickBanConfigSlot.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PickBanConfigItem(db.TimeStampIntegerMixin):
    """One catalog item (map or hero id) in a flat-mode :class:`PickBanConfig` pool."""

    __tablename__ = "pick_ban_config_item"
    __table_args__ = (
        UniqueConstraint("pick_ban_config_id", "item_id", name="uq_pick_ban_config_item"),
        {"schema": "tournament"},
    )

    pick_ban_config_id: Mapped[int] = mapped_column(ForeignKey(PickBanConfig.id, ondelete="CASCADE"), index=True)
    # Soft reference: resolves against ``catalog.entity`` maps or characters depending on the owning config's kind.
    item_id: Mapped[int] = mapped_column(Integer(), index=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    config: Mapped[PickBanConfig] = relationship(back_populates="items")


class PickBanConfigSlot(db.TimeStampIntegerMixin):
    """One slot (one map's worth of candidates) of a slot-mode :class:`PickBanConfig`."""

    __tablename__ = "pick_ban_config_slot"
    __table_args__ = (
        UniqueConstraint("pick_ban_config_id", "position", name="uq_pick_ban_config_slot_position"),
        CheckConstraint("position >= 1", name="ck_pick_ban_config_slot_position_positive"),
        {"schema": "tournament"},
    )

    pick_ban_config_id: Mapped[int] = mapped_column(ForeignKey(PickBanConfig.id, ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer(), nullable=False)
    # Reserve item on a draw (map mode only; meaningless but harmless for hero
    # configs, which never populate it).
    reserve_item_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    config: Mapped[PickBanConfig] = relationship(back_populates="slots")
    items: Mapped[list[PickBanConfigSlotItem]] = relationship(
        back_populates="slot",
        order_by="PickBanConfigSlotItem.sort_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PickBanConfigSlotItem(db.TimeStampIntegerMixin):
    """One candidate item of a :class:`PickBanConfigSlot`."""

    __tablename__ = "pick_ban_config_slot_item"
    __table_args__ = (
        UniqueConstraint("pick_ban_config_slot_id", "item_id", name="uq_pick_ban_config_slot_item"),
        {"schema": "tournament"},
    )

    pick_ban_config_slot_id: Mapped[int] = mapped_column(
        ForeignKey(PickBanConfigSlot.id, ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(Integer(), index=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    slot: Mapped[PickBanConfigSlot] = relationship(back_populates="items")

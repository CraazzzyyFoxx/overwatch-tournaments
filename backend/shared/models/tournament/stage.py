import typing

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.tournament.tournament import Tournament

if typing.TYPE_CHECKING:
    from shared.models.tournament.team import Team

__all__ = (
    "Stage",
    "StageItem",
    "StageItemInput",
)


STAGE_TYPE_ENUM = Enum(
    enums.StageType,
    values_callable=lambda e: [x.value for x in e],
    name="stagetype",
    schema="tournament",
    create_type=False,
)

STAGE_ITEM_TYPE_ENUM = Enum(
    enums.StageItemType,
    values_callable=lambda e: [x.value for x in e],
    name="stageitemtype",
    schema="tournament",
    create_type=False,
)

STAGE_ITEM_INPUT_TYPE_ENUM = Enum(
    enums.StageItemInputType,
    values_callable=lambda e: [x.value for x in e],
    name="stageiteminputtype",
    schema="tournament",
    create_type=False,
)


class Stage(db.TimeStampIntegerMixin):
    __tablename__ = "stage"
    __table_args__ = ({"schema": "tournament"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    stage_type: Mapped[enums.StageType] = mapped_column(STAGE_TYPE_ENUM)
    max_rounds: Mapped[int] = mapped_column(Integer(), default=5, server_default="5")
    # How many teams advance from each group of this (group) stage to the next
    # stage. NULL = not configured → the frontend derives it from bracket wiring
    # or falls back to a default. Mirrors the wire-from-groups ``top`` parameter.
    advance_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Double-elimination playoff stages only: when true, the teams advancing from
    # each group (advance_count) are split evenly between the Upper and Lower
    # bracket (extra team → Upper on an odd count). When false, all advancing
    # teams seed the Upper bracket. Drives the auto-wire on activate-and-generate.
    split_lower_bracket: Mapped[bool] = mapped_column(
        Boolean(), default=False, server_default="false"
    )
    order: Mapped[int] = mapped_column(Integer(), default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), default=False, server_default="false"
    )
    is_completed: Mapped[bool] = mapped_column(
        Boolean(), default=False, server_default="false"
    )
    settings_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    tournament: Mapped[Tournament] = relationship(back_populates="stages")
    items: Mapped[list["StageItem"]] = relationship(
        uselist=True,
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StageItem.order",
    )


class StageItem(db.TimeStampIntegerMixin):
    __tablename__ = "stage_item"
    __table_args__ = ({"schema": "tournament"},)

    stage_id: Mapped[int] = mapped_column(
        ForeignKey(Stage.id, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String())
    type: Mapped[enums.StageItemType] = mapped_column(STAGE_ITEM_TYPE_ENUM)
    order: Mapped[int] = mapped_column(Integer(), default=0)

    stage: Mapped[Stage] = relationship(back_populates="items")
    inputs: Mapped[list["StageItemInput"]] = relationship(
        foreign_keys="[StageItemInput.stage_item_id]",
        uselist=True,
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StageItemInput.slot",
    )


class StageItemInput(db.TimeStampIntegerMixin):
    __tablename__ = "stage_item_input"
    __table_args__ = ({"schema": "tournament"},)

    stage_item_id: Mapped[int] = mapped_column(
        ForeignKey(StageItem.id, ondelete="CASCADE"), index=True
    )
    slot: Mapped[int] = mapped_column(Integer())
    input_type: Mapped[enums.StageItemInputType] = mapped_column(
        STAGE_ITEM_INPUT_TYPE_ENUM,
        default=enums.StageItemInputType.EMPTY,
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.team.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_stage_item_id: Mapped[int | None] = mapped_column(
        ForeignKey(StageItem.id, ondelete="SET NULL"), nullable=True
    )
    source_position: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )

    stage_item: Mapped[StageItem] = relationship(
        back_populates="inputs", foreign_keys=[stage_item_id]
    )
    team: Mapped["Team | None"] = relationship(foreign_keys=[team_id])
    source_stage_item: Mapped["StageItem | None"] = relationship(
        foreign_keys=[source_stage_item_id]
    )

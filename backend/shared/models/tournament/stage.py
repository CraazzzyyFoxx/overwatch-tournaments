import typing

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.encounter.scoring_rule import ScoringRule
from shared.models.tournament.tournament import Tournament

if typing.TYPE_CHECKING:
    from shared.models.tournament.team import Team


# text[] in Postgres. JSON under SQLite, where several test harnesses
# build this schema: a PostgreSQL ARRAY has no SQLite bind, so a list would
# reach the driver raw.
_TEXT_ARRAY = ARRAY(String()).with_variant(JSON(), "sqlite")


__all__ = (
    "Stage",
    "StageItem",
    "StageItemInput",
    "StageRoundBestOf",
    "SwissBye",
    "SwissStoppedScope",
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
    __table_args__ = (
        CheckConstraint("de_grand_final_type IN ('no_reset', 'with_reset')", name="ck_stage_de_grand_final_type"),
        CheckConstraint("seed_ranking IN ('slot', 'avg_sr', 'total_sr', 'random')", name="ck_stage_seed_ranking"),
        CheckConstraint("best_of_default >= 1", name="ck_stage_best_of_default"),
        CheckConstraint("best_of_final IS NULL OR best_of_final >= 1", name="ck_stage_best_of_final"),
        CheckConstraint("swiss_qualify_wins IS NULL OR swiss_qualify_wins >= 1", name="ck_stage_swiss_qualify_wins"),
        CheckConstraint(
            "swiss_eliminate_losses IS NULL OR swiss_eliminate_losses >= 1", name="ck_stage_swiss_eliminate_losses"
        ),
        CheckConstraint(
            "best_of_swiss_qualify IS NULL OR best_of_swiss_qualify >= 1", name="ck_stage_best_of_swiss_qualify"
        ),
        CheckConstraint(
            "best_of_swiss_eliminate IS NULL OR best_of_swiss_eliminate >= 1", name="ck_stage_best_of_swiss_eliminate"
        ),
        #: Target of ``tournament.bracket_encounter``'s composite FK.
        UniqueConstraint("id", "tournament_id", name="uq_stage_id_tournament"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    # Deferred: a stage and the rule it points at are written in one
    # transaction, and the rule may be inserted after the stage.
    scoring_rule_id: Mapped[int] = mapped_column(
        BigInteger(), ForeignKey("encounter.scoring_rule.id", deferrable=True, initially="DEFERRED")
    )
    name: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    stage_type: Mapped[enums.StageType] = mapped_column(STAGE_TYPE_ENUM)
    max_rounds: Mapped[int] = mapped_column(Integer(), default=5, server_default="5")
    # How many teams advance from each group of this (group) stage to the next
    # stage. NULL = not configured → the frontend derives it from bracket wiring
    # or falls back to a default. Mirrors the wire-from-groups ``top`` parameter.
    advance_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Group stages only: how many of each group's ``advance_count`` start in the
    # Upper bracket of the double elimination they feed; the rest start in its
    # Lower bracket. NULL = all of them start Upper. A group's own value overrides it.
    advance_upper_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    order: Mapped[int] = mapped_column(Integer(), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    # Sticky, unlike ``is_active``: set True the first time the stage is
    # activated and never cleared again, even after a later stage's
    # activation flips ``is_active`` back to False. ``admin/stage/generation.py::
    # generate_encounters`` can populate a stage's encounters while it is
    # still Draft (a preview of the bracket shape before the stage goes
    # live) -- captains cannot report or veto against those encounters
    # until this flips True (tournament-service ``src.services.bracket.usability``).
    is_published: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    is_completed: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")

    # ── Regulation. NULL means "not set here": the engine falls back to the
    # tournament (points), the stage type's preset (ranking) or the win points
    # (a Swiss bye).
    #: A ``RULE_PRESET_DEFAULTS`` key; NULL = chosen by ``stage_type``.
    ranking_preset: Mapped[str | None] = mapped_column(String(), nullable=True)
    #: The tiebreak metrics in order; NULL = the preset's order.
    tiebreak_order: Mapped[list[str] | None] = mapped_column(_TEXT_ARRAY, nullable=True)
    win_points: Mapped[float | None] = mapped_column(Float(), nullable=True)
    draw_points: Mapped[float | None] = mapped_column(Float(), nullable=True)
    loss_points: Mapped[float | None] = mapped_column(Float(), nullable=True)
    #: What a Swiss bye pays; NULL = the stage's win points.
    swiss_bye_points: Mapped[float | None] = mapped_column(Float(), nullable=True)
    #: Swiss only: a team with this many wins (byes included) is through and
    #: paired no more; NULL = it plays on.
    swiss_qualify_wins: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Swiss only: a team with this many losses is out and paired no more;
    #: NULL = it plays on.
    swiss_eliminate_losses: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Double elimination only: ``with_reset`` plays a second Grand Final when
    #: the lower-bracket team wins the first.
    de_grand_final_type: Mapped[str] = mapped_column(String(16), default="no_reset", server_default="no_reset")
    #: How a bracket orders its seeds (``src.domain.stage.seeds.SeedRanking``).
    seed_ranking: Mapped[str] = mapped_column(String(16), default="slot", server_default="slot")
    #: Series length of an encounter in a round with no ``round_best_of`` row.
    best_of_default: Mapped[int] = mapped_column(Integer(), default=3, server_default="3")
    #: An elimination stage's last round; NULL = resolved like any other round.
    best_of_final: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Swiss only: a match one of whose teams is one win from ``swiss_qualify_wins``
    #: / one loss from ``swiss_eliminate_losses``; NULL = resolved like any other.
    best_of_swiss_qualify: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    best_of_swiss_eliminate: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: The Challonge group this stage mirrors (Challonge sync's only link to it).
    challonge_group_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    # A custom bracket drawn in the admin editor (tournament-service ``src.domain.bracket.template``);
    # NULL = the format's generator draws it.
    bracket_template: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    tournament: Mapped[Tournament] = relationship(back_populates="stages")
    items: Mapped[list[StageItem]] = relationship(
        uselist=True,
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StageItem.order",
    )
    #: Loaded with the stage: every stage read carries ``best_of``.
    round_best_of: Mapped[list[StageRoundBestOf]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StageRoundBestOf.round",
    )
    #: Levels 1-2 of the scoring: what one game pays and when the
    #: encounter is over. Loaded with the stage because ``scoring`` -- which
    #: every stage read carries -- is built from it.
    scoring_rule: Mapped[ScoringRule] = relationship(lazy="selectin")

    @property
    def scoring(self) -> dict[str, typing.Any]:
        """How this stage scores, as one API block.

        Levels 1-2 come from ``encounter.scoring_rule`` (the row every encounter
        of the stage also points at), level 3 -- the points a result pays in the
        table -- from the stage's own columns. One block because an organizer
        edits them as one thing, and because splitting them put the FFA half
        under a name (``ffa_scoring``) that stopped being true the moment a duel
        had a rule row too.

        ``preset``/``formula`` read as the ``wins`` preset while the rule is not
        loaded yet (a stage being built in memory); a flushed stage always has
        one.
        """
        rule = self.__dict__.get("scoring_rule")
        return {
            "win": self.win_points,
            "draw": self.draw_points,
            "loss": self.loss_points,
            "preset": rule.preset if rule is not None else "wins",
            "columns": [dict(column) for column in (rule.columns or ())] if rule is not None else [],
            "placement_points": [float(points) for points in (rule.placement_points or ())] if rule is not None else [],
            "formula": rule.game_formula if rule is not None else "win",
        }

    @property
    def has_custom_bracket(self) -> bool:
        return self.bracket_template is not None

    @property
    def best_of(self) -> dict[str, typing.Any]:
        return {
            "default": self.best_of_default,
            "by_round": {row.round: row.best_of for row in self.round_best_of},
            "final": self.best_of_final,
            "swiss_qualify": self.best_of_swiss_qualify,
            "swiss_eliminate": self.best_of_swiss_eliminate,
        }


class StageRoundBestOf(db.Base):
    """A round's own series length, overriding ``Stage.best_of_default``.

    ``round`` is the encounter round as the bracket numbers it: negative for a
    double elimination's lower bracket.
    """

    __tablename__ = "stage_round_best_of"
    __table_args__ = (
        CheckConstraint("best_of >= 1", name="ck_stage_round_best_of_best_of"),
        {"schema": "tournament"},
    )

    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"), primary_key=True)
    round: Mapped[int] = mapped_column(Integer(), primary_key=True)
    best_of: Mapped[int] = mapped_column(Integer())


class StageItem(db.TimeStampIntegerMixin):
    __tablename__ = "stage_item"
    __table_args__ = (
        #: Target of ``tournament.bracket_encounter``'s composite FK.
        UniqueConstraint("id", "stage_id", name="uq_stage_item_id_stage"),
        {"schema": "tournament"},
    )

    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String())
    type: Mapped[enums.StageItemType] = mapped_column(STAGE_ITEM_TYPE_ENUM)
    order: Mapped[int] = mapped_column(Integer(), default=0)
    # Per-group override of ``Stage.advance_count``: how many teams advance from
    # THIS group. NULL = inherit the stage's number, which is what every group
    # did before the column existed. Set it when groups are uneven and a flat
    # "top N from each" is the wrong bar.
    advance_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Per-group override of ``Stage.advance_upper_count``; NULL = inherit.
    advance_upper_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    stage: Mapped[Stage] = relationship(back_populates="items")
    inputs: Mapped[list[StageItemInput]] = relationship(
        foreign_keys="[StageItemInput.stage_item_id]",
        uselist=True,
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StageItemInput.slot",
    )


class StageItemInput(db.TimeStampIntegerMixin):
    __tablename__ = "stage_item_input"
    __table_args__ = (
        UniqueConstraint("stage_item_id", "slot", name="uq_stage_item_input_item_slot"),
        {"schema": "tournament"},
    )

    stage_item_id: Mapped[int] = mapped_column(ForeignKey(StageItem.id, ondelete="CASCADE"), index=True)
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
    source_position: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    stage_item: Mapped[StageItem] = relationship(back_populates="inputs", foreign_keys=[stage_item_id])
    team: Mapped[Team | None] = relationship(foreign_keys=[team_id])
    source_stage_item: Mapped[StageItem | None] = relationship(foreign_keys=[source_stage_item_id])


class SwissBye(db.TimeStampIntegerMixin):
    """One bye the Swiss generator handed out: a team that sat a round out.

    A pairing never gives the same team a second bye while another is due one,
    and a bye pays ``Stage.swiss_bye_points``. The scope is the stage item the
    round was paired in (NULL for a stage without items). ``round`` is NULL only
    for byes recorded before rounds were tracked; they still count, but no round
    removal can take them back.
    """

    __tablename__ = "swiss_bye"
    __table_args__ = ({"schema": "tournament"},)

    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"), index=True)
    stage_item_id: Mapped[int | None] = mapped_column(ForeignKey(StageItem.id, ondelete="CASCADE"), nullable=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("tournament.team.id", ondelete="CASCADE"), index=True)
    round: Mapped[int | None] = mapped_column(Integer(), nullable=True)


class SwissStoppedScope(db.TimeStampIntegerMixin):
    """A Swiss scope that ran out of rematch-free pairings.

    Counts as finished for the stage's completion even short of its planned
    rounds. The scope is a stage item, or the whole stage when it has none
    (``stage_item_id`` NULL; NULLs compare equal in the unique index).
    """

    __tablename__ = "swiss_stopped_scope"
    __table_args__ = (
        Index(
            "uq_swiss_stopped_scope",
            "stage_id",
            "stage_item_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "tournament"},
    )

    stage_id: Mapped[int] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"))
    stage_item_id: Mapped[int | None] = mapped_column(ForeignKey(StageItem.id, ondelete="CASCADE"), nullable=True)

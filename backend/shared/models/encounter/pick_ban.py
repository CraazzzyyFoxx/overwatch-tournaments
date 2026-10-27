"""Pick-ban rooms, boards and the submission log, in the match layer.

The configs stay with their owner (``tournament.pick_ban_config*``). A session
snapshots its pool (``pool_json``) as well as its ruleset, so an organizer editing the config
mid-series cannot change a running room; every "which side" column is a
reference to a participation plus, where a non-participant may act, an actor
kind (``team`` | ``decider`` | ``admin`` | ``system``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.encounter.encounter import Encounter

__all__ = (
    "PickBanEntry",
    "PickBanSession",
    "PickBanSubmission",
    "PICK_BAN_ACTOR_ENUM",
    "PICK_BAN_ENTRY_STATUS_ENUM",
    "PICK_BAN_KIND_ENUM",
    "PICK_BAN_SEED_SOURCE_ENUM",
    "PICK_BAN_SESSION_STATUS_ENUM",
)


PICK_BAN_KIND_ENUM = Enum(
    enums.PickBanKind,
    values_callable=lambda e: [x.value for x in e],
    name="pickbankind",
    schema="encounter",
)

PICK_BAN_ENTRY_STATUS_ENUM = Enum(
    enums.MapPoolEntryStatus,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanentrystatus",
    schema="encounter",
)

PICK_BAN_SESSION_STATUS_ENUM = Enum(
    enums.MapVetoSessionStatus,
    values_callable=lambda e: [x.value for x in e],
    name="pickbansessionstatus",
    schema="encounter",
)

PICK_BAN_SEED_SOURCE_ENUM = Enum(
    enums.VetoSeedSource,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanseedsource",
    schema="encounter",
)

#: Who performed a board action. ``team`` is the only kind that names a
#: participation; the rest are the engine, an organizer or a tiebreak.
PICK_BAN_ACTOR_ENUM = Enum(
    enums.PickBanActorKind,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanactor",
    schema="encounter",
)


class PickBanSession(db.TimeStampIntegerMixin):
    """Lifecycle of one encounter's pick-ban room, for one ``kind``.

    ``resolved_sequence_json`` and its matching :class:`PickBanEntry` rows are
    not necessarily complete at creation: when ``first_ban_rotation`` is
    result-dependent, each map's block is appended only once the *previous*
    map's winner is known.
    """

    __tablename__ = "pick_ban_session"
    __table_args__ = (
        Index("ix_pick_ban_session_encounter_id", "encounter_id"),
        #: The room reconcile tick's per-second scan of the live, timed rooms.
        Index(
            "ix_pick_ban_session_active_unpaused",
            "encounter_id",
            postgresql_where=text("status = 'active' AND paused_at IS NULL"),
        ),
        UniqueConstraint("encounter_id", "kind", name="uq_pick_ban_session_encounter_kind"),
        #: Target of the board's and the log's composite FKs.
        UniqueConstraint("id", "encounter_id", name="uq_pick_ban_session_id_encounter"),
        ForeignKeyConstraint(
            ["first_team_id", "encounter_id"],
            ["encounter.team.id", "encounter.team.encounter_id"],
            ondelete="SET NULL (first_team_id)",
            name="fk_pick_ban_session_first_team",
        ),
        ForeignKeyConstraint(
            ["pending_chooser_team_id", "encounter_id"],
            ["encounter.team.id", "encounter.team.encounter_id"],
            ondelete="SET NULL (pending_chooser_team_id)",
            name="fk_pick_ban_session_pending_chooser",
        ),
        ForeignKeyConstraint(
            ["undo_requested_by_team_id", "encounter_id"],
            ["encounter.team.id", "encounter.team.encounter_id"],
            ondelete="SET NULL (undo_requested_by_team_id)",
            name="fk_pick_ban_session_undo_requested_by",
        ),
        {"schema": "encounter"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"))
    kind: Mapped[enums.PickBanKind] = mapped_column(PICK_BAN_KIND_ENUM)
    #: Snapshot of the config's pool as it stood when the session opened. The
    #: config may be edited, or deleted, without touching a running room.
    pool_json: Mapped[dict] = mapped_column(JSON)
    # Nullable: NULL exactly while a round is `awaiting_choice`
    # (first_ban_rotation=result_loser_choice and nobody has called
    # elect_opener yet for the round currently being appended).
    first_team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    seed_source: Mapped[enums.VetoSeedSource] = mapped_column(PICK_BAN_SEED_SOURCE_ENUM)
    # The resolved steps appended so far: one object per step, ``index`` global
    # in the session, ``round`` the map of the series it belongs to (NULL in
    # flat mode), with every inherited value already resolved (``min``,
    # ``timer_seconds``, ``on_timeout``). Compiled from ``ruleset_json`` round
    # by round, never from the config's live ruleset.
    resolved_sequence_json: Mapped[list] = mapped_column(JSON)
    slot_reserves_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Snapshot of the config's ruleset taken when the session was created.
    ruleset_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[enums.MapVetoSessionStatus] = mapped_column(
        PICK_BAN_SESSION_STATUS_ENUM,
        default=enums.MapVetoSessionStatus.ACTIVE,
        server_default=enums.MapVetoSessionStatus.ACTIVE.value,
    )
    # True exactly while the session is waiting on an `elect_opener` call for
    # the round it is about to append (result_loser_choice rotation only).
    awaiting_choice: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    # Who is entitled to call `elect_opener` while `awaiting_choice` is true --
    # the loser of the round that just triggered `RotationNeedsChoice`. NULL
    # whenever `awaiting_choice` is false.
    pending_chooser_team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    # Undo consent. A participation may ask for the session's last action to be
    # taken back; the OPPONENT's matching call applies it. The request names the
    # ``resolved_sequence_json`` STEP INDEX it was made against, so an action
    # landing in between cannot be undone by a consent meant for a different
    # one -- a new action clears the request outright. Both NULL = no request.
    undo_requested_by_team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    undo_target_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    current_step_started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    # The organizer's hold on a live room: non-NULL = paused. The step keeps the
    # time it had left (``resume`` pushes ``current_step_started_at`` forward by
    # the paused span) and no participant write is accepted meanwhile.
    paused_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    encounter: Mapped[Encounter] = relationship()
    submissions: Mapped[list[PickBanSubmission]] = relationship(
        back_populates="session",
        foreign_keys="[PickBanSubmission.session_id, PickBanSubmission.encounter_id]",
        order_by="[PickBanSubmission.step_index, PickBanSubmission.attempt, PickBanSubmission.encounter_team_id]",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PickBanEntry(db.TimeStampIntegerMixin):
    """One catalog item's state within a :class:`PickBanSession`.

    ``item_id`` resolves against the map or hero catalog per the owning
    session's ``kind``. The rows are a projection recomputed from
    :class:`PickBanSubmission` after every mutation, which is why there is no
    one-entry-per-step unique index: a duplicated position cannot survive a
    projection pass, and the backstop against a step being resolved twice lives
    on the submission log's unique key.
    """

    __tablename__ = "pick_ban_entry"
    __table_args__ = (
        Index("ix_pick_ban_entry_session_id", "session_id"),
        Index("ix_pick_ban_entry_item_id", "item_id"),
        ForeignKeyConstraint(
            ["session_id", "encounter_id"],
            ["encounter.pick_ban_session.id", "encounter.pick_ban_session.encounter_id"],
            ondelete="CASCADE",
            name="fk_pick_ban_entry_session",
        ),
        # Deferred, not ``SET NULL``: ``ck_pick_ban_entry_*_by`` cannot hold a
        # ``team`` actor without its participation, and an encounter's delete
        # reaches its participations and its rooms in whichever order Postgres
        # fires their cascades -- the entries are gone by commit either way.
        ForeignKeyConstraint(
            ["picked_by_team_id", "encounter_id"],
            ["encounter.team.id", "encounter.team.encounter_id"],
            name="fk_pick_ban_entry_picked_by",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["protected_by_team_id", "encounter_id"],
            ["encounter.team.id", "encounter.team.encounter_id"],
            name="fk_pick_ban_entry_protected_by",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["picked_for_member_id"],
            ["encounter.team_member.id"],
            ondelete="SET NULL",
            name="fk_pick_ban_entry_picked_for",
        ),
        CheckConstraint(
            "(picked_by_kind = 'team') = (picked_by_team_id IS NOT NULL)", name="ck_pick_ban_entry_picked_by"
        ),
        CheckConstraint(
            "(protected_by_kind = 'team') = (protected_by_team_id IS NOT NULL)", name="ck_pick_ban_entry_protected_by"
        ),
        {"schema": "encounter"},
    )

    session_id: Mapped[int] = mapped_column(BigInteger())
    encounter_id: Mapped[int] = mapped_column(BigInteger())
    item_id: Mapped[int] = mapped_column(Integer())
    order: Mapped[int] = mapped_column(Integer(), default=0)
    # Position in the session's applied-action order, renumbered from scratch
    # by every projection pass (one step may apply several items, so this is
    # not the step index). NULL for an untouched candidate.
    action_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Which map-of-the-series this entry belongs to. For map-kind entries this
    # IS the slot/round number (1-based); for hero-kind entries it is the same
    # round number of the map whose hero-ban phase this entry is part of -- the
    # two kinds' sessions stay in lockstep by round number, which is what lets
    # a ban's ``lifetime`` be counted in maps across both kinds alike.
    round: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    picked_by_kind: Mapped[enums.PickBanActorKind | None] = mapped_column(PICK_BAN_ACTOR_ENUM, nullable=True)
    picked_by_team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    #: Whose hero a pick is (spec §11.6 R4-1): the member step's member, or whom an ``assign`` gave it to. NULL for a
    #: ban, a protect, a map and a team pick not yet assigned.
    picked_for_member_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    status: Mapped[enums.MapPoolEntryStatus] = mapped_column(
        PICK_BAN_ENTRY_STATUS_ENUM,
        default=enums.MapPoolEntryStatus.AVAILABLE,
        server_default=enums.MapPoolEntryStatus.AVAILABLE.value,
    )
    # Set together with status=PROTECTED: who protected it. The entry is then
    # out of ban range for the rest of the round -- that immunity IS the action.
    # Protects are round-local: nothing carries one into a later round the way
    # an active ban's ``carried_from_round`` does.
    protected_by_kind: Mapped[enums.PickBanActorKind | None] = mapped_column(PICK_BAN_ACTOR_ENUM, nullable=True)
    protected_by_team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    # Set on an entry the projection must NOT touch: an active ban carried into
    # this round from round N (``lifetime`` had not expired), created once when
    # the round opened with status BANNED and the original banner in
    # ``picked_by_*``. NULL for every entry the current round's submissions own.
    carried_from_round: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    session: Mapped[PickBanSession] = relationship()


class PickBanSubmission(db.TimeStampIntegerMixin):
    """One participation's answer to one resolved step -- the action log.

    Source of truth for the room: :class:`PickBanEntry` is a projection
    recomputed from these rows after every mutation, and the cursor is derived
    from them rather than stored. A step may be answered more than once: a
    dispute or an admin reopen voids the current attempt's rows and opens
    ``attempt + 1``, which is why the unique key carries the attempt.

    ``encounter_team_id`` is NULL for a system-resolved step (a decider, a
    random fill) -- hence ``NULLS NOT DISTINCT``, which keeps the system from
    answering one step twice. ``team_member_id`` is set exactly on a member
    step's answers, one per member (spec §11.6 R4-1), and is part of the key.
    """

    __tablename__ = "pick_ban_submission"
    __table_args__ = (
        Index("ix_pick_ban_submission_session_id", "session_id"),
        Index(
            "uq_pick_ban_submission_step_team_attempt",
            "session_id",
            "step_index",
            "encounter_team_id",
            "team_member_id",
            "attempt",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("state IN ('draft', 'locked', 'revealed', 'voided')", name="ck_pick_ban_submission_state"),
        ForeignKeyConstraint(
            ["session_id", "encounter_id"],
            ["encounter.pick_ban_session.id", "encounter.pick_ban_session.encounter_id"],
            ondelete="CASCADE",
            name="fk_pick_ban_submission_session",
        ),
        ForeignKeyConstraint(
            ["encounter_team_id", "encounter_id"],
            ["encounter.team.id", "encounter.team.encounter_id"],
            name="fk_pick_ban_submission_team",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["team_member_id"],
            ["encounter.team_member.id"],
            ondelete="CASCADE",
            name="fk_pick_ban_submission_team_member",
        ),
        {"schema": "encounter"},
    )

    session_id: Mapped[int] = mapped_column(BigInteger())
    encounter_id: Mapped[int] = mapped_column(BigInteger())
    #: Position in the owning session's ``resolved_sequence_json``.
    step_index: Mapped[int] = mapped_column(Integer())
    #: NULL = the system resolved this step.
    encounter_team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    #: The member a member step's answer is for (``encounter.team_member``); NULL for a team step and the engine.
    team_member_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer(), default=1, server_default="1")
    state: Mapped[str] = mapped_column(String(16))
    # ``[{"item_id": int, "target_player_id": int | null}]`` in submission
    # order. Empty until the participation names something; a blind step keeps
    # it private (never serialized to the opponent) until everyone has locked.
    items_json: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    locked_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    revealed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    session: Mapped[PickBanSession] = relationship(
        back_populates="submissions", foreign_keys=[session_id, encounter_id]
    )

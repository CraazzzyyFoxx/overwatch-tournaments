"""Generic pick-ban engine: config, session, pool entries and the submission
log shared by map veto and hero bans.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.identity.user import User
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.stage import Stage
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament

__all__ = (
    "EncounterReadiness",
    "PickBanConfig",
    "PickBanConfigItem",
    "PickBanConfigSlot",
    "PickBanConfigSlotItem",
    "PickBanEntry",
    "PickBanSession",
    "PickBanSubmission",
)


PICK_BAN_KIND_ENUM = Enum(
    enums.PickBanKind,
    values_callable=lambda e: [x.value for x in e],
    name="pickbankind",
    schema="tournament",
)

# Reused from the map-veto domain: side/status/rotation carry the same meaning
# generalized over kind, so they get their own PG enum types here rather than
# aliasing the ``map_*``-named ones, which stay owned by the legacy tables
# until the migration drops them (Decision log #9).
PICK_BAN_MODE_ENUM = Enum(
    enums.MapVetoMode,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanmode",
    schema="tournament",
)

PICK_BAN_SIDE_ENUM = Enum(
    enums.MapPickSide,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanside",
    schema="tournament",
)

PICK_BAN_ENTRY_STATUS_ENUM = Enum(
    enums.MapPoolEntryStatus,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanentrystatus",
    schema="tournament",
)

PICK_BAN_SESSION_STATUS_ENUM = Enum(
    enums.MapVetoSessionStatus,
    values_callable=lambda e: [x.value for x in e],
    name="pickbansessionstatus",
    schema="tournament",
)

PICK_BAN_SEED_SOURCE_ENUM = Enum(
    enums.VetoSeedSource,
    values_callable=lambda e: [x.value for x in e],
    name="pickbanseedsource",
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

    Same ``(tournament_id, stage_id, round)`` cascade as ``MapVetoConfig``, now
    partitioned additionally by ``kind`` — a tournament may run a map config and
    a hero config at the same cascade level side by side.
    """

    __tablename__ = "pick_ban_config"
    __table_args__ = (
        CheckConstraint("round IS NULL OR stage_id IS NOT NULL", name="ck_pick_ban_config_round_requires_stage"),
        # No ``slots``/``preset`` cross-check any more: v2 expresses a slot veto
        # as a phase generator, so mode and ruleset cannot disagree the way the
        # v1 preset column could.
        Index(
            "uq_pick_ban_config_level",
            "tournament_id",
            "kind",
            "stage_id",
            "round",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    kind: Mapped[enums.PickBanKind] = mapped_column(PICK_BAN_KIND_ENUM)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"), nullable=True)
    round: Mapped[int | None] = mapped_column(Integer(), nullable=True)
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
    # Ruleset v2 (docs/plans/2026-09-28-pick-ban-constructor.md §1): phases with
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
    # Soft reference: resolves against ``overwatch.map`` or ``overwatch.hero``
    # depending on the owning config's ``kind`` — no FK, mirroring how
    # ``EncounterMapPool``/entry rows already carry catalog ids without one per
    # kind (a single FK column cannot target two different tables).
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


class PickBanSession(db.TimeStampIntegerMixin):
    """Lifecycle of one encounter's pick-ban room, for one ``kind``.

    Generalizes ``EncounterVetoSession``. The key behavioral change:
    ``resolved_sequence_json``/its matching :class:`PickBanEntry` rows are not
    necessarily complete at creation. When ``first_ban_rotation`` is
    result-dependent, each map's block is appended only once the *previous*
    map's winner is known (via ``Match``, see the design doc §5.3/§5.5)."""

    __tablename__ = "pick_ban_session"
    __table_args__ = (
        UniqueConstraint("encounter_id", "kind", name="uq_pick_ban_session_encounter_kind"),
        CheckConstraint("first_side IS NULL OR first_side IN ('home', 'away')", name="ck_pick_ban_session_first_side"),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    kind: Mapped[enums.PickBanKind] = mapped_column(PICK_BAN_KIND_ENUM)
    config_id: Mapped[int | None] = mapped_column(ForeignKey(PickBanConfig.id, ondelete="SET NULL"), nullable=True)
    # Nullable: NULL exactly while a round is `awaiting_choice`
    # (first_ban_rotation=result_loser_choice and nobody has called
    # elect_opener yet for the round currently being appended).
    first_side: Mapped[enums.MapPickSide | None] = mapped_column(PICK_BAN_SIDE_ENUM, nullable=True)
    seed_source: Mapped[enums.VetoSeedSource] = mapped_column(PICK_BAN_SEED_SOURCE_ENUM)
    home_seed: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    away_seed: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # The resolved steps appended so far (design doc §3): one object per step,
    # ``index`` global in the session, ``round`` the map of the series it
    # belongs to (NULL in flat mode), with every inherited value already
    # resolved (``min``, ``timer_seconds``, ``on_timeout``). Compiled from
    # ``ruleset_json`` round by round, never from the config's live ruleset.
    resolved_sequence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    slot_reserves_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Snapshot of the config's ruleset taken when the session was created
    # (design doc D6): later rounds compile from this, so an organizer editing
    # the config mid-series cannot change a running room's rules. The pools are
    # still read live from the config.
    ruleset_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[enums.MapVetoSessionStatus] = mapped_column(
        PICK_BAN_SESSION_STATUS_ENUM,
        default=enums.MapVetoSessionStatus.ACTIVE,
        server_default=enums.MapVetoSessionStatus.ACTIVE.value,
    )
    # True exactly while the session is waiting on an `elect_opener` call for
    # the round it is about to append (result_loser_choice rotation only).
    awaiting_choice: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    # Who is entitled to call `elect_opener` while `awaiting_choice` is true —
    # the loser of the round that just triggered `RotationNeedsChoice`
    # (`result_loser_choice` is the only rotation that ever sets this). NULL
    # whenever `awaiting_choice` is false. Without it `elect_opener` could not
    # tell the loser's captain from the winner's, and either could dictate the
    # next round's opener.
    pending_loser_side: Mapped[enums.MapPickSide | None] = mapped_column(PICK_BAN_SIDE_ENUM, nullable=True)
    # Undo consent. A captain may ask for the session's last action to be taken
    # back; the OPPONENT's matching call applies it (both sides agree, which is
    # what keeps a mistake from becoming a re-pick nobody consented to). The
    # request names the ``resolved_sequence_json`` STEP INDEX it was made
    # against, so an action landing in between cannot be undone by a consent
    # meant for a different one -- a new action clears the request outright.
    # Both NULL = no request open.
    undo_requested_by: Mapped[enums.MapPickSide | None] = mapped_column(PICK_BAN_SIDE_ENUM, nullable=True)
    undo_target_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    current_step_started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    # The organizer's hold on a live room: non-NULL = paused. The step keeps the
    # time it had left (``resume`` pushes ``current_step_started_at`` forward by
    # the paused span) and no captain write is accepted meanwhile, so this is the
    # one state that suspends the clock without scrapping anything.
    paused_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    encounter: Mapped[Encounter] = relationship()
    config: Mapped[PickBanConfig | None] = relationship()
    submissions: Mapped[list[PickBanSubmission]] = relationship(
        back_populates="session",
        order_by="[PickBanSubmission.step_index, PickBanSubmission.attempt, PickBanSubmission.side]",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PickBanEntry(db.TimeStampIntegerMixin):
    """One catalog item's state within a :class:`PickBanSession`.

    Generalizes ``EncounterMapPool``. ``item_id`` resolves against the map or
    hero catalog per the owning session's ``kind``.
    """

    __tablename__ = "pick_ban_entry"
    __table_args__ = (
        # No one-entry-per-step unique index any more. ``action_index`` is now
        # assigned by ``runtime.project_entries``, which rebuilds every
        # non-carried entry of the session from the submission log in one pass,
        # so a duplicated position cannot survive a projection -- and the
        # backstop against a step being resolved twice moved to
        # ``pick_ban_submission``'s (session, step, side, attempt) unique
        # constraint, which is where the actual write race now lands.
        {"schema": "tournament"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey(PickBanSession.id, ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(Integer(), index=True)
    order: Mapped[int] = mapped_column(Integer(), default=0)
    # Position in the session's applied-action order, renumbered from scratch
    # by every projection pass (one step may apply several items now, so this
    # is no longer the step index). NULL for an untouched candidate.
    action_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Which map-of-the-series this entry belongs to. For map-kind entries this
    # IS the slot/round number (1-based); for hero-kind entries it is the same
    # round number of the map whose hero-ban phase this entry is part of — the
    # two kinds' sessions stay in lockstep by round number, which is what lets
    # a ban's ``lifetime`` be counted in maps across both kinds alike.
    round: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    picked_by: Mapped[enums.MapPickSide | None] = mapped_column(PICK_BAN_SIDE_ENUM, nullable=True)
    status: Mapped[enums.MapPoolEntryStatus] = mapped_column(
        PICK_BAN_ENTRY_STATUS_ENUM,
        default=enums.MapPoolEntryStatus.AVAILABLE,
        server_default=enums.MapPoolEntryStatus.AVAILABLE.value,
    )
    team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="SET NULL"), nullable=True, index=True)
    # Set together with status=PROTECTED: which side protected it. The entry is
    # then out of ban range for the rest of the round -- that immunity IS the
    # action. Protects are round-local: nothing carries one into a later round
    # the way an active ban's ``carried_from_round`` does.
    protected_by: Mapped[enums.MapPickSide | None] = mapped_column(PICK_BAN_SIDE_ENUM, nullable=True)
    # Set on an entry the projection must NOT touch: an active ban carried into
    # this round from round N (``lifetime`` had not expired), created once when
    # the round opened with status BANNED and the original banner in
    # ``picked_by``. NULL for every entry the current round's submissions own.
    carried_from_round: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    session: Mapped[PickBanSession] = relationship()
    team: Mapped[Team | None] = relationship()


class PickBanSubmission(db.TimeStampIntegerMixin):
    """One side's answer to one resolved step -- the pick-ban action log.

    Source of truth for the room (design doc D2/D3): :class:`PickBanEntry` is a
    projection recomputed from these rows after every mutation, and the cursor
    is derived from them rather than stored. A step may be answered more than
    once: a dispute or an admin reopen voids the current attempt's rows and
    opens ``attempt + 1``, which is why the unique key carries the attempt.

    ``side`` is a plain string rather than ``PICK_BAN_SIDE_ENUM`` because a
    system-resolved step (a decider, a random fill) writes ``system``, which is
    not a captain side and must never be selectable as one.
    """

    __tablename__ = "pick_ban_submission"
    __table_args__ = (
        CheckConstraint("side IN ('home', 'away', 'system')", name="ck_pick_ban_submission_side"),
        CheckConstraint("state IN ('draft', 'locked', 'revealed', 'voided')", name="ck_pick_ban_submission_state"),
        UniqueConstraint(
            "session_id", "step_index", "side", "attempt", name="uq_pick_ban_submission_step_side_attempt"
        ),
        {"schema": "tournament"},
    )

    session_id: Mapped[int] = mapped_column(ForeignKey(PickBanSession.id, ondelete="CASCADE"), index=True)
    # Position in the owning session's ``resolved_sequence_json``.
    step_index: Mapped[int] = mapped_column(Integer())
    side: Mapped[str] = mapped_column(String(8))
    attempt: Mapped[int] = mapped_column(Integer(), default=1, server_default="1")
    state: Mapped[str] = mapped_column(String(16))
    # ``[{"item_id": int, "target_player_id": int | null}]`` in submission
    # order. Empty until the side names something; a blind step keeps it
    # private (never serialized to the opponent) until every side has locked.
    items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    locked_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    revealed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    session: Mapped[PickBanSession] = relationship(back_populates="submissions")


class EncounterReadiness(db.TimeStampIntegerMixin):
    """One captain side's confirmation that their team is ready to begin this
    encounter's pre-game phase.

    Shared across BOTH :class:`PickBanSession` kinds (map veto + hero bans):
    the same captain confirms once for the whole match, not once per kind, so
    ``ensure_pick_ban_session`` refuses to create a session of EITHER kind
    until both sides have a row here. Cleared by
    ``sync_all_pick_ban_sessions_after_team_change`` whenever either team
    assignment changes -- a confirmation made against one opponent must not
    carry over to a different one.
    """

    __tablename__ = "encounter_readiness"
    __table_args__ = (
        UniqueConstraint("encounter_id", "side", name="uq_encounter_readiness_encounter_side"),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    side: Mapped[str] = mapped_column(String(16))
    ready_user_id: Mapped[int | None] = mapped_column(ForeignKey(User.id, ondelete="SET NULL"), nullable=True)

    encounter: Mapped[Encounter] = relationship()
    ready_user: Mapped[User | None] = relationship()

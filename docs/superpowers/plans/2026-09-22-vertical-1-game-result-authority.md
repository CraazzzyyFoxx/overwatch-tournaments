# Vertical 1 — Game/result authority: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-map results of a series are owned by a new `tournament.encounter_game` row (position, map, accepted score, source, version) instead of a `matches.match` row with `source=captain_report`; the veto loop reads the previous map's outcome from the game, not from `Match`; captains report against a `game_id`; admins correct a confirmed game explicitly.

**Architecture:** Additive shared model `EncounterGame` + re-keyed `EncounterMapReport(game_id, side)`; a small `EncounterGameService` (tournament-service) owns game lifecycle and the live series score materialised into `Encounter.home_score/away_score` while `Encounter.status != COMPLETED`; `map_report.py` becomes a thin claim→reconcile→accept flow; `pick_ban_session.py` derives round outcomes and hero-round gating from games. One alembic revision converts legacy reports/captain-only matches into games. Transport: three RPC subjects replace `captain_report_map`; the room state exposes `games` + `series` instead of `map_reports`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic, FastStream RabbitMQ RPC (`@broker.subscriber`), Pydantic v2, pytest (in-memory `_Store` fakes; no Postgres in unit tests), Go gateway route tables, Next.js/TypeScript frontend with vitest.

**Spec:** `docs/plans/2026-09-20-pregame-results-statistics-separation.md` — §4.1–4.5 (model map), §5.1, §5.2, §5.3 (PLAYED removal), §6.3, §6.5, §11 (routes), §13B (backfill), §15 item 1. Rulings taken before this plan are in `.superpowers/sdd/vertical-1-game-result-authority/progress.md`.

## Global Constraints

- Shared ORM stays in `backend/shared/models/`; no tables in service `src/models` (spec §4 rule 5).
- Every DB write in services goes through `shared.repository` (`backend/tests/test_repository_boundaries.py` is a ratchet: a file that stops writing directly MUST be removed from `PENDING_REPOSITORY_MIGRATION`; never add a file to it). `await session.get(` counts as a direct write pattern — use repositories.
- Enum columns persist `.value` (lowercase) via `values_callable=lambda e: [x.value for x in e]`, PG type in schema `tournament`, model-side `create_type=False` (pattern: `encounter_result_audit.py`). `Encounter.status` is the legacy exception and persists NAMES (`'COMPLETED'`).
- Game states in this vertical: `planned`, `awaiting_result`, `disputed`, `confirmed`, `cancelled` (ruling: `selected` arrives with Vertical 2).
- `result_source` values: `captain_agreement`, `admin`, `admin_log`. A Match score is never an implicit result source (spec §5.1).
- Series score before official finalize = wins over `confirmed` non-cancelled games; number of played positions counted separately (a draw completes a position, spec §5.2/§6.3). `series_complete` = `played >= best_of or max(wins)*2 > best_of`.
- Official finalize (`shared/services/encounter/finalize.py`) stays the only writer of the official score; live materialisation runs only while `encounter.status != EncounterStatus.COMPLETED`.
- A confirmed game rejects a normal claim with 409 `result_locked`; changing it is the admin correction command with a reason (spec §6.5).
- No new `Match` row is ever written from a captain report after this vertical. `Match.source`, `Match.encounter_id`, `Match.map_index` columns stay (Vertical 3 removes them).
- Errors: 404 missing/invisible resource; 403 forbidden command; 409 `result_locked` / `downstream_started` / `map_not_selected` / bracket preview; 422 invalid config/score. Waiting for the second captain is a normal 200.
- Alembic: revision id `encgame01`, `down_revision = "draftot01"`, filename `encgame01_encounter_game_authority.py`, docstring header `Revision ID:/Revises:/Create Date:`.
- Tests: extend the in-memory `_Store` fakes; no Postgres. Frontend tests: vitest. Do not run formatters/linters/project-wide suites inside a task — run the named test files only.
- Commit after each task with a conventional message (`feat(pregame): …`, `refactor(pregame): …`, `test(pregame): …`).

---

### Task 1: Shared enums, `EncounterGame` model, re-keyed `EncounterMapReport`, audit columns, repositories

**Files:**
- Modify: `backend/shared/core/enums.py` (around L405-434)
- Create: `backend/shared/models/tournament/encounter_game.py`
- Modify: `backend/shared/models/tournament/encounter_report.py:122-168`
- Modify: `backend/shared/models/tournament/encounter_result_audit.py`
- Modify: `backend/shared/models/tournament/__init__.py` (add `from .encounter_game import *` BEFORE `.encounter_report` — the report FK references `EncounterGame.id`)
- Modify: `backend/shared/models/tournament/encounter.py:116-138` (add `games` relationship)
- Modify: `backend/shared/repository/encounter.py:81-114`, `backend/shared/repository/__init__.py` (export `EncounterGameRepository`)
- Test: `backend/shared/tests/test_encounter_game_model.py`

**Interfaces:**
- Produces: `enums.EncounterGameState`, `enums.EncounterGameResultSource`, `enums.EncounterResultAuditAction.{GAME_CONFIRM,GAME_CORRECT,GAME_CANCEL}`; `models.EncounterGame`; `models.EncounterMapReport(game_id, side, reporter_user_id, home_score, away_score)`; `models.EncounterResultAudit.{game_id, game_result_version, reason}`; `EncounterGameRepository.list_for_encounter(session, encounter_id, *, include_cancelled=False)`, `EncounterGameRepository.get_for_update(session, game_id)`; `EncounterMapReportRepository.list_for_games(session, game_ids)`.
- Removes: `enums.MapPoolEntryStatus.PLAYED`; `EncounterMapReportRepository.list_for_encounter`, `.list_for_map_slot`; `EncounterMapReport.{encounter_id,map_id,map_index,team_id}`.

- [ ] **Step 1: Enums**

In `backend/shared/core/enums.py`: delete `PLAYED = "played"` from `MapPoolEntryStatus`; append to `EncounterResultAuditAction`:

```python
    # Per-map decisions (Vertical 1). Score columns on the audit row carry the
    # GAME's accepted score for these three actions, see EncounterResultAudit.
    GAME_CONFIRM = "game_confirm"
    GAME_CORRECT = "game_correct"
    GAME_CANCEL = "game_cancel"
```

Add after `MapVetoSessionStatus`:

```python
class EncounterGameState(StrEnum):
    """Lifecycle of one position of a series (``tournament.encounter_game``)."""

    PLANNED = "planned"  # position exists, map not chosen yet (freeplay)
    AWAITING_RESULT = "awaiting_result"  # map known; waiting for both captains' claims
    DISPUTED = "disputed"  # two claims that disagree
    CONFIRMED = "confirmed"  # accepted score present
    CANCELLED = "cancelled"  # kept as history after undo/reset; never revived


class EncounterGameResultSource(StrEnum):
    CAPTAIN_AGREEMENT = "captain_agreement"
    ADMIN = "admin"
    ADMIN_LOG = "admin_log"
```

- [ ] **Step 2: Model `encounter_game.py`**

```python
"""One position of an encounter's series and its accepted result.

A ``Match`` (``matches.match``) is what a parsed log OBSERVED; this row is what
the tournament DECIDED for series position ``position``. The two are linked only
by ``encounter_game_log`` (Vertical 3); nothing here reads or writes ``Match``.
See docs/plans/2026-09-20-pregame-results-statistics-separation.md §5.1.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.catalog.map import Map
from shared.models.tournament.encounter import Encounter

__all__ = ("EncounterGame", "ENCOUNTER_GAME_STATE_ENUM", "ENCOUNTER_GAME_RESULT_SOURCE_ENUM")

ENCOUNTER_GAME_STATE_ENUM = Enum(
    enums.EncounterGameState,
    values_callable=lambda e: [x.value for x in e],
    name="encountergamestate",
    schema="tournament",
    create_type=False,
)
ENCOUNTER_GAME_RESULT_SOURCE_ENUM = Enum(
    enums.EncounterGameResultSource,
    values_callable=lambda e: [x.value for x in e],
    name="encountergameresultsource",
    schema="tournament",
    create_type=False,
)


class EncounterGame(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_game"
    __table_args__ = (
        # A cancelled game keeps its position as history; the live series has at
        # most one game per position.
        Index(
            "uq_encounter_game_encounter_position",
            "encounter_id",
            "position",
            unique=True,
            postgresql_where=text("state != 'cancelled'"),
        ),
        CheckConstraint("position >= 1", name="ck_encounter_game_position"),
        CheckConstraint(
            "accepted_home_score IS NULL OR accepted_home_score >= 0", name="ck_encounter_game_home_score"
        ),
        CheckConstraint(
            "accepted_away_score IS NULL OR accepted_away_score >= 0", name="ck_encounter_game_away_score"
        ),
        # confirmed => the whole accepted shape is present. Cancelled rows keep
        # whatever they had, which is why this is one-directional.
        CheckConstraint(
            "state != 'confirmed' OR (accepted_home_score IS NOT NULL AND accepted_away_score IS NOT NULL "
            "AND result_source IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_encounter_game_confirmed_shape",
        ),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer())
    # RESTRICT, not CASCADE: deleting a catalog map must not silently erase a
    # played position's identity (spec §5.1).
    map_id: Mapped[int | None] = mapped_column(ForeignKey(Map.id, ondelete="RESTRICT"), nullable=True, index=True)
    state: Mapped[enums.EncounterGameState] = mapped_column(
        ENCOUNTER_GAME_STATE_ENUM,
        default=enums.EncounterGameState.PLANNED,
        server_default=enums.EncounterGameState.PLANNED.value,
    )
    accepted_home_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    accepted_away_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    result_source: Mapped[enums.EncounterGameResultSource | None] = mapped_column(
        ENCOUNTER_GAME_RESULT_SOURCE_ENUM, nullable=True
    )
    # Bumped on every accepted-result write (confirm, correction). Clients and
    # events compare it; it never decreases.
    result_version: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    confirmed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    encounter: Mapped[Encounter] = relationship(back_populates="games")
    map: Mapped[Map | None] = relationship()
```

Check `Map.id` import path matches `match.py:7` (`from shared.models.catalog.map import Map`). If `db.DateTime` is not how `pick_ban.py` declares timestamps, copy the exact form from `PickBanSession.started_at`.

- [ ] **Step 3: `Encounter.games` relationship**

In `encounter.py`, next to `captain_reports` (L134-138):

```python
    games: Mapped[list[EncounterGame]] = relationship(
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EncounterGame.position",
    )
```

Add `EncounterGame` to the `TYPE_CHECKING` imports the file already uses for `EncounterResultAudit`/`Match`.

- [ ] **Step 4: Re-key `EncounterMapReport`**

Replace the class body (L122-168) with:

```python
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
```

Import `EncounterGame` from `.encounter_game`; drop the now-unused `Team`/`Map` imports if nothing else in the file uses them (`EncounterCaptainReport` likely still uses `Team` — keep what is used).

- [ ] **Step 5: Audit columns**

In `encounter_result_audit.py` add after `adopted_team_id`:

```python
    # Per-game decisions (actions game_confirm/game_correct/game_cancel): which
    # game, and its result_version AFTER the write. For those rows
    # home/away_score_before/after carry the GAME's accepted score, not the
    # series score. NULL for series-level rows.
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.encounter_game.id", ondelete="CASCADE"), nullable=True, index=True
    )
    game_result_version: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Admin's stated reason for a correction/cancel; NULL for automatic rows.
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
```

(String FK target avoids an import cycle; `Text` from sqlalchemy.)

- [ ] **Step 6: Repositories**

In `shared/repository/encounter.py` replace `EncounterMapReportRepository` (L81-114) and add the game repository:

```python
class EncounterGameRepository(BaseRepository[models.EncounterGame]):
    def __init__(self) -> None:
        super().__init__(models.EncounterGame)

    async def list_for_encounter(
        self, session: AsyncSession, encounter_id: int, *, include_cancelled: bool = False
    ) -> Sequence[models.EncounterGame]:
        query = self.select().where(models.EncounterGame.encounter_id == encounter_id)
        if not include_cancelled:
            query = query.where(models.EncounterGame.state != enums.EncounterGameState.CANCELLED)
        result = await session.execute(query.order_by(models.EncounterGame.position, models.EncounterGame.id))
        return result.scalars().all()

    async def get_for_update(self, session: AsyncSession, game_id: int) -> models.EncounterGame | None:
        result = await session.execute(
            self.select()
            .where(models.EncounterGame.id == game_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()


class EncounterMapReportRepository(BaseRepository[models.EncounterMapReport]):
    def __init__(self) -> None:
        super().__init__(models.EncounterMapReport)

    async def list_for_games(
        self, session: AsyncSession, game_ids: Sequence[int]
    ) -> Sequence[models.EncounterMapReport]:
        if not game_ids:
            return []
        result = await session.execute(
            self.select().where(models.EncounterMapReport.game_id.in_(tuple(game_ids)))
        )
        return result.scalars().all()
```

Import `enums` from `shared.core`. Export `EncounterGameRepository` in `shared/repository/__init__.py` next to `EncounterMapReportRepository` (both in the import list and `__all__`).

- [ ] **Step 7: Test (metadata-level contract)**

`backend/shared/tests/test_encounter_game_model.py`:

```python
"""The encounter_game table shape the migration and the services rely on."""

from shared.core import enums
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_report import EncounterMapReport


def test_live_position_is_unique_only_among_non_cancelled_games() -> None:
    index = next(i for i in EncounterGame.__table__.indexes if i.name == "uq_encounter_game_encounter_position")
    assert index.unique
    assert [c.name for c in index.columns] == ["encounter_id", "position"]
    assert "cancelled" in str(index.dialect_options["postgresql"]["where"])


def test_map_report_is_keyed_by_game_and_side() -> None:
    unique = next(c for c in EncounterMapReport.__table__.constraints if c.name == "uq_encounter_map_report_game_side")
    assert [c.name for c in unique.columns] == ["game_id", "side"]
    assert "team_id" not in EncounterMapReport.__table__.c
    assert "map_index" not in EncounterMapReport.__table__.c


def test_played_is_no_longer_an_entry_status() -> None:
    assert "played" not in {member.value for member in enums.MapPoolEntryStatus}
```

- [ ] **Step 8: Run**

Run: `cd backend && uv run pytest shared/tests/test_encounter_game_model.py -q`
Expected: 3 passed. Also `uv run python -c "import shared.models"` prints nothing (no mapper errors).

- [ ] **Step 9: Commit**

```bash
git add backend/shared
git commit -m "feat(pregame): EncounterGame model, map reports keyed by game, game audit columns"
```

---

### Task 2: Pure series rules in `shared/domain/pick_ban_engine.py`

**Files:**
- Modify: `backend/shared/domain/pick_ban_engine.py:303-416`
- Test: `backend/shared/tests/test_pick_ban_engine.py`

**Interfaces:**
- Produces: `MapOutcome = Literal["home","away","draw"]`; `map_outcome(home_score, away_score) -> MapOutcome`; `SeriesScore(home_wins, away_wins, played)`; `series_score(results: Iterable[tuple[int,int]]) -> SeriesScore`; `series_complete(score: SeriesScore, best_of: int) -> bool`; `resolve_round_opener(*, rotation, round_number, session_first_side, previous_round_outcome: MapOutcome | None, previous_round_loser_choice) -> Side`.
- Removes: `winner_side`, `series_decided`, `resolve_round_opener(previous_round_winner=…)` keyword.

- [ ] **Step 1: Failing tests**

Append to `test_pick_ban_engine.py`:

```python
def test_series_score_counts_wins_and_played_positions_separately() -> None:
    score = engine.series_score([(3, 1), (2, 2), (0, 2)])
    assert (score.home_wins, score.away_wins, score.played) == (1, 1, 3)


def test_series_complete_by_positions_and_by_majority() -> None:
    assert engine.series_complete(engine.SeriesScore(1, 1, 2), best_of=2)  # Bo2 1:1 ends
    assert engine.series_complete(engine.SeriesScore(2, 0, 2), best_of=3)  # majority
    assert not engine.series_complete(engine.SeriesScore(1, 1, 2), best_of=3)
    assert engine.series_complete(engine.SeriesScore(1, 1, 3), best_of=3)  # a draw used the last position


def test_result_rotations_fall_back_to_the_snapshot_side_on_a_draw() -> None:
    for rotation in (
        enums.FirstBanRotation.RESULT_WINNER_FIRST,
        enums.FirstBanRotation.RESULT_LOSER_FIRST,
        enums.FirstBanRotation.RESULT_LOSER_CHOICE,
    ):
        assert (
            engine.resolve_round_opener(
                rotation=rotation,
                round_number=2,
                session_first_side="away",
                previous_round_outcome="draw",
                previous_round_loser_choice=None,
            )
            == "away"
        )


def test_result_rotations_refuse_a_pending_outcome() -> None:
    with pytest.raises(ValueError):
        engine.resolve_round_opener(
            rotation=enums.FirstBanRotation.RESULT_LOSER_FIRST,
            round_number=2,
            session_first_side="home",
            previous_round_outcome=None,
            previous_round_loser_choice=None,
        )
```

Run: `cd backend && uv run pytest shared/tests/test_pick_ban_engine.py -q` → FAIL (`series_score` undefined).

- [ ] **Step 2: Implement**

Replace `winner_side`/`series_decided` (L391-416) with:

```python
MapOutcome = Literal["home", "away", "draw"]


def map_outcome(home_score: int, away_score: int) -> MapOutcome:
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


@dataclass(frozen=True)
class SeriesScore:
    home_wins: int
    away_wins: int
    played: int  # confirmed positions, draws included


def series_score(results: Iterable[tuple[int, int]]) -> SeriesScore:
    """Wins and played positions over CONFIRMED games' accepted (home, away) scores."""
    home = away = played = 0
    for home_score, away_score in results:
        played += 1
        outcome = map_outcome(home_score, away_score)
        home += outcome == "home"
        away += outcome == "away"
    return SeriesScore(home, away, played)


def series_complete(score: SeriesScore, best_of: int) -> bool:
    """Every position played (Bo2 1:1, or a draw consuming the last map), or one
    side past half. Wins alone cannot say this: a drawn map adds no win but does
    use a position (spec §6.3)."""
    if best_of < 1:
        return False
    return score.played >= best_of or max(score.home_wins, score.away_wins) * 2 > best_of
```

Change `resolve_round_opener`: parameter `previous_round_outcome: MapOutcome | None` replaces `previous_round_winner`. For the two `RESULT_*_FIRST` rotations: `None` → `ValueError`; `"draw"` → `session_first_side`; else winner/other as before. For `RESULT_LOSER_CHOICE`: `"draw"` → `session_first_side` (no loser, no choice); `None` outcome → `ValueError`; otherwise the existing `RotationNeedsChoice` rule. Update the docstring accordingly (draw = fixed snapshot side; None = caller bug).

Add `Iterable`, `Literal` imports. Update the module's own existing callers of `winner_side`/`series_decided` inside this file (there are none besides tests). Do NOT touch service callers in this task — Task 5 migrates them.

- [ ] **Step 3: Run** the file → all pass (existing tests that used `winner_side`/`series_decided`/`previous_round_winner` must be rewritten to the new names in this same step, keeping their behaviour claims).

- [ ] **Step 4: Commit** `refactor(pregame): series score and map outcome as pure rules; draw keeps the snapshot opener`

---

### Task 3: Migration `encgame01` with a pure backfill planner

**Files:**
- Create: `backend/shared/domain/encounter_game_backfill.py`
- Create: `backend/migrations/versions/encgame01_encounter_game_authority.py`
- Test: `backend/shared/tests/test_encounter_game_backfill.py`

**Interfaces:**
- Produces: `plan_games(reports: Sequence[LegacyReport], captain_matches: Sequence[LegacyCaptainMatch], encounters: Mapping[int, EncounterSides]) -> BackfillPlan` where `BackfillPlan.games: list[PlannedGame]`, `BackfillPlan.report_keys: dict[int, tuple[int, str]]` (legacy report id → (game key, side)), `BackfillPlan.orphan_report_ids: list[int]`, `BackfillPlan.conflicts: list[str]` (human-readable, non-empty ⇒ migration must abort).

- [ ] **Step 1: Planner test first** (`backend/shared/tests/test_encounter_game_backfill.py`)

```python
from datetime import UTC, datetime

from shared.domain.encounter_game_backfill import (
    EncounterSides,
    LegacyCaptainMatch,
    LegacyReport,
    plan_games,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
SIDES = {1: EncounterSides(home_team_id=10, away_team_id=20)}


def test_positioned_agreeing_reports_become_one_confirmed_game() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=1, team_id=10, home_score=2, away_score=1, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=1, team_id=20, home_score=2, away_score=1, created_at=T0),
        ],
        [],
        SIDES,
    )
    assert plan.conflicts == []
    [game] = plan.games
    assert (game.encounter_id, game.position, game.map_id, game.state) == (1, 1, 5, "confirmed")
    assert (game.accepted_home_score, game.accepted_away_score) == (2, 1)
    assert plan.report_keys == {1: (game.key, "home"), 2: (game.key, "away")}


def test_disagreeing_reports_make_a_disputed_game_and_one_side_awaits() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=1, team_id=10, home_score=2, away_score=1, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=1, team_id=20, home_score=1, away_score=2, created_at=T0),
            LegacyReport(id=3, encounter_id=1, map_id=6, map_index=2, team_id=10, home_score=2, away_score=0, created_at=T0),
        ],
        [],
        SIDES,
    )
    assert [g.state for g in plan.games] == ["disputed", "awaiting_result"]


def test_captain_only_match_without_reports_becomes_a_confirmed_game() -> None:
    plan = plan_games(
        [],
        [LegacyCaptainMatch(id=77, encounter_id=1, map_id=5, map_index=2, home_score=1, away_score=0, created_at=T0)],
        SIDES,
    )
    [game] = plan.games
    assert (game.position, game.state, game.accepted_home_score) == (2, "confirmed", 1)
    assert plan.deleted_match_ids == [77]


def test_legacy_zero_index_rows_are_ordered_after_explicit_positions_by_creation() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=0, team_id=10, home_score=1, away_score=0, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=0, team_id=20, home_score=1, away_score=0, created_at=T0),
            LegacyReport(id=3, encounter_id=1, map_id=6, map_index=0, team_id=10, home_score=0, away_score=1, created_at=T0.replace(day=2)),
        ],
        [],
        SIDES,
    )
    assert [(g.position, g.map_id) for g in plan.games] == [(1, 5), (2, 6)]


def test_same_map_twice_without_positions_is_a_conflict_not_a_guess() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=0, team_id=10, home_score=1, away_score=0, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=0, team_id=10, home_score=0, away_score=1, created_at=T0.replace(day=2)),
        ],
        [],
        SIDES,
    )
    assert plan.conflicts and "encounter 1" in plan.conflicts[0]


def test_report_from_a_team_no_longer_in_the_encounter_is_an_orphan() -> None:
    plan = plan_games(
        [LegacyReport(id=9, encounter_id=1, map_id=5, map_index=1, team_id=99, home_score=1, away_score=0, created_at=T0)],
        [],
        SIDES,
    )
    assert plan.orphan_report_ids == [9]
    assert plan.games == []
```

Run → FAIL (module missing).

- [ ] **Step 2: Planner**

`backend/shared/domain/encounter_game_backfill.py` — pure, no SQLAlchemy:

```python
"""Plan the one-time conversion of legacy per-map results into encounter_game rows.

Inputs are the legacy shapes as they exist BEFORE migration ``encgame01``:
``encounter_map_report(encounter_id, map_id, map_index, team_id, …)`` and
``matches.match`` rows with ``source='captain_report'``. Output is a plan the
migration applies verbatim. Rules (spec §13B): explicit ``map_index>0`` is the
position; legacy index 0 / NULL rows are ordered by creation time AFTER every
explicit position, one game per distinct map; the same map twice without a
position is a conflict that aborts the migration; nothing is guessed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EncounterSides:
    home_team_id: int | None
    away_team_id: int | None


@dataclass(frozen=True)
class LegacyReport:
    id: int
    encounter_id: int
    map_id: int
    map_index: int
    team_id: int
    home_score: int
    away_score: int
    created_at: datetime


@dataclass(frozen=True)
class LegacyCaptainMatch:
    id: int
    encounter_id: int
    map_id: int
    map_index: int | None
    home_score: int
    away_score: int
    created_at: datetime


@dataclass
class PlannedGame:
    key: tuple[int, int]  # (encounter_id, position) — the migration maps it to the new id
    encounter_id: int
    position: int
    map_id: int
    state: str
    accepted_home_score: int | None = None
    accepted_away_score: int | None = None
    confirmed_at: datetime | None = None


@dataclass
class BackfillPlan:
    games: list[PlannedGame] = field(default_factory=list)
    report_keys: dict[int, tuple[tuple[int, int], str]] = field(default_factory=dict)
    orphan_report_ids: list[int] = field(default_factory=list)
    deleted_match_ids: list[int] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
```

`plan_games` algorithm (implement exactly):
1. Drop reports whose `team_id` is neither side of their encounter → `orphan_report_ids`; side = `"home"` if `team_id == home_team_id` else `"away"`.
2. Per encounter, collect *items* = reports with `map_index > 0` and captain matches with `map_index` not None, grouped by position. A position group with more than one distinct `map_id` → conflict `"encounter {id}: position {n} names maps {sorted ids}"`.
3. Legacy items (report `map_index == 0`, match `map_index is None`) per encounter: sort by `(created_at, id)`; assign positions `max_explicit + 1, +2, …` one per distinct `map_id` in first-seen order; a `map_id` already used at an explicit position, or seen twice in legacy items with a gap (i.e. another map between), → conflict `"encounter {id}: legacy rows play map {map_id} twice; set map_index by hand"`. Reports and a captain match for the same legacy `map_id` share the game.
4. State per game: both sides reported and equal → `confirmed` with that score, `confirmed_at = max(created_at)`; both reported, differ → `disputed`; one side → `awaiting_result`; no reports but a captain match → `confirmed` from the match (`confirmed_at = match.created_at`). If the captain match disagrees with agreed reports → conflict.
5. Every captain match consumed → `deleted_match_ids`.
6. `report_keys[report.id] = (game.key, side)`.

- [ ] **Step 3: Run planner tests** → pass.

- [ ] **Step 4: Migration**

`backend/migrations/versions/encgame01_encounter_game_authority.py` — `revision="encgame01"`, `down_revision="draftot01"`. Upgrade, in order (use `op.execute(sa.text(...))` / `op.get_bind()`; PG enum labels are lowercase `.value`s):

1. `CREATE TYPE tournament.encountergamestate AS ENUM ('planned','awaiting_result','disputed','confirmed','cancelled')`; `CREATE TYPE tournament.encountergameresultsource AS ENUM ('captain_agreement','admin','admin_log')`.
2. `ALTER TYPE tournament.encounterresultauditaction ADD VALUE IF NOT EXISTS 'game_confirm'` (and `game_correct`, `game_cancel`).
3. `op.create_table("encounter_game", …, schema="tournament")` matching Task 1 exactly (columns, FKs with `ondelete`, checks, `created_at/updated_at` as `TimeStampIntegerMixin` defines them — copy from `chat01` or `pbstep0001`), then the partial unique index.
4. `ALTER TABLE tournament.encounter_result_audit ADD COLUMN game_id …, game_result_version integer, reason text` + FK + index.
5. Load legacy rows: `SELECT id, encounter_id, map_id, map_index, team_id, home_score, away_score, created_at FROM tournament.encounter_map_report`; `SELECT id, encounter_id, map_id, map_index, home_score, away_score, created_at FROM matches.match WHERE source = 'captain_report'`; `SELECT id, home_team_id, away_team_id FROM tournament.encounter WHERE id IN (…)`. Build the dataclasses, call `plan_games`. If `plan.conflicts`: `raise RuntimeError("encgame01 cannot map legacy results unambiguously:\n" + "\n".join(conflicts))` — the migration aborts (transaction rolls back) and the operator fixes `map_index` by hand (spec §13B).
6. Insert planned games (`INSERT … RETURNING id`), remember `key → id`.
7. `ALTER TABLE tournament.encounter_map_report ADD COLUMN game_id bigint, ADD COLUMN side varchar(16)`; `UPDATE … SET game_id=:g, side=:s WHERE id=:id` per `report_keys`; `DELETE … WHERE id IN orphan_report_ids`; then `ALTER COLUMN game_id SET NOT NULL`, `side SET NOT NULL`, add FK (CASCADE) + index + `uq_encounter_map_report_game_side` + `ck_encounter_map_report_side`; drop `uq_encounter_map_report_encounter_map_index_team`, `ck_encounter_map_report_index`, and columns `encounter_id, map_id, map_index, team_id` (and their indexes).
8. `DELETE FROM matches.match WHERE id IN deleted_match_ids` — log `len(deleted_match_ids)` and the ids with the alembic logger (this is the manifest for dev; production Stage A produces its own).
9. `UPDATE tournament.pick_ban_entry SET status = 'picked' WHERE status = 'played'` (the PG label stays on the type; document in the docstring).
10. Re-materialise live scores for open encounters:
```sql
UPDATE tournament.encounter e
SET home_score = s.home_wins, away_score = s.away_wins
FROM (
  SELECT encounter_id,
         COUNT(*) FILTER (WHERE accepted_home_score > accepted_away_score) AS home_wins,
         COUNT(*) FILTER (WHERE accepted_away_score > accepted_home_score) AS away_wins
  FROM tournament.encounter_game WHERE state = 'confirmed' GROUP BY encounter_id
) s
WHERE s.encounter_id = e.id AND e.status <> 'COMPLETED'
```

Downgrade: recreate the four legacy report columns from `encounter_game` (`encounter_id`, `map_id`, `map_index = position`, `team_id` from `encounter.home/away_team_id` by `side`), drop `game_id/side`, drop audit columns, drop `encounter_game`, drop the two types. Deleted captain-only matches are NOT restored — say so in the docstring (spec §13D: no lossy automatic downgrade after cutover; this is the pre-cutover dev path).

- [ ] **Step 5: Verify the migration module loads and the planner is wired**

Run: `cd backend && uv run python -c "import importlib.util,pathlib; p=pathlib.Path('migrations/versions/encgame01_encounter_game_authority.py'); s=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.revision, m.down_revision)"` → `encgame01 draftot01`.
If a local Postgres is reachable (`docker compose ps` shows `postgres` healthy), also run `uv run alembic upgrade head` then `uv run alembic downgrade draftot01` then `upgrade head` and record the output in the report; otherwise state that only the import check ran.

- [ ] **Step 6: Commit** `feat(pregame): encgame01 — encounter_game table and legacy result backfill`

---

### Task 4: `EncounterGameService` — game lifecycle and live series score

**Files:**
- Create: `backend/tournament-service/src/services/encounter/games.py`
- Create: `backend/shared/services/encounter/game_audit.py` (one helper next to `result_audit.py`)
- Test: `backend/tournament-service/tests/test_encounter_games.py`

**Interfaces (all consumed by Tasks 5–7):**

```python
class EncounterGameService:
    def __init__(self, *, game_repo=EncounterGameRepository(), report_repo=EncounterMapReportRepository(), entry_repo=PickBanEntryRepository()) -> None
    async def list_games(self, session, encounter_id: int) -> list[EncounterGame]            # live, by position
    async def reports_by_game(self, session, games: Sequence[EncounterGame]) -> dict[int, list[EncounterMapReport]]
    async def sync_games_with_picks(self, session, encounter: Encounter, map_pick_ban: PickBanSession) -> list[EncounterGame]
    async def ensure_freeplay_game(self, session, encounter: Encounter) -> EncounterGame | None
    def live_score(self, games: Sequence[EncounterGame]) -> engine.SeriesScore
    def materialize_series_score(self, encounter: Encounter, games: Sequence[EncounterGame]) -> None
    async def accept_result(self, session, encounter, game, *, home_score: int, away_score: int, source: EncounterGameResultSource, actor_user_id: int | None, reason: str | None = None) -> EncounterGame
    async def select_map(self, session, encounter, game, *, map_id: int) -> EncounterGame
    async def cancel_games(self, session, encounter, games: Sequence[EncounterGame], *, actor_user_id: int | None, reason: str) -> None
    def serialize(self, game: EncounterGame, reports: Sequence[EncounterMapReport]) -> dict[str, Any]
    def serialize_series(self, encounter: Encounter, games: Sequence[EncounterGame]) -> dict[str, Any]

encounter_game_service = EncounterGameService()
```

`shared/services/encounter/game_audit.py`:
```python
def record_game_result_transition(session, encounter, game, *, action: EncounterResultAuditAction, source: str, actor_user_id: int | None, home_score_before: int | None, away_score_before: int | None, reason: str | None = None) -> EncounterResultAudit
```
It writes via the same `_result_audit.add` the sibling helper uses, with `game_id=game.id`, `game_result_version=game.result_version`, `home_score_after=game.accepted_home_score`, `away_score_after=game.accepted_away_score`, `to_result_status=encounter.result_status`, `from_result_status=encounter.result_status`.

Behaviour to implement:
- `sync_games_with_picks`: `entries = list_by_session(map_pick_ban.id)`; `settled = engine.settled_in_order(entries)`; `games = list_games`. For `position, entry in enumerate(settled, 1)`: if no live game at `position` → `create(EncounterGame(encounter_id, position, map_id=entry.item_id, state=AWAITING_RESULT))`; if a live game exists with `map_id != entry.item_id` and state in (PLANNED, AWAITING_RESULT) and no reports → set `map_id`. Live games with `position > len(settled)` and state != CONFIRMED and no reports → `cancel_games(..., reason="pick_undone")`. Never touches confirmed games (the undo guard in Task 5 refuses before this runs). Returns refreshed live list.
- `ensure_freeplay_game`: `games = list_games`; if `series_complete(live_score(games), best_of)` → None; if any game state in (PLANNED, AWAITING_RESULT, DISPUTED) → that game; else if `len(games) < best_of` → create `EncounterGame(position=max(positions, default=0)+1, state=PLANNED)`.
- `live_score`: `engine.series_score((g.accepted_home_score, g.accepted_away_score) for g in games if g.state == CONFIRMED)`.
- `materialize_series_score`: `if encounter.status != EncounterStatus.COMPLETED: encounter.home_score, encounter.away_score = score.home_wins, score.away_wins`.
- `accept_result`: `before = (game.accepted_home_score, game.accepted_away_score)`; set accepted scores, `result_source`, `confirmed_at=now(UTC)`, `state=CONFIRMED`, `result_version += 1`; `record_game_result_transition(action=GAME_CONFIRM if before == (None, None) else GAME_CORRECT, source=source.value, …)`; `materialize_series_score`; `flush`; return game.
- `select_map`: game must be live and not CONFIRMED; if it has reports and `map_id` differs → 409 `map_locked`; set `map_id`, `state = AWAITING_RESULT if state == PLANNED else state`.
- `cancel_games`: for each: was_confirmed → audit `GAME_CANCEL` (before = accepted, after = accepted); `state = CANCELLED`; then `materialize_series_score` over remaining live games; flush.
- `serialize`: `{"id","position","map_id","state","accepted_home_score","accepted_away_score","result_source","result_version","confirmed_at"(iso or None),"reports":[{"side","home_score","away_score"}]}` sorted by side home, away.
- `serialize_series`: `{"home_wins","away_wins","played","complete": series_complete(...),"official": {"home_score","away_score"} if encounter.status == COMPLETED else None}`.

HTTP errors use `shared.core.errors.BaseAPIException` the way `map_report.py` does today (it imports `HTTPException`/`status` — copy the exact import lines).

- [ ] **Step 1: Failing tests** (`test_encounter_games.py`; copy the `sys.path` bootstrap L27-34 and the `_Store`/`_matches`/`_Result` fakes from `test_pregame_loop.py` into a shared helper module `tournament-service/tests/_pregame_store.py` and import it from BOTH test files — add `EncounterGame` to the recognised model set and support `_matches` for `ne` on enum values; make `test_pregame_loop.py` import the helper instead of defining its own). Tests:

```python
async def test_picks_create_awaiting_games_and_an_undone_pick_cancels_its_game():
    # session with picks for 11 then 22 -> games at positions 1,2 with those maps;
    # remove the second pick's status -> sync cancels game 2 (state cancelled), game 1 untouched

async def test_freeplay_opens_one_planned_game_at_a_time_until_the_series_is_complete():
    # best_of=3, no games -> planned #1; while #1 open -> same game; confirm #1 (2:0) -> planned #2;
    # confirm #2 as 2:0 -> series complete -> None

async def test_accept_result_materialises_live_score_only_before_official_finalize():
    # encounter.status OPEN: accept 2:1 on game 1 -> encounter 1:0, game confirmed, version 1, audit game_confirm;
    # set encounter.status COMPLETED with 0:0 -> accept 0:2 on game 2 -> encounter still 0:0

async def test_a_draw_counts_as_played_but_not_as_a_win():
    # accept 1:1 -> live_score == SeriesScore(0, 0, 1); serialize_series()["played"] == 1

async def test_cancelling_a_confirmed_game_writes_a_cancel_audit_and_rematerialises():
```

Run: `cd backend && uv run pytest tournament-service/tests/test_encounter_games.py -q` → FAIL (module missing).

- [ ] **Step 2: Implement** `games.py` and `game_audit.py` per the interface above. All writes go through repositories (`game_repo.create`, attribute mutation on loaded rows + `session.flush()`); no `session.add`.

- [ ] **Step 3: Run** the new test file and `test_pregame_loop.py` (must still pass after the store extraction) → pass.

- [ ] **Step 4: Commit** `feat(pregame): EncounterGameService owns game lifecycle and the live series score`

---

### Task 5: The series loop reads games — `pick_ban_session`, `pick_ban_action`, `pick_ban_undo`, `advancement`, `map_report`

**Files:**
- Modify: `backend/tournament-service/src/services/encounter/pick_ban_session.py` (L141-164 `__init__`, L315-347, L563-616, L618-810, L848-990)
- Modify: `backend/tournament-service/src/services/encounter/pick_ban_action.py` (L326-342, L373-421 `auto_complete_decider`, L588-676)
- Modify: `backend/tournament-service/src/services/encounter/pick_ban_undo.py:127-217`
- Modify: `backend/shared/services/bracket/advancement.py:202-263`
- Rewrite: `backend/tournament-service/src/services/encounter/map_report.py`
- Modify: `backend/tests/test_repository_boundaries.py:96-98` (remove `map_report.py` from `PENDING_REPOSITORY_MIGRATION` once it has no direct writes; keep `pick_ban_session.py` only if it still writes directly — check with the regex in the file)
- Tests: `tournament-service/tests/test_pregame_loop.py`, `test_pick_ban_session.py`, `test_pick_ban_undo.py`, `test_map_report_correction.py`, `test_cascade_reset_reports.py`, `test_notification_producers.py:~510`

**Interfaces:**
- Consumes: Task 2 engine, Task 4 service.
- Produces: `MapReportService.submit_map_report(session, encounter, *, game_id: int, side: str, reporter_user_id: int | None, home_score: int, away_score: int) -> dict` returning `{"disputed": bool, "resolved": bool, "game": <serialize>}`; `PickBanSessionService.map_round_outcome(session, encounter, round_number) -> MapOutcome | None`; `PickBanSessionService.advance_to_next_round(..., outcome: MapOutcome | None, loser_choice=None, commit=True)`; room state fields `games` and `series` (MAP kind, including the unavailable/freeplay state); `map_reports` removed.
- Removes: `find_series_match`, `map_round_winner`, `_resolved_report_rounds`, `MatchRepository` from `PickBanSessionService`, `_pending_play`, `_freeplay_index`, `_map_reports`.

- [ ] **Step 1: Update tests to the new contract first** (they define the behaviour; run them to see them fail):
  - `test_pregame_loop.py`: every `submit_map_report(... map_id=..., team_id=...)` call becomes `submit_map_report(... game_id=<id of the game at that position from state["games"]>, side="home"|"away")`; assertions on `state["map_reports"]` become assertions on `state["games"][i]["reports"]` / `["state"]` / `["accepted_*"]`; assertions on `encounter.home_score` stay. Add these scenarios (spec V01/V02/R01):
    - `test_scrim_series_rotates_on_the_game_outcome_without_a_match_row` — the scrim container path opens round 2 with the loser first under `RESULT_LOSER_FIRST` exactly like a tournament.
    - `test_result_loser_choice_after_a_draw_opens_the_next_round_on_the_snapshot_side_without_a_choice`.
    - `test_hero_round_n_plus_one_waits_for_confirmed_game_n_even_when_the_map_is_picked` (V03).
    - `test_a_confirmed_game_rejects_a_new_claim_with_409_result_locked`.
    - `test_two_agreeing_claims_count_the_win_once_and_a_re_submitted_identical_claim_changes_nothing`.
  - `test_pick_ban_session.py`: `map_round_winner` tests → `map_round_outcome` reading `EncounterGame` rows in the fake (return `"home"`/`"away"`/`"draw"`/`None`); remove `Match` fixtures from the fake.
  - `test_pick_ban_undo.py`: add `test_map_undo_is_refused_once_the_game_has_a_claim` (400) and `test_map_undo_cancels_the_unclaimed_game`.
  - `test_map_report_correction.py`: rewrite to the new flow (a disputed game accepts corrected agreeing claims; a confirmed game returns 409).
  - `test_cascade_reset_reports.py`: cascade reset also cancels live games; admin reopen re-materialises the live score from confirmed games (not 0).
  - `test_notification_producers.py`: dispute payload is `{"encounter_id","tournament_id","game_id","position","map_id"}`.

- [ ] **Step 2: `pick_ban_session.py`**
  - `__init__`: replace `match_repo: MatchRepository` with `games: EncounterGameService = encounter_game_service`.
  - `settled_map_rounds`: count `status == PICKED` only.
  - Delete `find_series_match`, `map_round_winner`, `_resolved_report_rounds`. Add:
    ```python
    async def map_round_outcome(self, session, encounter, round_number: int) -> engine.MapOutcome | None:
        """Confirmed outcome of series position ``round_number``; None while pending."""
        if round_number < 1:
            return None
        game = next((g for g in await self.games.list_games(session, encounter.id) if g.position == round_number), None)
        if game is None or game.state != EncounterGameState.CONFIRMED:
            return None
        return engine.map_outcome(game.accepted_home_score, game.accepted_away_score)
    ```
  - `advance_to_next_round(..., outcome: engine.MapOutcome | None, ...)`: remove the "winner None → FIXED" fallback (L713-718). If `rotation` is result-dependent and `outcome is None` and `next_round > 1` → `return pick_ban` (the round is owed later). Pass `previous_round_outcome=outcome` to `resolve_round_opener`. Keep `RotationNeedsChoice` handling; a `"draw"` never raises it (Task 2).
  - `sync_hero_rounds`: `games = await self.games.list_games(session, encounter.id)`; `score = self.games.live_score(games)`; `if engine.series_complete(score, encounter.best_of): return`; `confirmed = score.played`; with a map pool: `target = min(settled_map_rounds, confirmed + 1, best_of)`; freeplay: `target = min(confirmed + 1, best_of)`. In the loop use `outcome = await self.map_round_outcome(session, encounter, highest)` and pass `outcome=outcome`. Keep the `RotationNeedsChoice` branch (pending_loser_side = other(outcome)).
  - `sync_pick_ban_session_after_team_change`: replace the PLAYED count with `games = list_games(...)`; `if any(g.state == CONFIRMED for g in games): return` (admin resets by hand); else reset. Update the comment: the cascade reset cancels games first, so a matchup change always resets; score is not consulted (spec §6.5).
  - `reset_pick_ban_session`: for `kind == MAP`, before deleting the session: `await self.games.cancel_games(session, encounter, await self.games.list_games(session, encounter.id), actor_user_id=None, reason="map_session_reset")`.
  - Check `ensure_pick_ban_session` for a `map_round_settled` use — unchanged semantics (PICKED only).

- [ ] **Step 3: `pick_ban_action.py`**
  - `__init__`: add `games: EncounterGameService = encounter_game_service`; drop `map_report_repo`.
  - `auto_complete_decider`: after a decider resolves for `kind == MAP`, call `await self.games.sync_games_with_picks(session, encounter, pick_ban)` (load the encounter through `encounter_repo`), then commit as today.
  - `perform_pick_ban_action`: after `auto_complete_decider`, for `kind == MAP` and `action == "pick"` call `sync_games_with_picks` and commit (games appear without a read).
  - `get_pick_ban_state`: for `kind == MAP`: if `pick_ban is not None` → `games = await self.games.sync_games_with_picks(...)`; else (freeplay/unavailable) → `await self.games.ensure_freeplay_game(session, encounter)` then `games = list_games`. In both branches: `reports = await self.games.reports_by_game(session, games)`; `state["games"] = [self.games.serialize(g, reports.get(g.id, [])) for g in games]`; `state["series"] = self.games.serialize_series(encounter, games)`. Delete `_map_reports` and every `state["map_reports"]`.

- [ ] **Step 4: `pick_ban_undo.py`**
  - In `perform_undo` for `kind == MAP`, after computing `entries`: `settled = engine.settled_in_order(pool)`; `positions = [i for i, e in enumerate(settled, 1) if e in entries]`; load `games = list_games`; for each game at those positions: `if game.state == CONFIRMED or reports_by_game(...)[game.id]: raise HTTPException(400, "Undo is not possible: this map already has a result claim")`. After `apply_undo` and ledger cleanup: `await self.sessions.games.sync_games_with_picks(session, encounter, pick_ban)` (load the encounter via `EncounterRepository`).

- [ ] **Step 5: `advancement.reset_encounter_result`** (approved direct-write file):
  - `CASCADE_RESET` branch: `await session.execute(sa.update(EncounterGame).where(EncounterGame.encounter_id == encounter.id, EncounterGame.state != enums.EncounterGameState.CANCELLED).values(state=enums.EncounterGameState.CANCELLED))` next to the captain-report delete; scores stay 0.
  - `REOPEN`: after zeroing, recompute: `rows = (await session.execute(sa.select(EncounterGame.accepted_home_score, EncounterGame.accepted_away_score).where(EncounterGame.encounter_id == encounter.id, EncounterGame.state == CONFIRMED))).all()`; `score = engine.series_score(rows)`; `encounter.home_score, encounter.away_score = score.home_wins, score.away_wins`. Import `pick_ban_engine as engine` from `shared.domain`.

- [ ] **Step 6: Rewrite `map_report.py`**

```python
class MapReportService:
    def __init__(self, *, report_repo=EncounterMapReportRepository(), games: EncounterGameService = encounter_game_service) -> None: ...

    async def submit_map_report(self, session, encounter, *, game_id, side, reporter_user_id, home_score, away_score) -> dict:
        if not await is_encounter_live(session, encounter): raise 409 (same text as today)
        game = await self.games.game_repo.get_for_update(session, game_id)
        if game is None or game.encounter_id != encounter.id or game.state == CANCELLED: raise 404 "Game not found"
        if game.state == CONFIRMED: raise HTTPException(409, detail=[ApiExc(code="result_locked", msg="This map's result is already accepted; ask an organizer to correct it")])
        if game.map_id is None: raise 409 code="map_not_selected"
        reports = list(await self.report_repo.list_for_games(session, [game.id]))
        row = next((r for r in reports if r.side == side), None)
        other = next((r for r in reports if r.side != side), None)
        if row is None:
            row = await self.report_repo.create(session, EncounterMapReport(game_id=game.id, side=side))
            reports.append(row)
        row.reporter_user_id, row.home_score, row.away_score = reporter_user_id, home_score, away_score
        await emit_pick_ban_update(session, encounter.id)            # both topics, as today
        await emit_pick_ban_update(session, encounter.id, kind=PickBanKind.HERO.value)
        await session.flush()
        pair = engine.MapReportPair(home_report=..., away_report=...)   # from row/other by side
        reconciliation = engine.reconcile_map_reports(pair)
        if reconciliation.resolved is None:
            if reconciliation.disputed:
                game.state = DISPUTED
                await self._notify_dispute(session, encounter, game=game, reporter_auth_user_id=reporter_user_id)
            await session.commit()
            return {"disputed": reconciliation.disputed, "resolved": False, "game": self.games.serialize(game, reports)}
        resolved_home, resolved_away = reconciliation.resolved
        await self.games.accept_result(session, encounter, game, home_score=resolved_home, away_score=resolved_away,
                                       source=EncounterGameResultSource.CAPTAIN_AGREEMENT, actor_user_id=None)
        games = await self.games.list_games(session, encounter.id)
        map_pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter.id, PickBanKind.MAP)
        if map_pick_ban is not None and not engine.series_complete(self.games.live_score(games), encounter.best_of):
            outcome = engine.map_outcome(resolved_home, resolved_away)
            try:
                await pick_ban_session_service.advance_to_next_round(session, map_pick_ban, completed_round=game.position, outcome=outcome, commit=False)
            except engine.RotationNeedsChoice:
                map_pick_ban.awaiting_choice = True
                map_pick_ban.pending_loser_side = "away" if outcome == "home" else "home"
                await session.flush()
        elif map_pick_ban is None:
            await self.games.ensure_freeplay_game(session, encounter)
        await emit(session, scope=Scope.tournament(encounter.tournament_id), invalidates=[Resource.TOURNAMENT_ENCOUNTERS], entity_ids={"encounter_ids": [encounter.id]})
        await session.commit()
        return {"disputed": False, "resolved": True, "game": self.games.serialize(game, reports)}
```

`_notify_dispute(session, encounter, *, game, reporter_auth_user_id)` keeps the recipient logic; payload `{"encounter_id", "tournament_id", "game_id": game.id, "position": game.position, "map_id": game.map_id}`. Delete the `is_scrim_container` branch, `Match` import, `_pending_play`, `_freeplay_index`. The file must contain no `session.add(` — then remove it from `PENDING_REPOSITORY_MIGRATION`.

- [ ] **Step 7: Run** `cd backend && uv run pytest tournament-service/tests/test_pregame_loop.py tournament-service/tests/test_pick_ban_session.py tournament-service/tests/test_pick_ban_undo.py tournament-service/tests/test_pick_ban_action.py tournament-service/tests/test_map_report_correction.py tournament-service/tests/test_cascade_reset_reports.py tournament-service/tests/test_notification_producers.py tournament-service/tests/test_encounter_games.py tests/test_repository_boundaries.py -q` → all pass.

- [ ] **Step 8: Commit** `feat(pregame): the series loop reads map outcomes from encounter games; captain claims target a game`

---

### Task 6: Admin correction of a game result (spec §6.5 cases 1–3)

**Files:**
- Create: `backend/tournament-service/src/services/encounter/game_correction.py`
- Test: `backend/tournament-service/tests/test_game_correction.py`

**Interfaces:**
- Produces: `GameCorrectionService.correct(session, encounter, *, game_id: int, home_score: int, away_score: int, actor_user_id: int, reason: str) -> dict` returning `{"game": serialize, "rebuilt_rounds": [int]}`; singleton `game_correction_service`.
- Consumes: `encounter_game_service`, `pick_ban_session_service.advance_to_next_round/sync_hero_rounds`, `PickBanEntryRepository`, `build_round_sequence`.

Rules:
1. Game must be live (404 otherwise). Not confirmed (awaiting/disputed/planned-with-map) → `accept_result(source=ADMIN, actor, reason)`; then the same next-round opening `submit_map_report` does (extract that tail into `MapReportService.open_next_round(session, encounter, game, outcome)` in Task 5's file and call it from both — do this refactor here).
2. Confirmed and `map_outcome` unchanged → `accept_result` (writes `GAME_CORRECT`, bumps version); no round changes.
3. Confirmed and outcome changed:
   - Dependent tail = for MAP and HERO sessions: any `PickBanEntry` with `round > game.position` and `action_index IS NOT NULL`; any live game with `position > game.position` that is confirmed or has reports. If any → `HTTPException(409, detail=[ApiExc(code="downstream_started", msg="Later maps already have actions or claims; correct them first or reset the series")])`.
   - Else rebuild: for each session (MAP if `rounds_are_progressive`, HERO): delete entries with `round == game.position + 1` (repository `delete` per row or a repo method `delete_for_round(session_id, round)` you add to `PickBanEntryRepository`); truncate `resolved_sequence_json` to the token count of rounds `1..position`: `sum(len(build_round_sequence(config, kind, candidate_count=len([e for e in entries if e.round == r]), opener=MapPickSide.HOME)) for r in range(1, position+1))` — flat map sessions (entries with `round is None`) are left alone; clear `awaiting_choice/pending_loser_side`; cancel a live unclaimed game at `position + 1` (via `cancel_games`, reason `"correction_rebuild"`) — only when a MAP session exists (freeplay planned games stay). Then `accept_result(source=ADMIN)`, `advance_to_next_round(map_pick_ban, completed_round=position, outcome=new)` and `sync_hero_rounds(commit=False)`. Return the rebuilt round numbers.
4. Commit once at the end.

- [ ] **Step 1: Tests first** in `test_game_correction.py` using the shared store helper: score-only correction keeps round 2's opener; outcome flip with an untouched round 2 rebuilds it with the new opener (assert `resolved_sequence_json` tail and the round-2 entries' `picked_by is None`); outcome flip after a ban in round 2 → 409 `downstream_started`; correcting a disputed game accepts it with `result_source == "admin"` and opens the next round.
- [ ] **Step 2: Implement**, run the file + `test_pregame_loop.py` → pass.
- [ ] **Step 3: Commit** `feat(pregame): admin corrects a game result; an untouched next round is rebuilt on the new outcome`

---

### Task 7: Transport — RPC subjects, schemas, gateway routes, encounter read, achievement leaf, OpenAPI

**Files:**
- Modify: `backend/tournament-service/src/schemas/captain.py:41-47` (rename `MapReportInput` → `GameReportInput`; add `GameMapSelectInput(map_id: int)`)
- Modify: `backend/tournament-service/src/rpc/public_rpc.py:379-399` (replace `_captain_report_map` with `_captain_report_game` on `rpc.tournament.captain_report_game`, `game_id = _path_int(data, "game_id")`, `side = await captain_service.resolve_captain_side(...)`; add `_captain_select_game_map` on `rpc.tournament.captain_select_game_map` calling `encounter_game_service.select_map` after loading the game with `get_for_update` and checking `game.encounter_id == encounter.id`, then commit and return `{"game": serialize}`)
- Modify: `backend/tournament-service/src/rpc/pick_ban_admin.py` (add `AdminGameResultInput(home_score: int = Field(ge=0), away_score: int = Field(ge=0), reason: str = Field(min_length=1, max_length=500))` and `_admin_game_result` on `rpc.tournament.admin_game_result`, permission `ensure_workspace_permission(user, ws_id, "match", "update")`, `record_admin_audit(action="encounter.game_result", …)`, then `game_correction_service.correct(...)`)
- Modify: `backend/tournament-service/src/openapi_schemas.py:441`, `backend/tournament-service/src/openapi_docs.py:1029` (replace the `captain_report_map` entries with the three subjects; describe permissions and the 409 codes)
- Modify: `gateway/internal/tournament/public_routes.go:25` → two routes:
  `{Method: "POST", Pattern: "/api/v1/encounters/{encounter_id}/games/{game_id}/report", Queue: "rpc.tournament.captain_report_game", IDParam: "encounter_id", Path: []string{"game_id"}, Body: true, Auth: edge.AuthRequired}` and the same shape for `/games/{game_id}/map` → `rpc.tournament.captain_select_game_map`.
  `gateway/internal/tournament/admin_misc_routes.go:42` → add `{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/games/{game_id}/result", Queue: "rpc.tournament.admin_game_result", IDParam: "encounter_id", Path: []string{"game_id"}, Body: true, Auth: edge.AuthRequired}` (copy the admin auth mode used by `pick-ban-elect-opener`).
- Modify: `backend/tournament-service/src/schemas/encounter.py:73-100` add `games: list[EncounterGameRead] = []` where `EncounterGameRead(id, position, map_id, state, accepted_home_score, accepted_away_score, result_source, result_version, confirmed_at)`; `services/encounter/flows.py::to_pydantic` fills it from `encounter.games` (add `selectinload(models.Encounter.games)` wherever `Encounter.matches` is eager-loaded for the public read).
- Modify: `backend/parser-service/src/services/achievement/engine/conditions/participation.py:54-58,83-85` — for `metric == "map_reports"`: `encounter_col = models.EncounterGame.encounter_id` and add `.join(models.EncounterGame, models.EncounterGame.id == models.EncounterMapReport.game_id)` before the `Encounter` join. Update `parser-service/tests/test_achievement_nodes_participation.py` fixtures to the new columns.
- Regenerate: `backend/scripts/export_openapi_schemas.sh` (→ `gateway/internal/openapi/schemas.json`); run `uv run python backend/scripts/check_rpc_docs.py` and `uv run pytest tests/test_rpc_route_parity.py tests/test_rpc_error_code_parity.py -q` from `backend/`.

- [ ] **Step 1** Write a test in `tournament-service/tests/test_public_rpc_games.py` (or extend the existing public RPC test module if one covers `captain_report_map`) that the report handler resolves `side` from the caller and passes `game_id` through; and that `admin_game_result` demands the permission.
- [ ] **Step 2** Implement everything above; delete every `captain_report_map` mention (`scrim.py:11` docstring too).
- [ ] **Step 3** Run the parity tests, the new test, `parser-service/tests/test_achievement_nodes_participation.py`, and the manifest export; `git diff --stat gateway/internal/openapi/schemas.json` must show the three new subjects and the removed one.
- [ ] **Step 4: Commit** `feat(api): report and select-map on a game id; admin game result correction; encounter read exposes games`

---

### Task 8: Frontend — room, dialog, encounter page on games

**Files:**
- Modify: `frontend/src/types/tournament.types.ts:330-406` — delete `PickBanMapReport`; add
  ```ts
  export type EncounterGameState = "planned" | "awaiting_result" | "disputed" | "confirmed" | "cancelled";
  export interface PickBanGameReport { side: "home" | "away"; home_score: number; away_score: number }
  export interface PickBanGame {
    id: number; position: number; map_id: number | null; state: EncounterGameState;
    accepted_home_score: number | null; accepted_away_score: number | null;
    result_source: "captain_agreement" | "admin" | "admin_log" | null; result_version: number;
    confirmed_at: string | null; reports: PickBanGameReport[];
  }
  export interface PickBanSeries { home_wins: number; away_wins: number; played: number; complete: boolean; official: { home_score: number; away_score: number } | null }
  ```
  and on `PickBanState`: `games?: PickBanGame[]; series?: PickBanSeries;` replacing `map_reports`.
- Modify: `frontend/src/types/encounter.types.ts` — `Encounter.games: EncounterGame[]` (same shape minus `reports`); keep `Match.source` typing until Vertical 3.
- Modify: `frontend/src/services/pickBan.service.ts:20-29,95-105` — `reportGame(encounterId, gameId, {home_score, away_score}) → {disputed, resolved, game: PickBanGame}`; `selectGameMap(encounterId, gameId, {map_id}) → {game: PickBanGame}`; admin `correctGameResult(encounterId, gameId, {home_score, away_score, reason})` at `/api/v1/admin/encounters/${encounterId}/games/${gameId}/result`.
- Modify: `frontend/src/components/pick-ban/pick-ban-model.ts` — delete `agreedMapScore`; add `gameAtPosition(games: PickBanGame[], position: number): PickBanGame | null` and `acceptedScore(game): {home, away} | null`; remove the `"played"` member from `PickBanStatusLabelKey`/`statusLabelKey`; keep `seriesMatchesByPosition` (parsed matches still carry `map_index` in this vertical).
- Modify: `frontend/src/components/pick-ban/MapReportDialog.tsx` — prop `game: PickBanGame` instead of `mapId`; call `reportGame(encounterId, game.id, …)`; when `game.state === "planned"` (freeplay) show the map picker and call `selectGameMap` first; disable the form and show the accepted score when `state === "confirmed"`.
- Modify: `PregameRoom.tsx` (L355-500 region) and `PregameMapResult.tsx` — read `mapState.games`/`mapState.series` (per-position card: map, claims per side, disputed/confirmed badges, accepted score); series header shows `series.home_wins:series.away_wins` and `official` when present.
- Modify: `PregameAdminControls.tsx` — add "Correct result" per confirmed/disputed game: two score inputs + required reason → `correctGameResult`; surface 409 `downstream_started` message.
- Modify: `frontend/src/app/(site)/encounters/[id]/components/EncounterMapRow.tsx` and `page.tsx:299` — iterate `encounter.games` by position; attach the parsed `match` whose `map_index === game.position` (fallback: same `map_id` unmatched yet); render accepted score from the game and the parsed score from the match separately (two contracts, spec §11); delete the `match.source === "captain_report"` branch.
- Tests: `pick-ban-model.test.ts` (replace `agreedMapScore` cases with `gameAtPosition`/`acceptedScore`), `pregameRoom.behavior.test.tsx` (fixtures use `games`), and the encounter page test if one exists.
- i18n: add the new keys in every locale file the touched components use (find them with `grep -rn "pregame\." frontend/src/i18n` or the project's messages directory), sentence case per the repo's copy rules.

- [ ] **Step 1** Update tests/fixtures to the new payloads → run `cd frontend && npx vitest run src/components/pick-ban src/app/\(site\)/tournaments` → FAIL.
- [ ] **Step 2** Implement; `npx tsc --noEmit` clean; the two test globs pass.
- [ ] **Step 3** Smoke in the browser if the dev stack is up (`make dev-up`): open a pregame room, report a map from both captains, see the accepted score and the next round open. Record a screenshot path in the report; if no stack, say so.
- [ ] **Step 4: Commit** `feat(frontend): pregame room and encounter page render games; captains report against a game`

---

### Task 9: Docs and generated artifacts

**Files:**
- Modify: `docs/glossary.md` — add `EncounterGame` (series position + accepted result) and re-describe `EncounterMapReport` (claim per game side); note `Match` is no longer written from captain reports.
- Modify: `docs/plans/2026-09-20-pregame-results-statistics-separation.md` — under `## 15`, mark item 1 `✅ implemented (branch feat/pregame-game-authority)` with the revision id `encgame01`.
- Regenerate ERD: `cd backend && uv run python scripts/export_erd.py` (check its `--help`/docstring for the output path) and commit the changed diagram.
- [ ] Run the full backend suite once: `cd backend && uv run pytest -q` and `cd frontend && npx vitest run` — all green; fix only failures caused by this branch.
- [ ] **Commit** `docs(pregame): glossary and ERD for encounter games`

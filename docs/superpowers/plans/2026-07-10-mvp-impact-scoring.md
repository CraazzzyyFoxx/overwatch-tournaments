# MVP Impact Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Гибридный MVP: новый официальный MVP по роль-нормализованному z-скору с событиями (ImpactPoints/ImpactRank), бейдж «Сверх ожиданий» (OverperformanceScore, базлайны роль×ранг), старые PerformancePoints сохраняются и отображаются рядом.

**Architecture:** Новые событийные статы (FirstPicks/FirstDeaths/UltimateKills/SupportKills) считаются из kill_feed в существующем пайплайне parser-service и пишутся в `matches.statistics` новыми членами `LogStatsName`. Impact-скоринг — чистый модуль `impact.py` (rate за 10 мин → winsorized z по лиговым базлайнам → взвешенный композит × time_share), базлайны — версионированная таблица `matches.stat_baselines` + джоба пересчёта. Бэкфилл — idempotent CLI. app-service отдаёт новые поля рядом с `performance`, фронт переключает MVP-пилюли на `impact_rank` и добавляет бейдж.

**Tech Stack:** Python 3.13 (uv workspace в `backend/`), SQLAlchemy 2 async + asyncpg, pandas, FastStream/RabbitMQ (typed RPC), alembic, cashews; frontend Next.js + TypeScript, тесты `bun test`.

**Spec:** `docs/superpowers/specs/2026-07-10-mvp-impact-scoring-design.md`

## Global Constraints

- `Enum(...)` в SQLAlchemy персистит **ИМЯ** члена (`'FirstPicks'`, `'tank'`), не `.value` — все raw SQL/миграции пишутся по именам.
- Весовые константы формулы и порог бейджа живут в **одном** модуле `backend/shared/core/impact.py` (версия `impact_v1`); parser и app-service импортируют оттуда.
- Базлайн-строки с `rank_bucket = -1` — общероль-баз (V4); `0..2` — терцили ранга (V3). NULL не используется (уникальный констрейнт).
- Матчи без kill_feed: событийные статы **не пишутся**, событийные z = 0 (не штрафуют).
- Python-команды: `cd backend && uv run ...`. Тесты parser: `uv run pytest parser-service/tests/... -v`; app: `uv run pytest app-service/tests/... -v`. Frontend: `cd frontend && bun test <path>`.
- **НЕ выполнять `alembic upgrade head` против БД из dev-окружения** (env указывает на прод): миграции проверяются только рендером `alembic upgrade <rev> --sql`. Применение — на деплое.
- Коммиты: conventional commits (`feat:`, `fix:`, `docs:`…), без атрибуции. Стейджить `git add <точные пути>` (не `-u`).
- i18n: ключи в `frontend/src/i18n/messages/{ru,en}.json`, RU-плюрали только ICU; оба словаря правятся в одной задаче.
- Ruff-конфиг в корне `backend/`; после правок Python — `uv run ruff check <paths> --fix` и `uv run ruff format <paths>`.

---

### Task 1: Shared-константы формулы + новые члены LogStatsName

**Files:**
- Create: `backend/shared/core/impact.py`
- Modify: `backend/shared/core/enums.py` (класс `LogStatsName`, `_log_stats_default_direction`, `__all__` не трогаем — enums экспортируются классами)
- Test: `backend/parser-service/tests/test_impact_constants.py`

**Interfaces:**
- Produces: `shared.core.impact.FORMULA_VERSION: str = "impact_v1"`, `IMPACT_WEIGHTS: dict[str, float]` (ключи = ИМЕНА членов LogStatsName), `EVENT_STATS: tuple[str, ...]`, `WINSOR_LIMIT=3.0`, `BADGE_THRESHOLD=2.0`, `MIN_SECONDS=60.0`, `RANK_BUCKETS=3`, `BASELINE_MIN_MINUTES=3.0`; новые члены enum: `FirstPicks`, `FirstDeaths`, `UltimateKills`, `SupportKills`, `ImpactPoints`, `ImpactRank`, `OverperformanceScore`.

- [ ] **Step 1: Write the failing test**

```python
# backend/parser-service/tests/test_impact_constants.py
from shared.core import enums
from shared.core import impact


def test_new_log_stats_members_exist():
    for name in (
        "FirstPicks", "FirstDeaths", "UltimateKills", "SupportKills",
        "ImpactPoints", "ImpactRank", "OverperformanceScore",
    ):
        assert hasattr(enums.LogStatsName, name)


def test_weights_reference_real_stat_names():
    for key in impact.IMPACT_WEIGHTS:
        assert hasattr(enums.LogStatsName, key), key
    assert set(impact.EVENT_STATS) <= set(impact.IMPACT_WEIGHTS)


def test_directions():
    assert enums.is_ascending_stat(enums.LogStatsName.FirstDeaths) is True
    assert enums.is_ascending_stat(enums.LogStatsName.ImpactRank) is True
    assert enums.is_ascending_stat(enums.LogStatsName.ImpactPoints) is False
    assert enums.is_ascending_stat(enums.LogStatsName.FirstPicks) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest parser-service/tests/test_impact_constants.py -v`
Expected: FAIL (`No module named 'shared.core.impact'` / AttributeError)

- [ ] **Step 3: Implement**

В `backend/shared/core/enums.py` внутри `class LogStatsName`, после `HeroTimePlayed = "hero_time_played"` и перед блоком `# self calculated`:

```python
    # Derived from kill_feed (parser writes them like any other stat).
    FirstPicks = "first_picks"
    FirstDeaths = "first_deaths"
    UltimateKills = "ultimate_kills"
    SupportKills = "support_kills"
```

В конец блока `# self calculated` (после `Assists`):

```python
    ImpactPoints = "impact_points"  # self calculated (impact formula)
    ImpactRank = "impact_rank"  # self calculated (1 = MVP)
    OverperformanceScore = "overperformance_score"  # self calculated (role x rank baseline)
```

В `_log_stats_default_direction.update({...})` добавить две строки:

```python
        LogStatsName.FirstDeaths: "asc",
        LogStatsName.ImpactRank: "asc",
```

Создать `backend/shared/core/impact.py`:

```python
"""Shared constants of the MVP impact formula (spec 2026-07-10).

Weights apply to winsorized z-scores of per-10-minute rates. Keys are
``LogStatsName`` member NAMES (the same strings SQLAlchemy persists).
Bump ``FORMULA_VERSION`` whenever weights or baseline semantics change —
baselines are versioned by it and old scores stay on the old version
until an explicit backfill.
"""

from typing import Final

FORMULA_VERSION: Final = "impact_v1"

IMPACT_WEIGHTS: Final[dict[str, float]] = {
    "Eliminations": 1.3,
    "FinalBlows": 0.4,
    "Deaths": -1.3,
    "HeroDamageDealt": 0.35,
    "HealingDealt": 0.35,
    "DamageBlocked": 0.25,
    "OffensiveAssists": 0.45,
    "DefensiveAssists": 0.45,
    "UltimatesUsed": 0.1,
    "Multikills": 0.45,
    "SoloKills": 0.35,
    "ObjectiveKills": 0.3,
    "EnvironmentalKills": 0.2,
    "FirstPicks": 0.55,
    "FirstDeaths": -0.45,
    "UltimateKills": 0.5,
    "SupportKills": 0.3,
}

#: Stats derived from kill_feed — zeroed (not penalized) when a match has no feed.
EVENT_STATS: Final = ("FirstPicks", "FirstDeaths", "UltimateKills", "SupportKills")

WINSOR_LIMIT: Final = 3.0
#: Badge = top-1 OverperformanceScore in the match AND score >= threshold.
BADGE_THRESHOLD: Final = 2.0
#: Below this playtime a player's impact score is 0.
MIN_SECONDS: Final = 60.0
RANK_BUCKETS: Final = 3
#: Player-match rows entering baseline aggregation need >= this playtime.
BASELINE_MIN_MINUTES: Final = 3.0
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest parser-service/tests/test_impact_constants.py -v`
Expected: PASS. Затем smoke на регрессии enum: `uv run pytest app-service/tests/api/routes/test_user_compare_validation.py -v` — PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/shared/core/impact.py backend/shared/core/enums.py backend/parser-service/tests/test_impact_constants.py
git commit -m "feat(shared): impact formula constants + new LogStatsName members"
```

---

### Task 2: Модель StatBaseline + миграция

**Files:**
- Create: `backend/shared/models/matches/stat_baseline.py`
- Modify: `backend/shared/models/matches/__init__.py` (добавить экспорт; посмотреть существующий стиль re-export в этом файле)
- Create: `backend/migrations/versions/mvpimp0001_add_impact_scoring.py`

**Interfaces:**
- Produces: `shared.models.matches.StatBaseline` — колонки `formula_version: str`, `role: enums.HeroClass`, `rank_bucket: int` (−1 = без бакета, V4), `stat: enums.LogStatsName`, `mean: float`, `std: float`, `meta: dict | None` (границы бакетов + n), `computed_at: datetime`; таблица `matches.stat_baselines`, уникальный ключ (formula_version, role, rank_bucket, stat).

- [ ] **Step 1: Модель**

```python
# backend/shared/models/matches/stat_baseline.py
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db, enums

__all__ = ("StatBaseline",)


class StatBaseline(db.TimeStampIntegerMixin):
    """League baseline (mean/std of a per-10-minute stat rate) for impact scoring.

    ``rank_bucket = -1`` is the role-wide baseline (ImpactPoints); ``0..N-1``
    are rank terciles (OverperformanceScore). Bucket bounds are frozen in
    ``meta`` at compute time — scoring reads them from the rows, never
    recomputes. Versioned by ``formula_version``; recompute replaces the
    version's rows atomically.
    """

    __tablename__ = "stat_baselines"
    __table_args__ = (
        UniqueConstraint(
            "formula_version", "role", "rank_bucket", "stat",
            name="uq_stat_baselines_key",
        ),
        Index("ix_stat_baselines_version", "formula_version"),
        {"schema": "matches"},
    )

    formula_version: Mapped[str] = mapped_column(String(64))
    role: Mapped[enums.HeroClass] = mapped_column(Enum(enums.HeroClass))
    rank_bucket: Mapped[int] = mapped_column(SmallInteger(), server_default="-1")
    stat: Mapped[enums.LogStatsName] = mapped_column(Enum(enums.LogStatsName))
    mean: Mapped[float] = mapped_column(Float())
    std: Mapped[float] = mapped_column(Float())
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=db.func.now()
    )
```

В `backend/shared/models/matches/__init__.py` добавить импорт/экспорт `StatBaseline` по образцу соседних моделей. Проверить, что `parser-service/src/models.py` и `app-service/src/models.py` реэкспортируют `shared.models` целиком (grep `from shared.models`) — если экспорт пофайловый, добавить `StatBaseline` и туда.

- [ ] **Step 2: Миграция**

Сначала проверить head: `cd backend && uv run alembic heads` → ожидаем `wsbrand0002 (head)`; если head другой — подставить его в `down_revision`.

```python
# backend/migrations/versions/mvpimp0001_add_impact_scoring.py
"""add impact scoring: new logstatsname values + stat_baselines table

Revision ID: mvpimp0001
Revises: wsbrand0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "mvpimp0001"
down_revision = "wsbrand0002"
branch_labels = None
depends_on = None

_NEW_STAT_VALUES = (
    "FirstPicks",
    "FirstDeaths",
    "UltimateKills",
    "SupportKills",
    "ImpactPoints",
    "ImpactRank",
    "OverperformanceScore",
)


def upgrade() -> None:
    # PG12+: ADD VALUE is allowed inside a transaction as long as the new
    # value is not used in the same transaction (we don't use it here).
    for value in _NEW_STAT_VALUES:
        op.execute(f"ALTER TYPE logstatsname ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "stat_baselines",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("formula_version", sa.String(length=64), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="heroclass", create_type=False),
            nullable=False,
        ),
        sa.Column("rank_bucket", sa.SmallInteger(), server_default="-1", nullable=False),
        sa.Column(
            "stat",
            postgresql.ENUM(name="logstatsname", create_type=False),
            nullable=False,
        ),
        sa.Column("mean", sa.Float(), nullable=False),
        sa.Column("std", sa.Float(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("formula_version", "role", "rank_bucket", "stat", name="uq_stat_baselines_key"),
        schema="matches",
    )
    op.create_index("ix_stat_baselines_version", "stat_baselines", ["formula_version"], schema="matches")


def downgrade() -> None:
    op.drop_index("ix_stat_baselines_version", table_name="stat_baselines", schema="matches")
    op.drop_table("stat_baselines", schema="matches")
    # Enum values are intentionally NOT removed (PG can't drop enum values).
```

Перед написанием сверить колонки `TimeStampIntegerMixin` (id/created_at/updated_at имена и типы) с любой свежей миграцией (например, `wsbrand0001`) и привести Column-набор к тому же виду.

- [ ] **Step 3: Проверить рендер SQL (без применения!)**

Run: `cd backend && uv run alembic upgrade wsbrand0002:mvpimp0001 --sql | tail -40`
Expected: DDL с 7 × `ALTER TYPE ... ADD VALUE IF NOT EXISTS`, `CREATE TABLE matches.stat_baselines`, констрейнтом и индексом. Ошибок нет.

- [ ] **Step 4: Commit**

```bash
git add backend/shared/models/matches/stat_baseline.py backend/shared/models/matches/__init__.py backend/migrations/versions/mvpimp0001_add_impact_scoring.py
git commit -m "feat(db): stat_baselines table + new logstatsname values (mvpimp0001)"
```

---

### Task 3: Чистый модуль impact.py (события + скоринг)

**Files:**
- Create: `backend/parser-service/src/services/match_logs/impact.py`
- Test: `backend/parser-service/tests/test_impact_scoring.py`

**Interfaces:**
- Consumes: `shared.core.impact` (Task 1), `models.MatchKillFeed`, `models.MatchStatistics`.
- Produces:
  - `@dataclass(frozen=True) PlayerRef(player_id: int, user_id: int, team_id: int, role: enums.HeroClass | None, rank: int)`
  - `@dataclass(frozen=True) BaselineSet(formula_version: str, bucket_bounds: tuple[float, ...], values: Mapping[tuple[str, int, str], tuple[float, float]])` с методами `bucket_for(rank: int) -> int` и `z(role: str, bucket: int, stat: str, rate: float) -> float`
  - `build_event_counts(kill_feed: Sequence[models.MatchKillFeed], hero_types: Mapping[int, enums.HeroClass]) -> pd.DataFrame` — колонки `user_id, round, FirstPicks, FirstDeaths, UltimateKills, SupportKills` (int), только round > 0; totals строит вызывающий.
  - `dominant_roles(playtime: pd.DataFrame, hero_types: Mapping[int, enums.HeroClass]) -> dict[int, enums.HeroClass]` — вход: колонки `player_id, hero_id, seconds`.
  - `add_impact_scores(df: pd.DataFrame, *, players: Mapping[int, PlayerRef], baselines: BaselineSet, has_killfeed: bool) -> pd.DataFrame` — вход: pivot с колонками `player_id, round` + стат-колонки (члены `enums.LogStatsName`, включая `HeroTimePlayed` и событийные); добавляет колонки `enums.LogStatsName.ImpactPoints` и `enums.LogStatsName.OverperformanceScore`.

Ключевые правила реализации (из спеки): rate = value / seconds × 600; `seconds < MIN_SECONDS` → оба скора 0.0; z = clip((rate − mean)/std, ±WINSOR_LIMIT), std ≤ 0 или отсутствие базлайна → z = 0; `has_killfeed=False` → событийные z принудительно 0; `time_share = seconds / max(seconds внутри той же (round) группы df)`; роль None → скоры 0; итог = Σ w·z × time_share.

- [ ] **Step 1: Write the failing tests**

```python
# backend/parser-service/tests/test_impact_scoring.py
import pandas as pd
import pytest

from shared.core import enums
from shared.core.impact import BADGE_THRESHOLD, IMPACT_WEIGHTS
from src import models
from src.services.match_logs import impact

TANK = enums.HeroClass.tank
DAMAGE = enums.HeroClass.damage
SUPPORT = enums.HeroClass.support


def _kill(match_id=1, time=0.0, rnd=1, fight=1, killer=10, victim=20,
          killer_hero=1, victim_hero=2, ability=None, env=False):
    return models.MatchKillFeed(
        match_id=match_id, time=time, round=rnd, fight=fight,
        killer_id=killer, killer_hero_id=killer_hero, killer_team_id=1,
        victim_id=victim, victim_hero_id=victim_hero, victim_team_id=2,
        ability=ability, damage=100.0, is_critical_hit=False, is_environmental=env,
    )


HERO_TYPES = {1: DAMAGE, 2: SUPPORT, 3: TANK}


class TestBuildEventCounts:
    def test_first_kill_of_each_fight_is_first_pick_and_first_death(self):
        feed = [
            _kill(time=1.0, fight=1, killer=10, victim=20),
            _kill(time=3.0, fight=1, killer=20, victim=10),   # not first
            _kill(time=40.0, fight=2, killer=20, victim=10),
        ]
        df = impact.build_event_counts(feed, HERO_TYPES)
        row10 = df[df.user_id == 10].iloc[0]
        row20 = df[df.user_id == 20].iloc[0]
        assert row10.FirstPicks == 1 and row10.FirstDeaths == 1
        assert row20.FirstPicks == 1 and row20.FirstDeaths == 1

    def test_self_kill_gives_first_death_but_not_first_pick(self):
        feed = [_kill(time=1.0, fight=1, killer=10, victim=10)]
        df = impact.build_event_counts(feed, HERO_TYPES)
        row = df[df.user_id == 10].iloc[0]
        assert row.FirstPicks == 0 and row.FirstDeaths == 1

    def test_ultimate_and_support_kills(self):
        feed = [
            _kill(time=1.0, killer=10, victim=20, victim_hero=2,
                  ability=enums.AbilityEvent.Ultimate),
            _kill(time=2.0, killer=10, victim=20, victim_hero=3),  # tank victim
        ]
        df = impact.build_event_counts(feed, HERO_TYPES)
        row = df[df.user_id == 10].iloc[0]
        assert row.UltimateKills == 1
        assert row.SupportKills == 1  # only the hero-2 (support) victim

    def test_empty_feed_returns_empty_frame(self):
        df = impact.build_event_counts([], HERO_TYPES)
        assert df.empty


class TestBaselineSet:
    def _bs(self, mean=10.0, std=2.0):
        return impact.BaselineSet(
            formula_version="impact_v1",
            bucket_bounds=(500.0, 1000.0),
            values={("damage", -1, "Eliminations"): (mean, std)},
        )

    def test_z_and_winsorize(self):
        bs = self._bs()
        assert bs.z("damage", -1, "Eliminations", 12.0) == pytest.approx(1.0)
        assert bs.z("damage", -1, "Eliminations", 1000.0) == pytest.approx(3.0)  # clipped

    def test_missing_baseline_or_zero_std_is_zero(self):
        bs = self._bs(std=0.0)
        assert bs.z("damage", -1, "Eliminations", 12.0) == 0.0
        assert bs.z("tank", -1, "Eliminations", 12.0) == 0.0

    def test_bucket_for(self):
        bs = self._bs()
        assert bs.bucket_for(100) == 0
        assert bs.bucket_for(700) == 1
        assert bs.bucket_for(5000) == 2


class TestAddImpactScores:
    def _frame(self, elims=20.0, seconds=600.0, first_picks=3.0):
        cols = {
            "player_id": [1],
            "round": [0],
            enums.LogStatsName.Eliminations: [elims],
            enums.LogStatsName.HeroTimePlayed: [seconds],
            enums.LogStatsName.FirstPicks: [first_picks],
        }
        return pd.DataFrame(cols)

    def _players(self, role=DAMAGE, rank=800):
        return {1: impact.PlayerRef(player_id=1, user_id=10, team_id=1, role=role, rank=rank)}

    def _baselines(self):
        return impact.BaselineSet(
            formula_version="impact_v1",
            bucket_bounds=(500.0, 1000.0),
            values={
                ("damage", -1, "Eliminations"): (10.0, 5.0),
                ("damage", -1, "FirstPicks"): (1.0, 1.0),
                ("damage", 1, "Eliminations"): (12.0, 5.0),
                ("damage", 1, "FirstPicks"): (1.5, 1.0),
            },
        )

    def test_composite_uses_weights_and_events(self):
        out = impact.add_impact_scores(
            self._frame(), players=self._players(), baselines=self._baselines(), has_killfeed=True,
        )
        # elims rate 20/10min -> z=2; first_picks rate 3 -> z=2; time_share=1
        expected = IMPACT_WEIGHTS["Eliminations"] * 2.0 + IMPACT_WEIGHTS["FirstPicks"] * 2.0
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == pytest.approx(expected)

    def test_no_killfeed_zeroes_event_z_only(self):
        out = impact.add_impact_scores(
            self._frame(), players=self._players(), baselines=self._baselines(), has_killfeed=False,
        )
        expected = IMPACT_WEIGHTS["Eliminations"] * 2.0
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == pytest.approx(expected)

    def test_short_playtime_scores_zero(self):
        out = impact.add_impact_scores(
            self._frame(seconds=30.0), players=self._players(), baselines=self._baselines(), has_killfeed=True,
        )
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == 0.0
        assert out[enums.LogStatsName.OverperformanceScore].iloc[0] == 0.0

    def test_overperformance_uses_rank_bucket_baseline(self):
        out = impact.add_impact_scores(
            self._frame(), players=self._players(rank=700), baselines=self._baselines(), has_killfeed=True,
        )
        # bucket 1: elims z=(20-12)/5=1.6, fp z=(3-1.5)/1=1.5
        expected = IMPACT_WEIGHTS["Eliminations"] * 1.6 + IMPACT_WEIGHTS["FirstPicks"] * 1.5
        assert out[enums.LogStatsName.OverperformanceScore].iloc[0] == pytest.approx(expected)

    def test_unknown_role_scores_zero(self):
        out = impact.add_impact_scores(
            self._frame(), players=self._players(role=None), baselines=self._baselines(), has_killfeed=True,
        )
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == 0.0


class TestDominantRoles:
    def test_picks_role_with_most_playtime(self):
        df = pd.DataFrame({
            "player_id": [1, 1, 2],
            "hero_id": [1, 3, 2],
            "seconds": [100.0, 400.0, 300.0],
        })
        roles = impact.dominant_roles(df, HERO_TYPES)
        assert roles == {1: TANK, 2: SUPPORT}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest parser-service/tests/test_impact_scoring.py -v`
Expected: FAIL (`cannot import name 'impact'`)

- [ ] **Step 3: Implement `impact.py`**

```python
# backend/parser-service/src/services/match_logs/impact.py
"""Pure computation for MVP impact scoring (spec 2026-07-10).

Everything here is deterministic and DB-free: kill-feed event counting,
role attribution, and the z-composite scoring. IO (baselines fetch,
persistence) lives in the callers.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from shared.core.impact import (
    EVENT_STATS,
    IMPACT_WEIGHTS,
    MIN_SECONDS,
    WINSOR_LIMIT,
)
from src import models
from src.core import enums

__all__ = (
    "BaselineSet",
    "PlayerRef",
    "add_impact_scores",
    "build_event_counts",
    "dominant_roles",
)

_EVENT_COLS = list(EVENT_STATS)


@dataclass(frozen=True)
class PlayerRef:
    player_id: int  # tournament.player.id (pivot key)
    user_id: int  # players.user.id (stat rows / kill_feed key)
    team_id: int
    role: enums.HeroClass | None
    rank: int


@dataclass(frozen=True)
class BaselineSet:
    formula_version: str
    #: ascending inner bounds; rank <= bounds[i] -> bucket i, else last bucket
    bucket_bounds: tuple[float, ...]
    #: (role value, bucket | -1, stat NAME) -> (mean, std)
    values: Mapping[tuple[str, int, str], tuple[float, float]]

    def bucket_for(self, rank: int) -> int:
        for i, bound in enumerate(self.bucket_bounds):
            if rank <= bound:
                return i
        return len(self.bucket_bounds)

    def z(self, role: str, bucket: int, stat: str, rate: float) -> float:
        entry = self.values.get((role, bucket, stat))
        if entry is None:
            return 0.0
        mean, std = entry
        if std <= 0.0:
            return 0.0
        z = (rate - mean) / std
        return max(-WINSOR_LIMIT, min(WINSOR_LIMIT, z))


def build_event_counts(
    kill_feed: Sequence[models.MatchKillFeed],
    hero_types: Mapping[int, enums.HeroClass],
) -> pd.DataFrame:
    """Per (user_id, round) event counts derived from the kill feed.

    First kill of each fight (by time) yields a FirstPick for the killer
    (unless a self-kill) and a FirstDeath for the victim. Self-kills never
    count as kills for Ultimate/Support tallies.
    """
    if not kill_feed:
        return pd.DataFrame(columns=["user_id", "round", *_EVENT_COLS])

    rows = pd.DataFrame(
        {
            "time": [k.time for k in kill_feed],
            "round": [k.round for k in kill_feed],
            "fight": [k.fight for k in kill_feed],
            "killer_id": [k.killer_id for k in kill_feed],
            "victim_id": [k.victim_id for k in kill_feed],
            "victim_hero_id": [k.victim_hero_id for k in kill_feed],
            "is_ult": [k.ability == enums.AbilityEvent.Ultimate for k in kill_feed],
        }
    ).sort_values("time")

    rows["is_self"] = rows["killer_id"] == rows["victim_id"]
    rows["victim_is_support"] = rows["victim_hero_id"].map(
        lambda h: hero_types.get(h) == enums.HeroClass.support
    )
    first = rows.groupby("fight", as_index=False).first()

    counters: dict[tuple[int, int], dict[str, int]] = {}

    def bump(user_id: int, rnd: int, stat: str) -> None:
        key = (int(user_id), int(rnd))
        counters.setdefault(key, dict.fromkeys(_EVENT_COLS, 0))[stat] += 1

    for r in first.itertuples(index=False):
        if not r.is_self:
            bump(r.killer_id, r.round, "FirstPicks")
        bump(r.victim_id, r.round, "FirstDeaths")
    for r in rows[~rows["is_self"]].itertuples(index=False):
        if r.is_ult:
            bump(r.killer_id, r.round, "UltimateKills")
        if r.victim_is_support:
            bump(r.killer_id, r.round, "SupportKills")

    out = pd.DataFrame(
        [{"user_id": uid, "round": rnd, **stats} for (uid, rnd), stats in counters.items()]
    )
    return out.sort_values(["user_id", "round"]).reset_index(drop=True)


def dominant_roles(
    playtime: pd.DataFrame,
    hero_types: Mapping[int, enums.HeroClass],
) -> dict[int, enums.HeroClass]:
    """player_id -> role with the most summed hero seconds."""
    if playtime.empty:
        return {}
    df = playtime.copy()
    df["role"] = df["hero_id"].map(hero_types)
    df = df.dropna(subset=["role"])
    grouped = df.groupby(["player_id", "role"], observed=True)["seconds"].sum().reset_index()
    grouped = grouped.sort_values("seconds", ascending=False)
    best = grouped.drop_duplicates("player_id")
    return dict(zip(best["player_id"].astype(int), best["role"], strict=True))


def add_impact_scores(
    df: pd.DataFrame,
    *,
    players: Mapping[int, PlayerRef],
    baselines: BaselineSet,
    has_killfeed: bool,
) -> pd.DataFrame:
    """Add ImpactPoints / OverperformanceScore columns to a stat pivot.

    ``df`` rows are one player within one scoring group (a round or the
    whole match); stat columns are ``LogStatsName`` members. time_share is
    computed inside each ``round`` group.
    """
    df = df.copy()
    seconds = df.get(enums.LogStatsName.HeroTimePlayed)
    if seconds is None:
        seconds = pd.Series(0.0, index=df.index)
    seconds = seconds.fillna(0.0)
    max_seconds = seconds.groupby(df["round"]).transform("max").replace(0, 1.0)
    time_share = seconds / max_seconds

    impact_scores: list[float] = []
    overperf_scores: list[float] = []
    for idx, row in df.iterrows():
        ref = players.get(int(row["player_id"]))
        secs = float(seconds.loc[idx])
        if ref is None or ref.role is None or secs < MIN_SECONDS:
            impact_scores.append(0.0)
            overperf_scores.append(0.0)
            continue
        role = ref.role.value.lower() if hasattr(ref.role, "value") else str(ref.role).lower()
        bucket = baselines.bucket_for(ref.rank)
        base_score = 0.0
        rank_score = 0.0
        for stat_name, weight in IMPACT_WEIGHTS.items():
            member = enums.LogStatsName[stat_name]
            value = float(row.get(member, 0.0) or 0.0)
            if stat_name in EVENT_STATS and not has_killfeed:
                continue
            rate = value / secs * 600.0
            base_score += weight * baselines.z(role, -1, stat_name, rate)
            rank_score += weight * baselines.z(role, bucket, stat_name, rate)
        share = float(time_share.loc[idx])
        impact_scores.append(base_score * share)
        overperf_scores.append(rank_score * share)

    df[enums.LogStatsName.ImpactPoints] = impact_scores
    df[enums.LogStatsName.OverperformanceScore] = overperf_scores
    return df
```

Внимание на согласование: ключ `values` использует роль в НИЖНЕМ регистре значения `HeroClass` (`"tank"|"damage"|"support"` — от `HeroClass.tank.value.lower()`, т.к. value = "Tank"). Baseline-запись (Task 4) обязана писать роль в том же виде — зафиксировать хелпером `role_key(role) -> str` в этом же модуле, если при имплементации станет неудобно.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest parser-service/tests/test_impact_scoring.py -v`
Expected: PASS (все ~13 тестов)

- [ ] **Step 5: Lint + commit**

```bash
cd backend && uv run ruff check parser-service/src/services/match_logs/impact.py parser-service/tests/test_impact_scoring.py --fix && uv run ruff format parser-service/src/services/match_logs/impact.py parser-service/tests/test_impact_scoring.py
git add backend/parser-service/src/services/match_logs/impact.py backend/parser-service/tests/test_impact_scoring.py
git commit -m "feat(parser): pure impact scoring module (events, roles, z-composite)"
```

---

### Task 4: Сервис базлайнов (пересчёт + кэшированное чтение)

**Files:**
- Create: `backend/parser-service/src/services/baselines/__init__.py` (пустой)
- Create: `backend/parser-service/src/services/baselines/service.py`
- Create: `backend/parser-service/src/services/baselines/flows.py`
- Test: `backend/parser-service/tests/test_impact_baselines.py`

**Interfaces:**
- Consumes: `impact.BaselineSet` (Task 3), `models.StatBaseline` (Task 2), константы Task 1.
- Produces:
  - `service.get_active(session) -> BaselineSet | None` — читает строки `FORMULA_VERSION`, кэш cashews (ttl 10m, key `"parser:impact_baselines:{FORMULA_VERSION}"`), `service.invalidate_cache()`.
  - `flows.recompute(session) -> int` — пересчитывает и атомарно заменяет строки версии, возвращает число строк; вызывает `service.invalidate_cache()`.
  - `flows.build_baseline_rows(stats: pd.DataFrame) -> list[dict]` — ЧИСТАЯ функция: вход-DataFrame c колонками `role` (str, lower), `rank` (int), `minutes` (float), `has_killfeed` (bool) + rate-колонки `<StatName>_rate` для каждого ключа `IMPACT_WEIGHTS`; выход — dict'и строк StatBaseline (role, rank_bucket, stat, mean, std, meta).

Правила `build_baseline_rows`: фильтр `minutes >= BASELINE_MIN_MINUTES`; событийные статы агрегируются только по строкам `has_killfeed`; бакеты — терцили `rank` (numpy `quantile([1/3, 2/3])`), границы кладутся в `meta` каждой строки как `{"bucket_bounds": [b1, b2], "n": <rows>}`; std через `ddof=1`, NaN → 0.0; на каждый (role, stat) пишутся строки bucket=-1 и bucket=0..2.

- [ ] **Step 1: Write the failing test**

```python
# backend/parser-service/tests/test_impact_baselines.py
import numpy as np
import pandas as pd

from shared.core.impact import IMPACT_WEIGHTS
from src.services.baselines import flows


def _stats_frame(n=90):
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "role": ["damage"] * n,
        "rank": np.concatenate([
            rng.integers(100, 400, n // 3),
            rng.integers(600, 900, n // 3),
            rng.integers(1200, 2000, n - 2 * (n // 3)),
        ]),
        "minutes": 15.0,
        "has_killfeed": [True] * (n // 2) + [False] * (n - n // 2),
    })
    for stat in IMPACT_WEIGHTS:
        df[f"{stat}_rate"] = rng.normal(10.0, 3.0, n)
    return df


def test_rows_cover_all_buckets_and_role_wide():
    rows = flows.build_baseline_rows(_stats_frame())
    buckets = {(r["role"], r["rank_bucket"]) for r in rows}
    assert ("damage", -1) in buckets
    assert {("damage", 0), ("damage", 1), ("damage", 2)} <= buckets


def test_event_stats_use_only_killfeed_rows():
    df = _stats_frame()
    df.loc[df.has_killfeed, "FirstPicks_rate"] = 5.0
    df.loc[~df.has_killfeed, "FirstPicks_rate"] = 100.0  # must be ignored
    rows = flows.build_baseline_rows(df)
    fp = next(r for r in rows if r["stat"] == "FirstPicks" and r["rank_bucket"] == -1)
    assert fp["mean"] == 5.0


def test_short_playtime_rows_excluded():
    df = _stats_frame()
    df["Eliminations_rate"] = 10.0
    extra = df.iloc[[0]].copy()
    extra["minutes"] = 1.0
    extra["Eliminations_rate"] = 10_000.0
    rows = flows.build_baseline_rows(pd.concat([df, extra], ignore_index=True))
    el = next(r for r in rows if r["stat"] == "Eliminations" and r["rank_bucket"] == -1)
    assert el["mean"] == 10.0


def test_bucket_bounds_frozen_in_meta():
    rows = flows.build_baseline_rows(_stats_frame())
    bounds = rows[0]["meta"]["bucket_bounds"]
    assert len(bounds) == 2 and bounds[0] < bounds[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest parser-service/tests/test_impact_baselines.py -v`
Expected: FAIL (нет модуля)

- [ ] **Step 3: Implement**

`flows.py` — `build_baseline_rows` (чистая, по правилам выше) + `recompute(session)`:

```python
async def recompute(session: AsyncSession) -> int:
    stats = await _load_stats_frame(session)
    rows = build_baseline_rows(stats)
    await session.execute(
        sa.delete(models.StatBaseline).where(models.StatBaseline.formula_version == FORMULA_VERSION)
    )
    session.add_all(
        models.StatBaseline(
            formula_version=FORMULA_VERSION,
            role=enums.HeroClass(row["role"].capitalize()),
            rank_bucket=row["rank_bucket"],
            stat=enums.LogStatsName[row["stat"]],
            mean=row["mean"],
            std=row["std"],
            meta=row["meta"],
        )
        for row in rows
    )
    await session.commit()
    await service.invalidate_cache()
    return len(rows)
```

`_load_stats_frame(session)` — один SQL по образцу read-путей parser'а: per (match_id, user_id) round=0 hero-NULL значения нужных статов (pivot через `max(value) FILTER (WHERE name = '<StatName>')` — имена-ЧЛЕНЫ enum), + HeroTimePlayed → minutes, + доминирующая роль (join hero playtime hero-строк с `overwatch.hero.type`), + rank из `tournament.player` (join через `workspace_member`), + `has_killfeed = EXISTS(kill_feed)`. Реализовать через `sa.text(...)` c готовым SQL — образец запроса лежит в этом плане ниже (Task 6, бэкфилл использует те же join'ы). Роль в frame — в нижнем регистре (`lower(hero.type::text)`), rate-колонки считать в pandas: `value / minutes * 10`... ВНИМАНИЕ: в `impact.py` rate = value/seconds×600 (за 10 минут). Здесь то же самое: `<stat>_rate = value / (seconds/600)`. Единица должна совпадать — сверить с тестом Task 3.

`service.py`:

```python
from cashews import cache

from shared.core.impact import FORMULA_VERSION

_CACHE_KEY = f"parser:impact_baselines:{FORMULA_VERSION}"


async def get_active(session: AsyncSession) -> impact.BaselineSet | None:
    cached = await cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    rows = (await session.execute(
        sa.select(models.StatBaseline).where(models.StatBaseline.formula_version == FORMULA_VERSION)
    )).scalars().all()
    if not rows:
        return None
    bounds = tuple(rows[0].meta["bucket_bounds"]) if rows[0].meta else ()
    values = {
        (row.role.value.lower(), row.rank_bucket, row.stat.name): (row.mean, row.std)
        for row in rows
    }
    baseline_set = impact.BaselineSet(FORMULA_VERSION, bounds, values)
    await cache.set(_CACHE_KEY, baseline_set, expire="10m")
    return baseline_set


async def invalidate_cache() -> None:
    await cache.delete(_CACHE_KEY)
```

(cashews сериализует dataclass через pickle — если упадёт, кэшировать сырые кортежи и собирать BaselineSet после чтения. Ключ — полный литерал, БЕЗ шаблонов cashews: известный gotcha с prefix-less delete.)

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest parser-service/tests/test_impact_baselines.py parser-service/tests/test_impact_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/parser-service/src/services/baselines backend/parser-service/tests/test_impact_baselines.py
git commit -m "feat(parser): impact baselines service (recompute + cached fetch)"
```

---

### Task 5: Врезка в пайплайн обработки лога

**Files:**
- Modify: `backend/parser-service/src/services/match_logs/flows.py` — `create_stats()` (~строка 694), `_calculate_and_add_derived_stats()` (~613), `start()` (~865-873)
- Test: `backend/parser-service/tests/test_impact_pipeline_wiring.py`

**Interfaces:**
- Consumes: всё из Task 3-4.
- Produces: `create_stats(self, session, match, players_map, kill_feed: list[models.MatchKillFeed] | None = None)` — новые стат-строки FirstPicks/FirstDeaths/UltimateKills/SupportKills (per-round + round-0 totals, hero NULL) и ImpactPoints/ImpactRank/OverperformanceScore (в тех же группах, что Performance).

Изменения:

1. `start()`: передать килл-фид — `stats = await self.create_stats(session, match_model, players_map, kill_feed=kill_feed_db_objects)`.
2. В `create_stats` после построения `round_derived_df` / `match_derived_df`:

```python
        user_to_player = {p.workspace_member.player_id: p for p in players_map.values()}
        hero_types = {h.id: h.type for h in self.heroes_map.values()}

        events_df = impact.build_event_counts(kill_feed or [], hero_types)
        has_killfeed = bool(kill_feed)
        if not events_df.empty:
            events_df["player_id"] = events_df["user_id"].map(
                lambda uid: user_to_player[uid].id if uid in user_to_player else None
            )
            events_df = events_df.dropna(subset=["player_id"])
            events_df["player_id"] = events_df["player_id"].astype(int)

            # Per-round event stat rows + merge into the round pivot.
            for stat_name in impact_consts.EVENT_STATS:
                member = enums.LogStatsName[stat_name]
                for r in events_df.itertuples(index=False):
                    all_stat_objects.append(
                        self._create_stat_object(
                            match, member, user_to_player[r.user_id], int(r.round), None,
                            float(getattr(r, stat_name)),
                        )
                    )
            totals = events_df.groupby(["player_id", "user_id"], as_index=False)[
                list(impact_consts.EVENT_STATS)
            ].sum()
            for stat_name in impact_consts.EVENT_STATS:
                member = enums.LogStatsName[stat_name]
                for r in totals.itertuples(index=False):
                    all_stat_objects.append(
                        self._create_stat_object(
                            match, member, user_to_player[r.user_id], 0, None,
                            float(getattr(r, stat_name)),
                        )
                    )

            event_cols = ["player_id", "round", *impact_consts.EVENT_STATS]
            round_derived_df = round_derived_df.merge(
                events_df[event_cols].rename(
                    columns={s: enums.LogStatsName[s] for s in impact_consts.EVENT_STATS}
                ),
                on=["player_id", "round"], how="left",
            )
            match_events = totals.assign(round=0)
            match_derived_df = match_derived_df.merge(
                match_events[event_cols].rename(
                    columns={s: enums.LogStatsName[s] for s in impact_consts.EVENT_STATS}
                ),
                on=["player_id", "round"], how="left",
            )
        for df_ in (round_derived_df, match_derived_df):
            for s in impact_consts.EVENT_STATS:
                member = enums.LogStatsName[s]
                if member not in df_.columns:
                    df_[member] = 0.0
                df_[member] = df_[member].fillna(0.0)
```

3. Роли и PlayerRef (там же, до вызовов `_calculate_and_add_derived_stats`):

```python
        playtime_df = final_cumulative_df[
            final_cumulative_df["stat_name"] == enums.LogStatsName.HeroTimePlayed
        ][["player_id", "hero_id", "value"]].rename(columns={"value": "seconds"})
        roles = impact.dominant_roles(playtime_df, hero_types)

        player_refs = {
            p.id: impact.PlayerRef(
                player_id=p.id,
                user_id=p.workspace_member.player_id,
                team_id=p.team_id,
                role=roles.get(p.id) or p.role,
                rank=p.rank,
            )
            for p in players_map.values()
        }
        baselines = await baselines_service.get_active(session)
```

4. `_calculate_and_add_derived_stats(..., impact_ctx: ImpactContext | None = None)` — маленький dataclass `ImpactContext(players, baselines, has_killfeed)` в `impact.py`. Внутри блока `if is_mvp_calc:` после Performance-ранжирования:

```python
            if impact_ctx is not None and impact_ctx.baselines is not None:
                df = impact.add_impact_scores(
                    df,
                    players=impact_ctx.players,
                    baselines=impact_ctx.baselines,
                    has_killfeed=impact_ctx.has_killfeed,
                )
                for stat_member in (
                    enums.LogStatsName.ImpactPoints,
                    enums.LogStatsName.OverperformanceScore,
                ):
                    records = df[["player_model", "round", "hero_id", stat_member]].to_dict(orient="records")
                    temp_derived_stats.extend(
                        self._create_stat_object(
                            match, stat_member, r["player_model"], r["round"], r.get("hero_id"), r[stat_member]
                        )
                        for r in records
                    )
                df_rank = df.sort_values(
                    by=["round", enums.LogStatsName.ImpactPoints], ascending=[True, False]
                )
                df_rank["_impact_rank"] = df_rank.groupby("round").cumcount() + 1
                records = df_rank[["player_model", "round", "hero_id", "_impact_rank"]].to_dict(orient="records")
                temp_derived_stats.extend(
                    self._create_stat_object(
                        match, enums.LogStatsName.ImpactRank, r["player_model"], r["round"], r.get("hero_id"),
                        r["_impact_rank"],
                    )
                    for r in records
                )
            elif impact_ctx is not None:
                logger.warning("Impact baselines missing for %s — skipping impact stats", enums.LogStatsName.ImpactPoints)
```

`impact_ctx` передаётся ТОЛЬКО в два вызова с `is_mvp_calc=True` (строки ~785, ~787): `round_derived_df` и `match_derived_df`. Импорты в flows.py: `from shared.core import impact as impact_consts`, `from src.services.baselines import service as baselines_service`, `from src.services.match_logs import impact`.

- [ ] **Step 1: Write the failing test** — сквозной unit на новую логику через фейковые объекты (без БД): собрать mini-`MatchLogProcessor` НЕ нужно; тестируем через `_calculate_and_add_derived_stats`-уровень сложно (метод класса). Вместо этого тест на хелпер-уровне: в `test_impact_pipeline_wiring.py` проверить, что `create_stats` определяет параметр `kill_feed` и что `start()` его передаёт — минимум: сигнатурный тест + тест ImpactContext:

```python
# backend/parser-service/tests/test_impact_pipeline_wiring.py
import inspect

from src.services.match_logs.flows import MatchLogProcessor
from src.services.match_logs import impact


def test_create_stats_accepts_kill_feed():
    sig = inspect.signature(MatchLogProcessor.create_stats)
    assert "kill_feed" in sig.parameters


def test_impact_context_shape():
    ctx = impact.ImpactContext(players={}, baselines=None, has_killfeed=False)
    assert ctx.baselines is None
```

- [ ] **Step 2: Run to verify fail** — `cd backend && uv run pytest parser-service/tests/test_impact_pipeline_wiring.py -v` → FAIL.
- [ ] **Step 3: Implement** (правки flows.py по коду выше + `ImpactContext` dataclass в impact.py).
- [ ] **Step 4: Run FULL parser test suite** — `cd backend && uv run pytest parser-service/tests -x -q`
Expected: PASS (в т.ч. существующие тесты пайплайна логов; если какой-то тест зовёт `create_stats` позиционно — обновить вызов, kill_feed keyword-only).
- [ ] **Step 5: Commit**

```bash
git add backend/parser-service/src/services/match_logs/flows.py backend/parser-service/src/services/match_logs/impact.py backend/parser-service/tests/test_impact_pipeline_wiring.py
git commit -m "feat(parser): wire event stats + impact scoring into log pipeline"
```

---

### Task 6: Бэкфилл истории (idempotent CLI)

**Files:**
- Create: `backend/parser-service/src/services/match_logs/backfill.py`
- Create: `backend/parser-service/backfill_impact.py` (CLI-entrypoint рядом с serve.py)
- Test: `backend/parser-service/tests/test_impact_backfill.py`

**Interfaces:**
- Consumes: impact.py, baselines service.
- Produces:
  - `backfill.rebuild_frames(stat_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]` — ЧИСТАЯ: из строк `matches.statistics` матча (колонки `user_id, round, hero_id, name, value`) восстанавливает round-pivot (hero NULL, round>0) и match-pivot (round 0) с колонками-членами LogStatsName + `player_id == user_id` (в бэкфилле ключом служит user_id, roster-id не нужен).
  - `backfill.backfill_match(session, match_id) -> bool` — пересчёт одного матча: читает статы + kill_feed + ростеры обеих команд (role/rank через `tournament.player` join `workspace_member`), удаляет строки с `name IN (7 новых статов)` по match_id, вставляет новые; False если у матча нет статов.
  - `backfill.backfill_all(session_factory, tournament_id: int | None = None) -> dict` — цикл по матчам (фильтр по турниру опционален), коммит на каждый матч, лог прогресса каждые 100.
- CLI: `cd backend/parser-service && uv run python backfill_impact.py [--tournament-id N]` — конфигурирует кэш (`configure_cache()` — обязательный gotcha), зовёт `backfill_all`, печатает сводку.

Каркас `backfill_match`:

```python
NEW_STAT_MEMBERS = tuple(
    enums.LogStatsName[name]
    for name in (*impact_consts.EVENT_STATS, "ImpactPoints", "ImpactRank", "OverperformanceScore")
)

async def backfill_match(session: AsyncSession, match_id: int) -> bool:
    stat_rows = await _load_stat_rows(session, match_id)   # только СТАРЫЕ имена статов
    if stat_rows.empty:
        return False
    kill_feed = (await session.execute(
        sa.select(models.MatchKillFeed).where(models.MatchKillFeed.match_id == match_id)
    )).scalars().all()
    refs = await _load_player_refs(session, match_id)      # user_id -> PlayerRef (role: dominant|declared, rank)
    hero_types = await _load_hero_types(session)           # кэшируемо на процесс
    baselines = await baselines_service.get_active(session)
    if baselines is None:
        raise RuntimeError("Impact baselines are not computed — run recompute first")

    round_df, match_df = rebuild_frames(stat_rows)
    events_df = impact.build_event_counts(kill_feed, hero_types)
    # merge событий + fillna(0) — тем же кодом, что Task 5 (в бэкфилле player_id == user_id)
    ...
    objects = _stat_objects(match_id, refs, round_df, match_df, events_df, baselines, bool(kill_feed))
    await session.execute(
        sa.delete(models.MatchStatistics).where(
            models.MatchStatistics.match_id == match_id,
            models.MatchStatistics.name.in_(NEW_STAT_MEMBERS),
        )
    )
    session.add_all(objects)
    return True
```

`_stat_objects` строит `models.MatchStatistics(match_id=..., round=..., team_id=ref.team_id, user_id=ref.user_id, hero_id=None, name=..., value=...)` напрямую (без `_create_stat_object` — он привязан к ORM-Player). Ранжирование ImpactRank — тем же sort/cumcount, что в Task 5.

- [ ] **Step 1: Write the failing test** — на `rebuild_frames` и idempotency-контракт:

```python
# backend/parser-service/tests/test_impact_backfill.py
import pandas as pd

from shared.core import enums
from src.services.match_logs import backfill


def _stat_rows():
    return pd.DataFrame([
        # round rows (hero NULL)
        {"user_id": 10, "round": 1, "hero_id": None, "name": enums.LogStatsName.Eliminations, "value": 5.0},
        {"user_id": 10, "round": 1, "hero_id": None, "name": enums.LogStatsName.HeroTimePlayed, "value": 300.0},
        # match totals
        {"user_id": 10, "round": 0, "hero_id": None, "name": enums.LogStatsName.Eliminations, "value": 5.0},
        {"user_id": 10, "round": 0, "hero_id": None, "name": enums.LogStatsName.HeroTimePlayed, "value": 300.0},
        # per-hero row must be ignored by pivots
        {"user_id": 10, "round": 0, "hero_id": 3, "name": enums.LogStatsName.Eliminations, "value": 5.0},
    ])


def test_rebuild_frames_pivots_round_and_match():
    round_df, match_df = backfill.rebuild_frames(_stat_rows())
    assert list(round_df["round"].unique()) == [1]
    assert round_df[enums.LogStatsName.Eliminations].iloc[0] == 5.0
    assert match_df["round"].iloc[0] == 0
    assert match_df[enums.LogStatsName.HeroTimePlayed].iloc[0] == 300.0


def test_rebuild_frames_drops_already_derived_new_stats():
    rows = _stat_rows()
    rows = pd.concat([rows, pd.DataFrame([
        {"user_id": 10, "round": 0, "hero_id": None, "name": enums.LogStatsName.ImpactPoints, "value": 9.9},
    ])], ignore_index=True)
    _, match_df = backfill.rebuild_frames(rows)
    assert enums.LogStatsName.ImpactPoints not in match_df.columns
```

- [ ] **Step 2: Run to verify fail** → FAIL (нет модуля).
- [ ] **Step 3: Implement** `backfill.py` + CLI `backfill_impact.py` (argparse `--tournament-id`, `asyncio.run`, `async_session_maker` из `src.core.db`, `configure_cache()` перед работой — смотри как это делает `serve.py`).
- [ ] **Step 4: Run tests** — `cd backend && uv run pytest parser-service/tests/test_impact_backfill.py -v` → PASS; полный парсер-сьют `uv run pytest parser-service/tests -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/parser-service/src/services/match_logs/backfill.py backend/parser-service/backfill_impact.py backend/parser-service/tests/test_impact_backfill.py
git commit -m "feat(parser): idempotent impact backfill (module + CLI)"
```

---

### Task 7: RPC пересчёта базлайнов

**Files:**
- Create: `backend/parser-service/src/rpc/impact.py`
- Modify: `backend/parser-service/serve.py` (импорт + `rpc_impact.register(broker, logger)` рядом со строками 92-96)

**Interfaces:**
- Produces: subscriber `rpc.parser.impact.recompute_baselines` — superuser-only, зовёт `baselines_flows.recompute`, возвращает `{"rows": N, "formula_version": ...}`.

- [ ] **Step 1: Implement** (по образцу `src/rpc/logs.py`: `c.actor(data)`, `c.require_active(user)`, гейт — `if not user.is_superuser: raise HTTPException(403)`; ВАЖНО: 2-й параметр subscriber'а — `msg: RabbitMessage`, иначе auto-reply молча отваливается):

```python
# backend/parser-service/src/rpc/impact.py
"""Typed-RPC: manual recompute of impact-scoring baselines (superuser)."""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.core.impact import FORMULA_VERSION
from src.core import db
from src.services.baselines import flows as baselines_flows

from . import _common as c

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.impact.recompute_baselines")
    async def _recompute(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.is_superuser:
                raise HTTPException(status_code=403, detail="Superuser required")
            rows = await baselines_flows.recompute(session)
            return {"rows": rows, "formula_version": FORMULA_VERSION}

        return await c.envelope(logger, "impact.recompute_baselines", op, session_factory=_SF)
```

Перед коммитом свериться с `_common.py` (`envelope`, `actor`) — если у actor нет `is_superuser`, использовать тот же атрибут, что в других superuser-гейтах parser'а (grep `is_superuser` по `parser-service/src`).

- [ ] **Step 2: Verify** — `cd backend && uv run python -c "import ast,sys; ast.parse(open('parser-service/src/rpc/impact.py').read())"` + `uv run pytest parser-service/tests -q` (регрессия) → PASS.
- [ ] **Step 3: Commit**

```bash
git add backend/parser-service/src/rpc/impact.py backend/parser-service/serve.py
git commit -m "feat(parser): rpc.parser.impact.recompute_baselines (superuser)"
```

---

### Task 8: app-service — impact-поля в user-эндпоинтах

**Files:**
- Modify: `backend/app-service/src/schemas/user.py` (класс `MatchReadWithUserStats`, ~строка 165)
- Modify: `backend/app-service/src/services/user/_repositories.py` (CTE-блоки ~строки 65-110, 250-340 — все места, где строится `performance_cte`)
- Modify: `backend/app-service/src/services/user/service.py` / `flows.py` — мапперы, где `row.performance` кладётся в схему (grep `performance=`)
- Test: `backend/app-service/tests/api/routes/test_user_impact.py`

**Interfaces:**
- Produces (schema): `MatchReadWithUserStats.impact_rank: int | None`, `.impact_points: float | None`, `.overperformance_score: float | None`, `.overperformance_badge: bool = False`.

CTE-паттерн (добавить рядом с `performance_cte`, по одному разу на каждый read-path):

```python
    impact_rank_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.value.label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.ImpactRank,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("impact_rank_cte")
    )

    overperf_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.value.label("value"),
            sa.func.rank()
            .over(
                partition_by=models.MatchStatistics.match_id,
                order_by=models.MatchStatistics.value.desc(),
            )
            .label("pos"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.name == enums.LogStatsName.OverperformanceScore,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("overperf_cte")
    )
```

В основном select добавить `impact_rank_cte.c.value.label("impact_rank")`, `overperf_cte.c.value.label("overperformance_score")`, `overperf_cte.c.pos.label("overperf_pos")` (join overperf по `match_id` + `user_id == user_id`), маппер:

```python
from shared.core.impact import BADGE_THRESHOLD

impact_rank=int(row.impact_rank) if row.impact_rank is not None else None,
overperformance_score=row.overperformance_score,
overperformance_badge=(
    row.overperf_pos == 1
    and row.overperformance_score is not None
    and row.overperformance_score >= BADGE_THRESHOLD
),
```

`impact_points` — аналогичный одностатный CTE по `LogStatsName.ImpactPoints` (нужен для тултипов; если по месту окажется, что фронту хватает rank+score — оставить всё равно, спека фиксирует поле).

- [ ] **Step 1: Write the failing test** — по образцу `app-service/tests/api/routes/test_user.py` (те же фикстуры сессии/данных; скопировать setup-паттерн создания `models.MatchStatistics` из этого файла):

```python
# backend/app-service/tests/api/routes/test_user_impact.py
# Фикстуры/хелперы создания турнира-команды-матча берём 1:1 из test_user.py
# (skip-маркеры без БД — как у соседей). Сценарий:
#  - user A: ImpactRank=1, OverperformanceScore=2.5 (top-1 в матче) -> badge True
#  - user B: ImpactRank=2, OverperformanceScore=1.0 -> badge False
#  - user C: score 3.0, но pos=2 в другом матче... (одно утверждение на правило)
# Утверждения по ответу эндпоинта encounters пользователя:
#   match["impact_rank"] == 1
#   match["overperformance_badge"] is True  (pos=1 и score >= 2.0)
#   у B: badge False (pos != 1); у матча без impact-строк: impact_rank is None
```

Написать тест полностью, скопировав структуру `test_user.py::test_...performance` (файл уже содержит рабочий паттерн с `enums.LogStatsName.Performance` — повторить с новыми именами).

- [ ] **Step 2: Run to verify fail** — `cd backend && uv run pytest app-service/tests/api/routes/test_user_impact.py -v` → FAIL (нет полей).
- [ ] **Step 3: Implement** (schema + все performance-read-paths: строки ~65, ~265, ~310 `_repositories.py` — grep `LogStatsName.Performance` по файлу и продублировать CTE в каждом).
- [ ] **Step 4: Run tests** — новый файл + regression: `uv run pytest app-service/tests/api/routes/test_user_impact.py app-service/tests/api/routes/test_user.py -v` → PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app-service/src/schemas/user.py backend/app-service/src/services/user/_repositories.py backend/app-service/src/services/user/service.py backend/app-service/src/services/user/flows.py backend/app-service/tests/api/routes/test_user_impact.py
git commit -m "feat(app): impact_rank/points + overperformance badge in user match reads"
```

---

### Task 9: Frontend — пилюли на impact_rank, бейдж, «Очки (классика)»

**Files:**
- Modify: `frontend/src/types/user.types.ts` (тип `MatchWithUserStats`)
- Modify: `frontend/src/components/match/cells.tsx` (хелпер выбора ранга)
- Modify: `frontend/src/components/match/MvpMatchPill.tsx`
- Modify: `frontend/src/app/(site)/users/components/matches/MatchRow.tsx` (фильтр `mvpMatches`, строка ~56)
- Modify: `frontend/src/app/(site)/users/components/tournaments/EncounterRow.tsx` (аналогичный фильтр — найти по `performance != null`)
- Modify: `frontend/src/app/(site)/matches/[id]/components/MatchTeamTable.tsx` (колонки статов)
- Modify: `frontend/src/types/stats.types.ts` (если там enum имён статов — добавить новые)
- Modify: `frontend/src/i18n/messages/ru.json`, `frontend/src/i18n/messages/en.json`
- Test: `frontend/src/components/match/__tests__/mvp-rank.test.ts`

**Interfaces:**
- Produces: `MatchWithUserStats` дополняется `impact_rank?: number | null; impact_points?: number | null; overperformance_score?: number | null; overperformance_badge?: boolean;` (snake_case — как приходит из API). Хелпер в `cells.tsx`:

```tsx
/** Official MVP placement: impact rank when computed, legacy performance otherwise. */
export const resolveMvpPlacement = (m: { impact_rank?: number | null; performance?: number | null }): number | null =>
  m.impact_rank ?? m.performance ?? null;
```

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/match/__tests__/mvp-rank.test.ts
import { describe, expect, it } from "bun:test";
import { resolveMvpPlacement, mvpRank } from "@/components/match/cells";

describe("resolveMvpPlacement", () => {
  it("prefers impact_rank over legacy performance", () => {
    expect(resolveMvpPlacement({ impact_rank: 2, performance: 1 })).toBe(2);
  });
  it("falls back to performance for legacy matches", () => {
    expect(resolveMvpPlacement({ impact_rank: null, performance: 3 })).toBe(3);
  });
  it("returns null when neither exists", () => {
    expect(resolveMvpPlacement({})).toBeNull();
  });
});

describe("mvpRank", () => {
  it("maps 1..3 to medals", () => {
    expect(mvpRank(1)).toBe("gold");
    expect(mvpRank(4)).toBe("default");
  });
});
```

- [ ] **Step 2: Run to verify fail** — `cd frontend && bun test src/components/match/__tests__/mvp-rank.test.ts` → FAIL.
- [ ] **Step 3: Implement**
  - типы + `resolveMvpPlacement`;
  - `MvpMatchPill`: `const placement = resolveMvpPlacement(match); if (placement == null) return null;` + после MvpPill, если `match.overperformance_badge`, рендерить вторую пилюлю `<MvpPill rank="default" label={t("users.matches.overperformanceBadge")} />` (компонент уже принимает label; t — прокинуть через `useTranslations`, компонент client);
  - `MatchRow.tsx`: `const mvpMatches = (enc.matches ?? []).filter((m) => resolveMvpPlacement(m) != null);` — то же в `EncounterRow.tsx`;
  - `MatchTeamTable.tsx`: найти массив определения колонок (grep `PerformancePoints`), добавить после него записи для `impact_points` («Impact») и оставить существующую колонку с новой подписью «Очки (классика)» через i18n; новые статы `first_picks`/`ultimate_kills`/... добавить в тот же список, если таблица перечисляет статы явно;
  - i18n (оба словаря): `users.matches.overperformanceBadge` (ru: «Сверх ожиданий», en: "Above expectations"), подписи колонок `matches.stats.impactPoints` (ru: «Impact», en: "Impact"), `matches.stats.classicPoints` (ru: «Очки (классика)», en: "Points (classic)"), имена новых статов (ru: «Первые киллы», «Первые смерти», «Киллы с ульты», «Киллы саппортов»; en: "First picks", "First deaths", "Ultimate kills", "Support kills").
- [ ] **Step 4: Run tests + typecheck** — `cd frontend && bun test src/components/match/__tests__/mvp-rank.test.ts && bunx tsc --noEmit`
Expected: PASS, 0 ошибок tsc (помнить: next build стопает на первом файле — tsc даёт полный список).
- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/user.types.ts frontend/src/components/match/cells.tsx frontend/src/components/match/MvpMatchPill.tsx "frontend/src/app/(site)/users/components/matches/MatchRow.tsx" "frontend/src/app/(site)/users/components/tournaments/EncounterRow.tsx" "frontend/src/app/(site)/matches/[id]/components/MatchTeamTable.tsx" frontend/src/types/stats.types.ts frontend/src/i18n/messages/ru.json frontend/src/i18n/messages/en.json frontend/src/components/match/__tests__/mvp-rank.test.ts
git commit -m "feat(front): MVP pills on impact_rank + overperformance badge + classic points column"
```

---

### Task 10: Runbook выката (НЕ выполняется автоматически)

**Files:**
- Create: `docs/superpowers/plans/2026-07-10-mvp-impact-rollout.md`

Записать шаги оператора (порядок обязателен), без выполнения:

1. Deploy backend (миграция `mvpimp0001` применится штатно при деплое; после — обычный `restart nginx` по чек-листу прода).
2. Сид базлайнов: RPC `rpc.parser.impact.recompute_baselines` (суперюзером) ИЛИ на хосте: `docker compose exec parser-worker uv run python -c "..."` — команда с recompute.
3. Бэкфилл: `docker compose exec parser-worker uv run python backfill_impact.py` (можно по турнирам: `--tournament-id N`).
4. Верификация SQL (read-only):
   - `SELECT count(*) FROM matches.stat_baselines WHERE formula_version='impact_v1';` — ожидаемо `3 роли × 4 бакета(-1,0,1,2) × 17 статов ≈ 204`;
   - `SELECT count(DISTINCT match_id) FROM matches.statistics WHERE name='ImpactRank';` — ≈ числу матчей со статами (~6.9k);
   - выборочно 2-3 матча: `ImpactRank=1` осмыслен (сравнить со старым Performance).
5. Deploy frontend (стандартно; Turbopack-кэш чистить не требуется — токены не менялись).
6. Smoke на проде: профиль игрока — пилюли и бейдж; страница матча — обе колонки очков.

- [ ] **Step 1: Написать runbook** (полный текст команд).
- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-07-10-mvp-impact-rollout.md
git commit -m "docs: impact scoring rollout runbook"
```

---

## Self-Review

**Spec coverage:** §3 семантика → Tasks 1, 8, 9; §4 события → Tasks 3, 5; §5 скоринг (формула, гейт килл-фида, MIN_SECONDS, time_share) → Task 3; §6 базлайны (таблица, версия, бакеты в meta, кэш) → Tasks 2, 4; §7 пайплайн + бэкфилл → Tasks 5, 6; RPC пересчёта → Task 7; §8 API → Task 8; §9 фронт → Task 9; §10 edge cases → тесты Tasks 3, 4, 8; §11 тесты → во всех задачах; выкат → Task 10.

**Известные упрощения (осознанные):** бейдж вычисляется на read-path app-service (окно по OverperformanceScore), не материализуется; ранжирование ImpactRank в per-round группах использует базлайны от 10-минутных рейтов (как и match-level) — допустимо, т.к. ранжирование монотонно по z; RPC-бэкфилла нет (только CLI) — YAGNI.

**Type consistency:** ключи `IMPACT_WEIGHTS`/`EVENT_STATS` = ИМЕНА членов enum (str) — используются через `enums.LogStatsName[name]` в Tasks 3, 5, 6; роль в ключах BaselineSet — `HeroClass.value.lower()` — зафиксировано в Tasks 3 и 4; `PlayerRef` создаётся в Tasks 5 (roster-id ключ) и 6 (user-id ключ) — `player_id` поле в бэкфилле равно user_id, `add_impact_scores` использует только `players[row.player_id]`, согласовано.

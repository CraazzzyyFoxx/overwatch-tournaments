from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


import sqlalchemy as sa  # noqa: E402
from sqlalchemy.exc import MissingGreenlet  # noqa: E402

from shared.core.enums import FirstBanRotation, MapVetoMode, MapVetoSessionStatus, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterPickBanLedger,
    EncounterReadiness,
    PickBanConfig,
    PickBanEntry,
    PickBanSession,
)
from shared.models.tournament.stage import Stage  # noqa: E402
from src.services.encounter.pick_ban_session import (  # noqa: E402
    REASON_NOT_READY,
    REASON_WAITING_MAP,
    pick_ban_session_service,
)
from src.services.encounter.veto_session import (  # noqa: E402
    REASON_BRACKET_PREVIEW,
    REASON_NOT_CONFIGURED,
    REASON_SLOT_COUNT_MISMATCH,
    REASON_SLOT_UNDERFILLED,
    REASON_TEAMS_UNKNOWN,
    SLOT_CANDIDATE_FLOOR,
)


def _slot(position: int, item_ids: list[int], *, reserve: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        position=position,
        reserve_item_id=reserve,
        items=[SimpleNamespace(item_id=item_id) for item_id in item_ids],
    )


def _entry(item_id: int, *, round: int | None = None, status: str = "available", order: int = 0) -> SimpleNamespace:
    """One ``PickBanEntry``-shaped row, as the engine reads it."""
    return SimpleNamespace(
        item_id=item_id,
        round=round,
        status=status,
        order=order,
        action_index=None,
        picked_by=None,
        protected_by=None,
    )


def _config(
    *,
    kind: PickBanKind = PickBanKind.MAP,
    mode: MapVetoMode = MapVetoMode.SLOTS,
    rotation: str = FirstBanRotation.FIXED,
    items: list[int] | None = None,
    slots: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        kind=kind,
        stage_id=None,
        round=None,
        mode=mode,
        preset="bracket",
        first_ban_rotation=rotation,
        sequence_json=["pick_first", "pick_second"],
        turn_timer_seconds=45,
        no_repeat_scope="none",
        items=[SimpleNamespace(item_id=item_id, sort_order=idx) for idx, item_id in enumerate(items or [])],
        slots=slots or [],
    )


def _encounter(*, best_of: int, home: int | None = 10, away: int | None = 20) -> SimpleNamespace:
    return SimpleNamespace(
        id=500,
        tournament_id=7,
        stage_id=3,
        stage_item_id=None,
        round=2,
        best_of=best_of,
        home_team_id=home,
        away_team_id=away,
        home_score=0,
        away_score=0,
    )


def _loads_config_pool(statement: Any) -> bool:
    """Whether a ``PickBanConfig`` query eagerly loads the config's pool."""
    paths = " ".join(str(getattr(option, "path", "")) for option in statement._with_options)
    return "PickBanConfig.items" in paths and "PickBanConfigSlot.items" in paths


class _PoolUnloadedConfig:
    """A ``PickBanConfig`` fetched WITHOUT its pool loader options.

    Reading ``items``/``slots`` off one is a lazy load from a plain attribute
    access, which under async SQLAlchemy raises ``MissingGreenlet`` instead of
    emitting a SELECT -- how ``advance_to_next_round`` broke a whole series in
    production (Sentry OWT-TOURNAMENTS-22Y). The fake raises the same way, so a
    config load that drops the eager options fails here too instead of
    silently handing back a loaded pool.
    """

    def __init__(self, config: Any) -> None:
        self._config = config

    def __getattr__(self, name: str) -> Any:
        if name in ("items", "slots"):
            raise MissingGreenlet(f"lazy load of PickBanConfig.{name} outside a greenlet")
        return getattr(self._config, name)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def unique(self) -> _Result:
        # `shared.repository` reads go through `result.unique().scalars()`, so the
        # fake has to answer it -- it is a no-op here (no joined eager loads).
        return self

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


#: `_FakeSession(map_session=...)` left unset: answer a MAP-kind session lookup
#: with the same `existing` every other kind gets.
_INHERIT = object()


class _FakeSession:
    """Just enough ``AsyncSession`` for ``ensure_pick_ban_session``,
    ``unavailable_reason`` and ``reset_pick_ban_session``. Mirrors
    ``test_veto_session.py``'s ``_FakeSession`` exactly, generalized to the
    ``PickBanConfig``/``PickBanSession`` entities and extended with ``Delete``
    dispatch for the reset path.
    """

    def __init__(
        self,
        *,
        config: Any = None,
        configs: list[Any] | None = None,
        existing: Any = None,
        pool_count: int = 0,
        readiness: frozenset[str] = frozenset({"home", "away"}),
        ledger: list[Any] | None = None,
        entries: list[Any] | None = None,
        encounter: Any = None,
        map_session: Any = _INHERIT,
        stage_published: bool = True,
    ) -> None:
        self.map_session = map_session
        self.config = config
        self.configs = configs
        self.existing = existing
        self.pool_count = pool_count
        # Defaults to "both ready" so every pre-existing test (all written
        # before the readiness gate existed) keeps exercising config/team
        # logic unchanged; only tests that care about the gate pass a
        # narrower set.
        self.readiness = readiness
        # `EncounterPickBanLedger` rows `advance_to_next_round` reads back to
        # build a later round's candidate pool -- empty for every test that
        # predates that call (round 1 never reads the ledger).
        self.ledger = ledger or []
        # The session's existing `PickBanEntry` rows. `advance_to_next_round`
        # reads them to decide whether the round in play is resolved (it never
        # stacks a round on an unfinished one) and which round already exists.
        self.entries = entries or []
        # `advance_to_next_round` reads `best_of` off the encounter to cap the
        # rounds it will ever open.
        self.encounter = encounter
        # Defaults to published so every pre-existing test (all written
        # before the bracket-preview gate existed) keeps exercising
        # config/team logic unchanged; only tests that care about the gate
        # pass ``stage_published=False``.
        self.stage_published = stage_published
        self.added: list[Any] = []
        self.deletes: list[Any] = []
        self.commits = 0
        self.flushes = 0

    def _config_answer(self, statement: Any) -> Any:
        """The config a query gets back: the real one only when it asked for
        the pool, a pool-less proxy otherwise."""
        if self.config is None:
            return None
        return self.config if _loads_config_pool(statement) else _PoolUnloadedConfig(self.config)

    async def get(self, model: Any, pk: Any) -> Any:
        if model is PickBanConfig:
            # `session.get` takes no loader options at any call site here, so
            # the pool is never loaded -- see `_PoolUnloadedConfig`.
            return None if self.config is None else _PoolUnloadedConfig(self.config)
        if model is Encounter:
            return self.encounter
        if model is Stage:
            return SimpleNamespace(is_published=self.stage_published)
        raise AssertionError(f"unexpected get() model: {model}")

    async def execute(self, statement: Any) -> _Result:
        if isinstance(statement, sa.sql.dml.Delete):
            self.deletes.append(statement)
            if statement.table.name == PickBanSession.__tablename__:
                self.existing = None
            elif statement.table.name == EncounterReadiness.__tablename__:
                self.readiness = frozenset()
            return _Result([])
        col = statement.column_descriptions[0]
        entity = col["entity"]
        col_name = str(col.get("name") or col.get("expr") or "")
        if entity is None or col_name.endswith("round"):
            # `list_rounds` is `SELECT pick_ban_entry.round`.
            if "round" in col_name or entity is None:
                return _Result([row.round for row in self.entries])
        if entity is PickBanSession:
            # A hero session's gate reads the MAP session ("is round N's map
            # picked yet?"), so the two cannot share one canned answer. Sniff
            # the compiled WHERE for the kind, same trick the readiness branch
            # below uses for the side. `map_session` left unset means "answer
            # every kind with `existing`", which is what every test predating
            # the hero gate expects.
            if self.map_session is not _INHERIT and "kind = 'map'" in str(
                statement.compile(compile_kwargs={"literal_binds": True})
            ):
                return _Result([] if self.map_session is None else [self.map_session])
            return _Result([] if self.existing is None else [self.existing])
        if getattr(entity, "__name__", None) in {"EncounterMapReport", "Match"}:
            return _Result([])
        if entity is PickBanConfig:
            if self.configs is not None:
                return _Result(
                    [
                        config if _loads_config_pool(statement) else _PoolUnloadedConfig(config)
                        for config in self.configs
                    ]
                )
            answer = self._config_answer(statement)
            return _Result([] if answer is None else [answer])
        if entity is EncounterReadiness:
            # ``mark_ready`` queries a specific side (``select(EncounterReadiness)
            # .where(..., side == X)``); ``get_readiness`` queries all sides for
            # the encounter (no side filter). Distinguish by sniffing the
            # compiled WHERE clause -- there's no ORM-level "which side" the
            # fake can otherwise read off an opaque ``Select``.
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            side_match = re.search(r"side = '(\w+)'", compiled)
            if side_match:
                side = side_match.group(1)
                return _Result([side] if side in self.readiness else [])
            return _Result(sorted(self.readiness))
        if entity is PickBanEntry:
            return _Result(list(self.entries))
        if entity is EncounterPickBanLedger:
            return _Result(list(self.ledger))
        raise AssertionError(f"unexpected execute() entity: {entity}")

    async def scalar(self, statement: Any) -> Any:
        entity = statement.column_descriptions[0]["entity"]
        if entity is None:
            return self.pool_count
        if entity is Stage:
            return None
        if entity is PickBanConfig:
            return self._config_answer(statement)
        raise AssertionError(f"unexpected scalar() entity: {entity}")

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if isinstance(instance, EncounterReadiness):
            self.readiness = self.readiness | {instance.side}

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:  # pragma: no cover - no IntegrityError here
        return None

    @property
    def pool_rows(self) -> list[PickBanEntry]:
        return [row for row in self.added if isinstance(row, PickBanEntry)]

    def deleted_tables(self) -> list[str]:
        return [stmt.table.name for stmt in self.deletes]


class EnsurePickBanSessionSlotReservesTests(IsolatedAsyncioTestCase):
    """``slot_reserves_json`` on the created session -- the parity gap the
    generic engine had against ``EncounterVetoSession.slot_reserves_json``."""

    async def test_slot_mode_snapshots_reserves_for_in_play_slots_only(self) -> None:
        config = _config(
            slots=[
                _slot(1, [11, 12]),
                _slot(2, [21, 22, 23], reserve=99),
                _slot(3, [31, 32], reserve=98),  # out of play at best_of=2
            ]
        )
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=2), PickBanKind.MAP
        )

        assert pick_ban is not None
        self.assertEqual({"2": 99}, pick_ban.slot_reserves_json)

    async def test_flat_mode_has_no_reserve_snapshot(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13, 14, 15])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        assert pick_ban is not None
        self.assertIsNone(pick_ban.slot_reserves_json)

    async def test_no_reserves_is_an_empty_snapshot_not_none(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=2), PickBanKind.MAP
        )

        assert pick_ban is not None
        self.assertEqual({}, pick_ban.slot_reserves_json)


class EnsurePickBanSessionSlotCountMismatchTests(IsolatedAsyncioTestCase):
    """Pins the fix for a tautological check: ``len(list[:n]) < min(len(list),
    n)`` is never true, so the pre-existing mismatch guard never refused a
    series longer than the config's slot count. The real condition is
    ``best_of > len(config.slots)``."""

    async def test_best_of_longer_than_the_slot_count_refuses(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNone(pick_ban)
        self.assertEqual([], session.pool_rows)

    async def test_best_of_equal_to_the_slot_count_is_playable(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=2), PickBanKind.MAP
        )

        self.assertIsNotNone(pick_ban)

    async def test_a_config_with_no_slots_refuses(self) -> None:
        config = _config(slots=[])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=1), PickBanKind.MAP
        )

        self.assertIsNone(pick_ban)


class UnavailableReasonTests(IsolatedAsyncioTestCase):
    """Kind-aware reason derivation against ``PickBanConfig`` -- fixes the bug
    where ``get_pick_ban_state`` used to call the legacy, kind-blind
    ``veto_session.unavailable_reason`` (which resolves ``MapVetoConfig``
    regardless of ``kind``)."""

    async def test_unknown_teams_short_circuit_before_any_query(self) -> None:
        session = _FakeSession()

        reason = await pick_ban_session_service.unavailable_reason(
            session, _encounter(best_of=3, away=None), PickBanKind.MAP
        )

        self.assertEqual(REASON_TEAMS_UNKNOWN, reason)

    async def test_no_config_is_not_configured(self) -> None:
        session = _FakeSession(config=None)

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.HERO)

        self.assertEqual(REASON_NOT_CONFIGURED, reason)

    async def test_a_pool_less_template_is_not_configured(self) -> None:
        """A config with no candidates is a rules template a narrower scope
        inherits from; it opens no room, so the scope that resolves to it reads
        as unconfigured rather than as a slot problem."""
        session = _FakeSession(config=_config(mode=MapVetoMode.POOL, items=[]))

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.MAP)

        self.assertEqual(REASON_NOT_CONFIGURED, reason)
        self.assertIsNone(
            await pick_ban_session_service.ensure_pick_ban_session(
                session, _encounter(best_of=3), PickBanKind.MAP, commit=False
            )
        )

    async def test_more_rounds_than_slots_is_slot_count_mismatch(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22, 23])])
        session = _FakeSession(config=config)

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.MAP)

        self.assertEqual(REASON_SLOT_COUNT_MISMATCH, reason)

    async def test_an_underfilled_slot_in_play_is_slot_underfilled(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21])])
        session = _FakeSession(config=config)

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=2), PickBanKind.MAP)

        self.assertEqual(REASON_SLOT_UNDERFILLED, reason)

    async def test_a_playable_flat_config_reports_not_configured(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config)

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=9), PickBanKind.MAP)

        self.assertEqual(REASON_NOT_CONFIGURED, reason)

    async def test_the_two_slot_reasons_are_distinct_strings(self) -> None:
        self.assertNotEqual(REASON_SLOT_COUNT_MISMATCH, REASON_SLOT_UNDERFILLED)
        self.assertNotIn(REASON_SLOT_COUNT_MISMATCH, {REASON_NOT_CONFIGURED, REASON_TEAMS_UNKNOWN})


class ResolveConfigTemplateShadowTests(IsolatedAsyncioTestCase):
    """A pool-less more-specific row is a rules template: it must not hide a
    parent's pool. Empty per-round fan-outs were closing every room even after
    maps existed at the tournament."""

    async def test_empty_round_config_does_not_shadow_tournament_pool(self) -> None:
        parent = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        parent.id = 69
        child = _config(slots=[])
        child.id = 70
        child.stage_id = 3
        child.round = 2
        session = _FakeSession(configs=[parent, child])

        resolved = await pick_ban_session_service.resolve_config_at_level(
            session,
            tournament_id=7,
            kind=PickBanKind.MAP,
            stage_id=3,
            round=2,
        )

        self.assertIs(resolved, parent)

    async def test_only_templates_still_resolve_to_the_most_specific(self) -> None:
        parent = _config(slots=[])
        parent.id = 69
        child = _config(slots=[])
        child.id = 70
        child.stage_id = 3
        child.round = 2
        session = _FakeSession(configs=[parent, child])

        resolved = await pick_ban_session_service.resolve_config_at_level(
            session,
            tournament_id=7,
            kind=PickBanKind.MAP,
            stage_id=3,
            round=2,
        )

        self.assertIs(resolved, child)


class SyncHeroRoundsWithoutMapPoolTests(IsolatedAsyncioTestCase):
    """No map veto: round 1 opens at ready; round 2 waits on an agreed report."""

    def _hero_session(self, *, complete: bool) -> tuple[SimpleNamespace, SimpleNamespace, _FakeSession]:
        config = _config(mode=MapVetoMode.POOL, kind=PickBanKind.HERO, items=[101, 102, 103, 104])
        config.sequence_json = ["ban_first", "ban_second"]
        pick_ban = SimpleNamespace(
            id=900,
            encounter_id=500,
            kind=PickBanKind.HERO,
            config_id=config.id,
            first_side="home",
            resolved_sequence_json=["ban_home", "ban_away"],
            awaiting_choice=False,
            pending_loser_side=None,
            status=MapVetoSessionStatus.COMPLETED if complete else MapVetoSessionStatus.ACTIVE,
            current_step_started_at=None,
        )
        entries = (
            [_entry(101, round=1, status="banned"), _entry(102, round=1, status="banned")]
            if complete
            else [_entry(101, round=1, status="banned"), _entry(102, round=1, status="available")]
        )
        session = _FakeSession(
            config=config,
            existing=pick_ban,
            map_session=None,
            entries=entries,
            encounter=_encounter(best_of=3),
        )
        return config, pick_ban, session

    async def test_does_not_open_round_two_before_a_map_report(self) -> None:
        _config_row, pick_ban, session = self._hero_session(complete=True)

        with patch.object(
            pick_ban_session_service,
            "_resolve_config",
            new=AsyncMock(return_value=_config(slots=[])),
        ):
            await pick_ban_session_service.sync_hero_rounds(session, session.encounter, commit=True)

        self.assertEqual([], session.pool_rows)
        self.assertEqual(MapVetoSessionStatus.COMPLETED, pick_ban.status)

    async def test_opens_round_two_after_an_agreed_map_report(self) -> None:
        _config_row, pick_ban, session = self._hero_session(complete=True)

        with (
            patch.object(
                pick_ban_session_service,
                "_resolve_config",
                new=AsyncMock(return_value=_config(slots=[])),
            ),
            patch.object(
                pick_ban_session_service,
                "_resolved_report_rounds",
                new=AsyncMock(return_value=1),
            ),
        ):
            await pick_ban_session_service.sync_hero_rounds(session, session.encounter, commit=True)

        self.assertEqual({2}, {row.round for row in session.pool_rows})
        self.assertEqual(MapVetoSessionStatus.ACTIVE, pick_ban.status)

    async def test_does_not_open_round_two_while_round_one_is_still_in_play(self) -> None:
        _config_row, pick_ban, session = self._hero_session(complete=False)

        with patch.object(
            pick_ban_session_service,
            "_resolve_config",
            new=AsyncMock(return_value=_config(slots=[])),
        ):
            await pick_ban_session_service.sync_hero_rounds(session, session.encounter, commit=True)

        self.assertEqual([], session.pool_rows)


class FreeplayMapIndexTests(IsolatedAsyncioTestCase):
    async def test_first_named_map_is_series_position_one(self) -> None:
        from src.services.encounter.map_report import MapReportService

        class Repo:
            async def list_for_encounter(self, session: object, encounter_id: int) -> list:
                return []

        svc = MapReportService(report_repo=Repo())  # type: ignore[arg-type]
        self.assertEqual(1, await svc._freeplay_index(None, 500, 21))

    async def test_second_captain_must_report_the_open_map(self) -> None:
        from src.services.encounter.map_report import MapReportService

        class Repo:
            async def list_for_encounter(self, session: object, encounter_id: int) -> list:
                return [SimpleNamespace(map_index=1, map_id=21, team_id=10, home_score=2, away_score=1)]

        svc = MapReportService(report_repo=Repo())  # type: ignore[arg-type]
        self.assertEqual(1, await svc._freeplay_index(None, 500, 21))
        with self.assertRaises(HTTPException):
            await svc._freeplay_index(None, 500, 99)



class ResetPickBanSessionTests(IsolatedAsyncioTestCase):
    """Delete + re-create, mirroring ``veto_session.reset_veto_session``:
    the entries are not separately deleted here because
    ``pick_ban_entry.session_id`` carries ``ON DELETE CASCADE`` at the DB
    level (unlike legacy ``encounter_map_pool``, which is keyed by
    ``encounter_id`` and needs its own bulk delete)."""

    async def test_deletes_the_existing_session_and_its_kind_scoped_ledger(self) -> None:
        existing = SimpleNamespace(id=900)
        session = _FakeSession(existing=existing, config=None)  # no config -> re-ensure no-ops

        result = await pick_ban_session_service.reset_pick_ban_session(session, _encounter(best_of=3), PickBanKind.MAP)

        self.assertIsNone(result)
        self.assertEqual(
            {PickBanSession.__tablename__, EncounterPickBanLedger.__tablename__},
            set(session.deleted_tables()),
        )
        self.assertEqual(1, session.flushes)
        self.assertEqual(1, session.commits)

    async def test_no_existing_session_still_clears_the_ledger_and_recreates(self) -> None:
        session = _FakeSession(existing=None, config=_config(mode=MapVetoMode.POOL, items=[11, 12, 13]))

        pick_ban = await pick_ban_session_service.reset_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNotNone(pick_ban)
        # Only the ledger delete fires -- there was no session row to delete.
        self.assertEqual([EncounterPickBanLedger.__tablename__], session.deleted_tables())

    async def test_commit_false_flushes_instead_of_committing(self) -> None:
        session = _FakeSession(existing=None, config=_config(mode=MapVetoMode.POOL, items=[11, 12, 13]))

        await pick_ban_session_service.reset_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP, commit=False
        )

        self.assertEqual(0, session.commits)
        self.assertGreaterEqual(session.flushes, 1)


class GetPickBanSessionScopingTests(IsolatedAsyncioTestCase):
    async def test_returns_none_when_nothing_exists(self) -> None:
        session = _FakeSession()

        self.assertIsNone(await pick_ban_session_service.get_pick_ban_session(session, 500, PickBanKind.MAP))


class SyncPickBanSessionAfterTeamChangeTests(IsolatedAsyncioTestCase):
    """Mirrors ``veto_session.sync_veto_session_after_team_change``'s three
    branches exactly."""

    async def test_no_session_and_both_teams_known_creates_one(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(existing=None, config=config)

        await pick_ban_session_service.sync_pick_ban_session_after_team_change(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertEqual(3, len(session.pool_rows))
        self.assertEqual(0, session.commits)  # ensure_pick_ban_session is called with commit=False here

    async def test_no_session_and_teams_still_unknown_is_a_no_op(self) -> None:
        session = _FakeSession(existing=None, config=None)

        await pick_ban_session_service.sync_pick_ban_session_after_team_change(
            session, _encounter(best_of=3, home=None), PickBanKind.MAP
        )

        self.assertEqual([], session.pool_rows)

    async def test_an_existing_session_with_a_played_entry_is_left_alone(self) -> None:
        existing = SimpleNamespace(id=900)
        session = _FakeSession(existing=existing, pool_count=1)

        await pick_ban_session_service.sync_pick_ban_session_after_team_change(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertEqual([], session.deleted_tables())

    async def test_an_existing_session_with_no_played_entries_is_reset(self) -> None:
        existing = SimpleNamespace(id=900)
        session = _FakeSession(existing=existing, pool_count=0, config=None)

        await pick_ban_session_service.sync_pick_ban_session_after_team_change(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIn(PickBanSession.__tablename__, session.deleted_tables())


class ReadinessGateTests(IsolatedAsyncioTestCase):
    """``ensure_pick_ban_session``/``unavailable_reason`` refuse to create or
    explain a session as available until ``EncounterReadiness`` has both
    sides -- checked only once teams/config/slots are otherwise fine, so it
    never masks a more specific reason."""

    async def test_ensure_returns_none_when_readiness_incomplete(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, readiness=frozenset({"home"}))

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNone(pick_ban)
        self.assertEqual([], session.pool_rows)

    async def test_ensure_returns_none_when_no_side_ready(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, readiness=frozenset())

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNone(pick_ban)

    async def test_ensure_creates_once_both_sides_ready(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, readiness=frozenset({"home", "away"}))

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNotNone(pick_ban)
        self.assertEqual(3, len(session.pool_rows))

    async def test_unavailable_reason_is_not_ready_when_config_valid_but_unready(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, readiness=frozenset({"home"}))

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.MAP)

        self.assertEqual(REASON_NOT_READY, reason)

    async def test_unavailable_reason_prefers_teams_unknown_over_not_ready(self) -> None:
        session = _FakeSession(config=None, readiness=frozenset())

        reason = await pick_ban_session_service.unavailable_reason(
            session, _encounter(best_of=3, home=None), PickBanKind.MAP
        )

        self.assertEqual(REASON_TEAMS_UNKNOWN, reason)

    async def test_unavailable_reason_prefers_not_configured_over_not_ready(self) -> None:
        session = _FakeSession(config=None, readiness=frozenset())

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.MAP)

        self.assertEqual(REASON_NOT_CONFIGURED, reason)


class BracketPreviewGateTests(IsolatedAsyncioTestCase):
    """``ensure_pick_ban_session``/``unavailable_reason`` refuse a bracket
    generated as an organizer preview -- the encounter's stage exists but has
    never been activated (``Stage.is_published=False``). Checked ahead of
    config/readiness so a preview never reads as merely unready."""

    async def test_ensure_returns_none_when_stage_not_published(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, stage_published=False)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNone(pick_ban)
        self.assertEqual([], session.pool_rows)

    async def test_unavailable_reason_is_bracket_preview_when_stage_not_published(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, stage_published=False)

        reason = await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.MAP)

        self.assertEqual(REASON_BRACKET_PREVIEW, reason)

    async def test_unavailable_reason_prefers_teams_unknown_over_bracket_preview(self) -> None:
        session = _FakeSession(config=None, stage_published=False)

        reason = await pick_ban_session_service.unavailable_reason(
            session, _encounter(best_of=3, home=None), PickBanKind.MAP
        )

        self.assertEqual(REASON_TEAMS_UNKNOWN, reason)

    async def test_ensure_creates_when_stage_published(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(config=config, stage_published=True)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        self.assertIsNotNone(pick_ban)


class ReadinessHelperTests(IsolatedAsyncioTestCase):
    """``get_readiness``/``both_sides_ready``/``mark_ready``/``reset_readiness``
    in isolation from the session-creation gate above."""

    async def test_get_readiness_reports_each_side_independently(self) -> None:
        session = _FakeSession(readiness=frozenset({"home"}))

        readiness = await pick_ban_session_service.get_readiness(session, 500)

        self.assertEqual({"home": True, "away": False}, readiness)

    async def test_both_sides_ready_requires_both(self) -> None:
        self.assertFalse(
            await pick_ban_session_service.both_sides_ready(_FakeSession(readiness=frozenset({"home"})), 500)
        )
        self.assertTrue(
            await pick_ban_session_service.both_sides_ready(_FakeSession(readiness=frozenset({"home", "away"})), 500)
        )

    async def test_mark_ready_is_idempotent_and_returns_full_map(self) -> None:
        session = _FakeSession(readiness=frozenset())

        first = await pick_ban_session_service.mark_ready(session, _encounter(best_of=3), "home", 42)
        self.assertEqual({"home": True, "away": False}, first)
        self.assertEqual(1, session.commits)

        # Re-confirming the same side does not add a second row or re-commit
        # needlessly -- it just reflects the (unchanged) state back.
        second = await pick_ban_session_service.mark_ready(session, _encounter(best_of=3), "home", 42)
        self.assertEqual({"home": True, "away": False}, second)
        self.assertEqual(1, session.commits)

        third = await pick_ban_session_service.mark_ready(session, _encounter(best_of=3), "away", 99)
        self.assertEqual({"home": True, "away": True}, third)
        self.assertEqual(2, session.commits)

    async def test_reset_readiness_clears_both_sides(self) -> None:
        session = _FakeSession(readiness=frozenset({"home", "away"}))

        await pick_ban_session_service.reset_readiness(session, 500)

        self.assertEqual({"home": False, "away": False}, await pick_ban_session_service.get_readiness(session, 500))
        self.assertIn(EncounterReadiness.__tablename__, session.deleted_tables())


class SyncAllPickBanSessionsAfterTeamChangeTests(IsolatedAsyncioTestCase):
    """The two-kind, legacy-shape wrapper additionally clears readiness --
    a confirmation made against one opponent must not carry over once the
    team assignment changes."""

    async def test_clears_readiness_alongside_both_kinds(self) -> None:
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13])
        session = _FakeSession(existing=None, config=config, readiness=frozenset({"home", "away"}))

        await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, _encounter(best_of=3))

        self.assertEqual({"home": False, "away": False}, await pick_ban_session_service.get_readiness(session, 500))


# Round 1 fully resolved: two non-available entries against the two-token
# sequence `_pick_ban` carries, which is what lets the next round open.
RESOLVED_ROUND_ONE = [_entry(11, round=1, status="banned"), _entry(12, round=1, status="picked")]


class AdvanceToNextRoundCandidateFloorTests(IsolatedAsyncioTestCase):
    """``advance_to_next_round`` must not build a round whose no-repeat
    -filtered candidate pool falls below ``SLOT_CANDIDATE_FLOOR``. Left
    unguarded, that round's ``PickBanEntry`` rows come up short of what
    ``build_slot_sequence`` assumed, and it crashes far later and far less
    clearly, inside ``auto_complete_decider_entry`` on the room's very next
    state read."""

    def _pick_ban(self, config: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(
            id=900,
            encounter_id=500,
            kind=PickBanKind.MAP,
            config_id=config.id,
            first_side="home",
            resolved_sequence_json=["ban_home", "decider"],
            awaiting_choice=False,
            pending_loser_side=None,
            status="active",
            current_step_started_at=None,
        )

    async def test_raises_when_no_repeat_exclusion_depletes_the_next_round(self) -> None:
        # Slot 2 offers the same two maps slot 1 did; round 1 banned one of
        # them, and `no_repeat_scope=encounter` excludes that ban globally --
        # leaving slot 2 only one candidate, below the floor of two.
        config = _config(
            mode=MapVetoMode.SLOTS,
            rotation=FirstBanRotation.RESULT_WINNER_FIRST,
            slots=[_slot(1, [11, 12]), _slot(2, [11, 12])],
        )
        config.no_repeat_scope = "encounter"
        session = _FakeSession(
            config=config,
            ledger=[SimpleNamespace(item_id=11, banned_by_side="home")],
            entries=RESOLVED_ROUND_ONE,
            encounter=_encounter(best_of=2),
        )
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban  # `advance_to_next_round` re-reads it under FOR UPDATE

        with self.assertRaises(HTTPException) as ctx:
            await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner="home")

        self.assertEqual(422, ctx.exception.status_code)
        self.assertIn(
            f"1 candidate(s) left after no-repeat exclusion (needs >= {SLOT_CANDIDATE_FLOOR})", ctx.exception.detail
        )
        self.assertEqual(0, session.commits)

    async def test_does_not_raise_once_the_pool_stays_at_the_floor(self) -> None:
        # Same shape, but nothing has been banned yet -- both slot-2 maps are
        # still candidates, so the round builds normally.
        config = _config(
            mode=MapVetoMode.SLOTS,
            rotation=FirstBanRotation.RESULT_WINNER_FIRST,
            slots=[_slot(1, [11, 12]), _slot(2, [21, 22])],
        )
        config.no_repeat_scope = "encounter"
        session = _FakeSession(
            config=config,
            ledger=[SimpleNamespace(item_id=11, banned_by_side="home")],
            entries=RESOLVED_ROUND_ONE,
            encounter=_encounter(best_of=2),
        )
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban

        result = await pick_ban_session_service.advance_to_next_round(
            session, pick_ban, completed_round=1, winner="home"
        )

        self.assertIs(pick_ban, result)
        self.assertEqual(2, len(session.pool_rows))
        self.assertEqual(1, session.commits)


class ProgressiveRoundCreationTests(IsolatedAsyncioTestCase):
    """A progressive session is created holding round 1 ALONE -- the whole
    point of the pre-game loop: map picked -> heroes banned -> map played and
    reported -> next map. Precomputing every round's entries (what this used
    to do) let both captains ban maps 2 and 3 before map 1 was ever played."""

    async def test_slot_mode_creates_only_the_first_round(self) -> None:
        config = _config(slots=[_slot(1, [11, 12, 13]), _slot(2, [21, 22, 23])])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=2), PickBanKind.MAP
        )

        assert pick_ban is not None
        self.assertEqual([1, 1, 1], [row.round for row in session.pool_rows])
        self.assertEqual([11, 12, 13], [row.item_id for row in session.pool_rows])
        # Slot 1 alone: two bans opened by the higher seed, then its decider.
        self.assertEqual(["ban_home", "ban_away", "decider"], pick_ban.resolved_sequence_json)

    async def test_a_flat_map_config_still_settles_the_whole_series_at_once(self) -> None:
        # The legacy classic veto: one sequence, one round, `round IS NULL`.
        config = _config(mode=MapVetoMode.POOL, items=[11, 12, 13, 14, 15])
        session = _FakeSession(config=config)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.MAP
        )

        assert pick_ban is not None
        self.assertEqual([None] * 5, [row.round for row in session.pool_rows])
        self.assertIn("decider", pick_ban.resolved_sequence_json)

    async def test_a_hero_config_runs_its_own_sequence_per_round(self) -> None:
        config = _config(mode=MapVetoMode.POOL, kind=PickBanKind.HERO, items=[101, 102, 103, 104])
        config.sequence_json = ["ban_first", "ban_second"]
        # `map_session` + `pool_count` stand in for the map phase: a map session
        # exists and one of its entries is picked, so round 1's map is settled
        # and its hero bans may open.
        session = _FakeSession(config=config, map_session=SimpleNamespace(id=800), pool_count=1)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.HERO
        )

        assert pick_ban is not None
        self.assertEqual(["ban_home", "ban_away"], pick_ban.resolved_sequence_json)
        # Every hero is a candidate of round 1 -- and only of round 1.
        self.assertEqual([1, 1, 1, 1], [row.round for row in session.pool_rows])

    async def test_a_hero_decider_token_is_dropped(self) -> None:
        # A hero round bans out of a pool that stays playable, so a decider has
        # no survivor to resolve to and would stall the room on a step nobody
        # can take. Legacy configs (authored when the flat validator demanded a
        # pick or a decider) carry one.
        config = _config(mode=MapVetoMode.POOL, kind=PickBanKind.HERO, items=[101, 102, 103])
        config.sequence_json = ["ban_first", "ban_second", "decider"]
        session = _FakeSession(config=config, map_session=SimpleNamespace(id=800), pool_count=1)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=1), PickBanKind.HERO
        )

        assert pick_ban is not None
        self.assertEqual(["ban_home", "ban_away"], pick_ban.resolved_sequence_json)

    async def test_hero_bans_wait_for_their_map(self) -> None:
        # The map session has settled nothing yet (`pool_count=0`), so round 1's
        # heroes cannot be banned: they are banned FOR a map.
        config = _config(mode=MapVetoMode.POOL, kind=PickBanKind.HERO, items=[101, 102, 103])
        config.sequence_json = ["ban_first", "ban_second"]
        session = _FakeSession(config=config, map_session=SimpleNamespace(id=800), pool_count=0)

        pick_ban = await pick_ban_session_service.ensure_pick_ban_session(
            session, _encounter(best_of=3), PickBanKind.HERO
        )

        self.assertIsNone(pick_ban)
        self.assertEqual([], session.pool_rows)
        self.assertEqual(
            REASON_WAITING_MAP,
            await pick_ban_session_service.unavailable_reason(session, _encounter(best_of=3), PickBanKind.HERO),
        )


class AdvanceToNextRoundLoopTests(IsolatedAsyncioTestCase):
    """The barrier between two maps: who may open the next round, and when."""

    def _pick_ban(
        self, config: SimpleNamespace, *, kind: PickBanKind = PickBanKind.MAP, sequence: list[str] | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=900,
            encounter_id=500,
            kind=kind,
            config_id=config.id,
            first_side="home",
            resolved_sequence_json=sequence if sequence is not None else ["ban_home", "decider"],
            awaiting_choice=False,
            pending_loser_side=None,
            status="completed",
            current_step_started_at=None,
        )

    async def test_a_fixed_rotation_also_advances(self) -> None:
        # Progression is no longer a property of result-dependent rotations
        # alone: every progressive config opens its rounds one map at a time,
        # or a `fixed` one would hand out the whole series' bans up front.
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config, entries=RESOLVED_ROUND_ONE, encounter=_encounter(best_of=2))
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban

        await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner=None)

        self.assertEqual([21, 22], [row.item_id for row in session.pool_rows])
        self.assertEqual(["ban_home", "decider", "ban_home", "decider"], pick_ban.resolved_sequence_json)
        self.assertEqual("active", pick_ban.status)

    async def test_an_unfinished_round_is_never_stacked_on(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(
            config=config,
            entries=[_entry(11, round=1, status="banned"), _entry(12, round=1)],
            encounter=_encounter(best_of=2),
        )
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban

        await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner="home")

        self.assertEqual([], session.pool_rows)
        self.assertEqual(["ban_home", "decider"], pick_ban.resolved_sequence_json)

    async def test_the_series_length_caps_the_rounds(self) -> None:
        # A Bo1 encounter plays one map, whatever the config's slot count says.
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config, entries=RESOLVED_ROUND_ONE, encounter=_encounter(best_of=1))
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban

        await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner="home")

        self.assertEqual([], session.pool_rows)

    async def test_a_hero_round_reopens_the_whole_pool_and_closes_the_last_one(self) -> None:
        config = _config(mode=MapVetoMode.POOL, kind=PickBanKind.HERO, items=[101, 102, 103, 104])
        config.sequence_json = ["ban_first", "ban_second"]
        session = _FakeSession(
            config=config,
            entries=[
                _entry(101, round=1, status="banned"),
                _entry(102, round=1, status="banned"),
                _entry(103, round=1),
                _entry(104, round=1),
            ],
            encounter=_encounter(best_of=3),
        )
        pick_ban = self._pick_ban(config, kind=PickBanKind.HERO, sequence=["ban_home", "ban_away"])
        session.existing = pick_ban

        await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner="away")

        self.assertEqual([101, 102, 103, 104], [row.item_id for row in session.pool_rows])
        self.assertEqual([2, 2, 2, 2], [row.round for row in session.pool_rows])
        # The finished round's untouched candidates are dropped, or the lowest
        # round holding something AVAILABLE would still name round 1 as the one
        # in play and scope round 2's bans to it.
        self.assertIn(PickBanEntry.__tablename__, session.deleted_tables())

    async def test_a_drawn_map_keeps_the_established_opener(self) -> None:
        # `result_winner_first` with no winner: a draw names none. Falling back
        # to the session's opener beats stalling the series on a rotation that
        # cannot resolve.
        config = _config(
            mode=MapVetoMode.SLOTS,
            rotation=FirstBanRotation.RESULT_WINNER_FIRST,
            slots=[_slot(1, [11, 12]), _slot(2, [21, 22, 23])],
        )
        session = _FakeSession(config=config, entries=RESOLVED_ROUND_ONE, encounter=_encounter(best_of=2))
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban

        await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner=None)

        self.assertEqual(["ban_home", "decider", "ban_home", "ban_away", "decider"], pick_ban.resolved_sequence_json)

    async def test_the_next_round_loads_the_config_with_its_pool(self) -> None:
        # Regression, Sentry OWT-TOURNAMENTS-22Y: the config was fetched with
        # `session.get`, which carries no loader options, so reading its slots
        # to build the next round was a lazy load -- `MissingGreenlet` under
        # async SQLAlchemy, 500ing every map report that closed a round and
        # stalling the series mid-way.
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config, entries=RESOLVED_ROUND_ONE, encounter=_encounter(best_of=2))
        pick_ban = self._pick_ban(config)
        session.existing = pick_ban

        unloaded = await session.get(PickBanConfig, config.id)
        with self.assertRaises(MissingGreenlet):
            _ = unloaded.slots

        await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner="home")

        self.assertEqual([21, 22], [row.item_id for row in session.pool_rows])


class AdvanceLocksTheSessionTests(IsolatedAsyncioTestCase):
    """Appending a round is a write gated on a read -- "has round N+1 already
    been appended". Unlocked, two simultaneous readers both answered no and
    both inserted the round's candidates, so the round offered every item
    twice. It locks its own row rather than trusting the caller: a state read,
    a map result and ``elect_opener`` all reach it."""

    async def test_it_locks_before_deciding_anything(self) -> None:
        config = _config(slots=[_slot(1, [11, 12]), _slot(2, [21, 22])])
        session = _FakeSession(config=config, entries=RESOLVED_ROUND_ONE, encounter=_encounter(best_of=2))
        pick_ban = SimpleNamespace(
            id=900,
            encounter_id=500,
            kind=PickBanKind.MAP,
            config_id=config.id,
            first_side="home",
            resolved_sequence_json=["ban_home", "decider"],
            awaiting_choice=False,
            pending_loser_side=None,
            status="completed",
            current_step_started_at=None,
        )
        session.existing = pick_ban
        locked: list[int] = []

        async def spy(_session, target):
            locked.append(target.id)
            return target

        with patch.object(pick_ban_session_service, "lock_pick_ban_session", spy):
            await pick_ban_session_service.advance_to_next_round(session, pick_ban, completed_round=1, winner=None)

        self.assertEqual([900], locked)
        self.assertEqual([21, 22], [row.item_id for row in session.pool_rows])

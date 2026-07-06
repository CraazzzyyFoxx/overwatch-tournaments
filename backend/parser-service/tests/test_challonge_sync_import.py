from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "false"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

sync = importlib.import_module("src.services.challonge.sync")
encounter_flows = importlib.import_module("src.services.encounter.flows")
schemas = importlib.import_module("src.schemas")
enums = importlib.import_module("shared.core.enums")
stage_refs = importlib.import_module("shared.services.stage_refs")


class _Result:
    def __init__(self, *, one=None, all_values=None) -> None:
        self._one = one
        self._all_values = all_values or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return self

    def all(self):
        return self._all_values

    def first(self):
        return self._all_values[0] if self._all_values else self._one


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        del script, numkeys
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


def _challonge_match(
    *,
    match_id: int = 900,
    player1_id: int | None = 101,
    player2_id: int | None = 102,
    state: str = "complete",
    scores_csv: str = "2-1",
    round: int = 1,
    identifier: str = "A",
    group_id: int | None = None,
    player1_prereq_match_id: int | None = None,
    player2_prereq_match_id: int | None = None,
    player1_is_prereq_match_loser: bool = False,
    player2_is_prereq_match_loser: bool = False,
) -> schemas.ChallongeMatch:
    now = datetime.now(UTC)
    return schemas.ChallongeMatch(
        id=match_id,
        started_at=None,
        created_at=now,
        updated_at=now,
        player1_id=player1_id,
        player2_id=player2_id,
        player1_prereq_match_id=player1_prereq_match_id,
        player2_prereq_match_id=player2_prereq_match_id,
        player1_is_prereq_match_loser=player1_is_prereq_match_loser,
        player2_is_prereq_match_loser=player2_is_prereq_match_loser,
        round=round,
        identifier=identifier,
        state=state,
        scores_csv=scores_csv,
        tournament_id=700,
        group_id=group_id,
    )


def _challonge_participant(
    *,
    participant_id: int,
    name: str,
    group_player_ids: list[int],
) -> schemas.ChallongeParticipant:
    now = datetime.now(UTC)
    return schemas.ChallongeParticipant(
        id=participant_id,
        active=True,
        created_at=now,
        updated_at=now,
        name=name,
        tournament_id=700,
        group_player_ids=group_player_ids,
    )


def _source(
    *,
    challonge_id: int = 700,
    group=None,
    stage=None,
    source_id: int | None = None,
) -> sync._ImportSource:
    return sync._ImportSource(
        challonge_id=challonge_id,
        source_id=source_id,
        group=group,
        stage=stage,
    )


def _team_lookup(
    mappings: list,
    teams: list,
) -> sync._TeamLookup:
    return sync._TeamLookup(
        by_source_key={},
        by_key={(row.group_id, row.challonge_id): row.team_id for row in mappings},
        teams_by_id={team.id: team for team in teams},
    )


class ChallongeSyncImportTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.get_redis_patcher = patch.object(
            sync,
            "_get_redis",
            AsyncMock(return_value=_FakeRedis()),
        )
        self.get_redis_patcher.start()
        self.addCleanup(self.get_redis_patcher.stop)

    async def test_discover_sources_reads_challonge_source_rows(self) -> None:
        # discover_sources now reads exclusively from challonge_source; it no
        # longer backfills rows from the deprecated tournament/stage columns.
        tournament = SimpleNamespace(id=7, stages=[], groups=[])
        source_row = SimpleNamespace(
            id=100,
            challonge_tournament_id=700,
            source_type="tournament",
            stage=None,
            stage_id=None,
            stage_item_id=None,
            slug="sample",
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_Result(all_values=[source_row])),
            add=Mock(),
            flush=AsyncMock(),
        )

        sources = await sync.discover_sources(session, tournament)

        self.assertEqual(1, len(sources))
        self.assertEqual(100, sources[0].source_id)
        self.assertEqual(700, sources[0].challonge_id)
        self.assertEqual("sample", sources[0].slug)
        # No rows are ever written here anymore.
        session.add.assert_not_called()

    async def test_import_creates_missing_encounter_from_challonge_match(self) -> None:
        stage_item = SimpleNamespace(id=30, order=0, inputs=[])
        stage = SimpleNamespace(
            id=20,
            name="Playoffs",
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[stage_item],
        )
        group = SimpleNamespace(
            id=10,
            is_groups=False,
            challonge_id=None,
            stage=stage,
            stage_id=stage.id,
        )
        tournament = SimpleNamespace(
            id=7,
            challonge_id=700,
            challonge_slug="sample",
            stages=[stage],
            groups=[group],
        )
        source = _source(group=group, stage=stage)
        home_team = SimpleNamespace(id=1, name="Alpha")
        away_team = SimpleNamespace(id=2, name="Beta")
        mappings = [
            SimpleNamespace(
                group_id=10,
                challonge_id=101,
                team_id=home_team.id,
            ),
            SimpleNamespace(
                group_id=10,
                challonge_id=102,
                team_id=away_team.id,
            ),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(one=tournament),
                    _Result(all_values=[]),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        def add_side_effect(obj):
            if isinstance(obj, sync.models.Encounter):
                obj.id = 501

        session.add.side_effect = add_side_effect

        with (
            patch.object(sync, "discover_sources", AsyncMock(return_value=[source])),
            patch.object(sync.challonge_service, "fetch_matches", AsyncMock(return_value=[_challonge_match()])),
            patch.object(sync.challonge_service, "fetch_participants", AsyncMock(return_value=[])),
            patch.object(
                sync, "_build_team_lookup", AsyncMock(return_value=_team_lookup(mappings, [home_team, away_team]))
            ),
            patch.object(sync, "_build_match_lookup", AsyncMock(return_value=sync._MatchLookup({}, {}, set()))),
            patch.object(
                sync,
                "resolve_stage_refs_from_group",
                AsyncMock(
                    return_value=stage_refs.StageRefs(
                        stage_id=20,
                        stage_item_id=30,
                        tournament_group_id=10,
                    )
                ),
            ),
            patch.object(
                sync.standings_recalculation,
                "enqueue_tournament_recalculation",
                AsyncMock(),
            ) as enqueue_recalculation,
        ):
            result = await sync.import_tournament(session, tournament.id)

        created = next(
            obj for call in session.add.call_args_list for obj in call.args if isinstance(obj, sync.models.Encounter)
        )
        self.assertEqual(1, result["matches_synced"])
        self.assertEqual(1, result["matches_created"])
        self.assertEqual(0, result["errors"])
        # encounter.challonge_id is no longer written (link lives in challonge_match_mapping).
        self.assertEqual((home_team.id, away_team.id), (created.home_team_id, created.away_team_id))
        self.assertEqual((2, 1), (created.home_score, created.away_score))
        self.assertEqual(enums.EncounterStatus.COMPLETED, created.status)
        self.assertEqual((20, 30, 10), (created.stage_id, created.stage_item_id, created.tournament_group_id))
        created_inputs = [
            obj
            for call in session.add.call_args_list
            for obj in call.args
            if isinstance(obj, sync.models.StageItemInput)
        ]
        self.assertEqual([home_team.id, away_team.id], [inp.team_id for inp in created_inputs])
        self.assertEqual([1, 2], [inp.slot for inp in created_inputs])
        self.assertEqual([30, 30], [inp.stage_item_id for inp in created_inputs])
        self.assertEqual(2, result["stage_inputs_created"])
        session.commit.assert_awaited_once_with()
        enqueue_recalculation.assert_awaited_once_with(tournament.id)

    async def test_import_creates_bracket_structure_and_pending_advancement_match(self) -> None:
        tournament = SimpleNamespace(
            id=7,
            challonge_id=700,
            challonge_slug="sample",
            stages=[],
            groups=[],
        )
        source = _source()
        teams = [
            SimpleNamespace(id=1, name="Alpha"),
            SimpleNamespace(id=2, name="Beta"),
            SimpleNamespace(id=3, name="Gamma"),
            SimpleNamespace(id=4, name="Delta"),
        ]
        mappings = [
            SimpleNamespace(group_id=None, challonge_id=101, team_id=1),
            SimpleNamespace(group_id=None, challonge_id=102, team_id=2),
            SimpleNamespace(group_id=None, challonge_id=103, team_id=3),
            SimpleNamespace(group_id=None, challonge_id=104, team_id=4),
        ]
        challonge_matches = [
            _challonge_match(
                match_id=900,
                player1_id=101,
                player2_id=102,
                state="complete",
                scores_csv="2-0",
                round=1,
                identifier="A",
            ),
            _challonge_match(
                match_id=902,
                player1_id=103,
                player2_id=104,
                state="open",
                scores_csv="",
                round=1,
                identifier="B",
            ),
            _challonge_match(
                match_id=901,
                player1_id=None,
                player2_id=None,
                state="pending",
                scores_csv="",
                round=2,
                identifier="C",
                player1_prereq_match_id=900,
                player2_prereq_match_id=902,
            ),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(one=tournament),
                    _Result(all_values=[]),
                    _Result(all_values=[]),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        next_ids = {
            sync.models.Stage: 20,
            sync.models.StageItem: 30,
            sync.models.TournamentGroup: 10,
            sync.models.EncounterLink: 800,
        }
        # encounter.challonge_id is no longer written, so ids are assigned in
        # creation order (matches are processed as [900, 902, 901]).
        encounter_id_counter = [1400]

        def add_side_effect(obj):
            for model, next_id in list(next_ids.items()):
                if isinstance(obj, model):
                    obj.id = next_id
                    next_ids[model] = next_id + 1
                    return
            if isinstance(obj, sync.models.Encounter):
                obj.id = encounter_id_counter[0]
                encounter_id_counter[0] += 1

        session.add.side_effect = add_side_effect

        with (
            patch.object(sync, "discover_sources", AsyncMock(return_value=[source])),
            patch.object(sync.challonge_service, "fetch_matches", AsyncMock(return_value=challonge_matches)),
            patch.object(sync.challonge_service, "fetch_participants", AsyncMock(return_value=[])),
            patch.object(sync, "_build_team_lookup", AsyncMock(return_value=_team_lookup(mappings, teams))),
            patch.object(sync, "_build_match_lookup", AsyncMock(return_value=sync._MatchLookup({}, {}, set()))),
            patch.object(
                sync,
                "resolve_stage_refs_from_group",
                AsyncMock(
                    return_value=stage_refs.StageRefs(
                        stage_id=20,
                        stage_item_id=30,
                        tournament_group_id=10,
                    )
                ),
            ),
            patch.object(sync, "_advance_completed_challonge_matches", AsyncMock()),
            patch.object(
                sync.standings_recalculation,
                "enqueue_tournament_recalculation",
                AsyncMock(),
            ),
        ):
            result = await sync.import_tournament(session, tournament.id)

        added_objects = [obj for call in session.add.call_args_list for obj in call.args]
        created_encounters = [obj for obj in added_objects if isinstance(obj, sync.models.Encounter)]
        created_links = [obj for obj in added_objects if isinstance(obj, sync.models.EncounterLink)]
        created_group = next(obj for obj in added_objects if isinstance(obj, sync.models.TournamentGroup))
        created_stage = next(obj for obj in added_objects if isinstance(obj, sync.models.Stage))
        # The pending advancement match has no resolved teams yet.
        pending = next(obj for obj in created_encounters if obj.home_team_id is None)

        self.assertEqual(3, result["matches_synced"])
        self.assertEqual(3, result["matches_created"])
        self.assertEqual(1, result["groups_created"])
        self.assertEqual(1, result["stages_created"])
        self.assertEqual(2, result["bracket_links_created"])
        self.assertEqual("Playoffs", created_group.name)
        self.assertEqual(enums.StageType.SINGLE_ELIMINATION, created_stage.stage_type)
        self.assertEqual((None, None), (pending.home_team_id, pending.away_team_id))
        self.assertEqual(enums.EncounterStatus.PENDING, pending.status)
        self.assertEqual("TBD vs TBD", pending.name)
        # Encounters are created in match-processing order [900, 902, 901] ->
        # ids 1400, 1401, 1402. Match 901's prereqs are 900 (HOME) and 902 (AWAY).
        self.assertEqual(
            {
                (1400, 1402, enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.HOME),
                (1401, 1402, enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY),
            },
            {
                (
                    link.source_encounter_id,
                    link.target_encounter_id,
                    link.role,
                    link.target_slot,
                )
                for link in created_links
            },
        )

    async def test_import_reports_missing_team_mapping_as_error(self) -> None:
        tournament = SimpleNamespace(
            id=7,
            challonge_id=700,
            challonge_slug="sample",
            stages=[],
            groups=[],
        )
        source = _source()
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(one=tournament),
                    _Result(all_values=[]),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(sync, "discover_sources", AsyncMock(return_value=[source])),
            patch.object(sync.challonge_service, "fetch_matches", AsyncMock(return_value=[_challonge_match()])),
            patch.object(sync.challonge_service, "fetch_participants", AsyncMock(return_value=[])),
            patch.object(
                sync,
                "_ensure_stage_structure_for_matches",
                AsyncMock(return_value={"groups_created": 0, "stages_created": 0}),
            ),
            patch.object(sync, "_build_team_lookup", AsyncMock(return_value=_team_lookup([], []))),
            patch.object(sync, "_build_match_lookup", AsyncMock(return_value=sync._MatchLookup({}, {}, set()))),
            patch.object(
                sync.standings_recalculation,
                "enqueue_tournament_recalculation",
                AsyncMock(),
            ) as enqueue_recalculation,
        ):
            result = await sync.import_tournament(session, tournament.id)

        self.assertEqual(0, result["matches_synced"])
        self.assertEqual(1, result["errors"])
        self.assertFalse(
            any(isinstance(obj, sync.models.Encounter) for call in session.add.call_args_list for obj in call.args)
        )
        session.commit.assert_awaited_once_with()
        enqueue_recalculation.assert_not_awaited()

    async def test_import_updates_existing_encounter_without_team_mapping(self) -> None:
        tournament = SimpleNamespace(
            id=7,
            challonge_id=700,
            challonge_slug="sample",
            stages=[],
            groups=[],
        )
        source = _source()
        existing = SimpleNamespace(
            id=501,
            challonge_id=900,
            name="Existing",
            home_team_id=1,
            away_team_id=2,
            home_score=0,
            away_score=0,
            round=1,
            tournament_group_id=None,
            stage_id=None,
            stage_item_id=None,
            status=enums.EncounterStatus.OPEN,
        )
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(one=tournament),
                    _Result(all_values=[]),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(sync, "discover_sources", AsyncMock(return_value=[source])),
            patch.object(
                sync.challonge_service,
                "fetch_matches",
                AsyncMock(return_value=[_challonge_match(state="open", scores_csv="1-0")]),
            ),
            patch.object(sync.challonge_service, "fetch_participants", AsyncMock(return_value=[])),
            patch.object(
                sync,
                "_ensure_stage_structure_for_matches",
                AsyncMock(return_value={"groups_created": 0, "stages_created": 0}),
            ),
            patch.object(sync, "_build_team_lookup", AsyncMock(return_value=_team_lookup([], []))),
            patch.object(
                sync, "_build_match_lookup", AsyncMock(return_value=sync._MatchLookup({}, {900: existing}, set()))
            ),
            patch.object(
                sync,
                "resolve_stage_refs_from_group",
                AsyncMock(
                    return_value=stage_refs.StageRefs(
                        stage_id=20,
                        stage_item_id=30,
                        tournament_group_id=None,
                    )
                ),
            ),
            patch.object(
                sync.standings_recalculation,
                "enqueue_tournament_recalculation",
                AsyncMock(),
            ) as enqueue_recalculation,
        ):
            result = await sync.import_tournament(session, tournament.id)

        self.assertEqual(1, result["matches_synced"])
        self.assertEqual(0, result["matches_created"])
        self.assertEqual(1, result["matches_updated"])
        self.assertEqual(0, result["errors"])
        self.assertEqual((1, 0), (existing.home_score, existing.away_score))
        self.assertEqual((20, 30), (existing.stage_id, existing.stage_item_id))
        self.assertEqual(enums.EncounterStatus.OPEN, existing.status)
        self.assertFalse(
            any(isinstance(obj, sync.models.Encounter) for call in session.add.call_args_list for obj in call.args)
        )
        enqueue_recalculation.assert_awaited_once_with(tournament.id)

    async def test_import_does_not_overwrite_completed_local_result(self) -> None:
        tournament = SimpleNamespace(
            id=7,
            challonge_id=700,
            challonge_slug="sample",
            stages=[],
            groups=[],
        )
        source = _source()
        existing = SimpleNamespace(
            id=501,
            challonge_id=900,
            name="Alpha vs Beta",
            home_team_id=1,
            away_team_id=2,
            home_score=2,
            away_score=0,
            round=1,
            tournament_id=7,
            tournament_group_id=None,
            stage_id=20,
            stage_item_id=30,
            status=enums.EncounterStatus.COMPLETED,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_Result(one=tournament)]),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(sync, "discover_sources", AsyncMock(return_value=[source])),
            patch.object(
                sync.challonge_service,
                "fetch_matches",
                AsyncMock(return_value=[_challonge_match(state="complete", scores_csv="0-2")]),
            ),
            patch.object(sync.challonge_service, "fetch_participants", AsyncMock(return_value=[])),
            patch.object(
                sync,
                "_ensure_stage_structure_for_matches",
                AsyncMock(return_value={"groups_created": 0, "stages_created": 0}),
            ),
            patch.object(sync, "_build_team_lookup", AsyncMock(return_value=_team_lookup([], []))),
            patch.object(
                sync, "_build_match_lookup", AsyncMock(return_value=sync._MatchLookup({}, {900: existing}, set()))
            ),
            patch.object(
                sync,
                "resolve_stage_refs_from_group",
                AsyncMock(
                    return_value=stage_refs.StageRefs(
                        stage_id=20,
                        stage_item_id=30,
                        tournament_group_id=None,
                    )
                ),
            ),
            patch.object(
                sync.standings_recalculation,
                "enqueue_tournament_recalculation",
                AsyncMock(),
            ) as enqueue_recalculation,
        ):
            result = await sync.import_tournament(session, tournament.id)

        self.assertEqual(1, result["conflicts"])
        self.assertEqual((2, 0), (existing.home_score, existing.away_score))
        self.assertEqual(enums.EncounterStatus.COMPLETED, existing.status)
        enqueue_recalculation.assert_not_awaited()

    async def test_export_uses_source_specific_match_and_participant_mapping(self) -> None:
        source_row = SimpleNamespace(
            id=55,
            challonge_tournament_id=9001,
            source_type="stage",
            stage_item_id=30,
        )
        encounter = SimpleNamespace(
            id=501,
            challonge_id=777,
            tournament_id=7,
            tournament_group_id=None,
            stage_id=20,
            stage_item_id=30,
            home_team_id=1,
            away_team_id=2,
            home_score=2,
            away_score=1,
            home_team=SimpleNamespace(id=1, challonge=[]),
            away_team=SimpleNamespace(id=2, challonge=[]),
        )
        tournament = SimpleNamespace(id=7)
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(
                        all_values=[
                            SimpleNamespace(
                                source=source_row,
                                challonge_match_id=888,
                            )
                        ]
                    ),
                    _Result(
                        all_values=[
                            SimpleNamespace(
                                source_id=55,
                                challonge_participant_id=123,
                                team_id=1,
                            )
                        ]
                    ),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
        )

        with patch.object(sync.challonge_service, "update_match", AsyncMock()) as update_match:
            pushed = await sync.push_single_result(session, tournament, encounter)

        self.assertTrue(pushed)
        update_match.assert_awaited_once_with(
            9001,
            888,
            scores_csv="2-1",
            winner_id=123,
        )

    async def test_auto_push_does_not_require_root_tournament_challonge_id(self) -> None:
        tournament = SimpleNamespace(id=7, challonge_id=None)
        encounter = SimpleNamespace(
            id=501,
            challonge_id=777,
            tournament=tournament,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_Result(one=encounter)),
            commit=AsyncMock(),
        )

        with (
            patch.object(
                sync,
                "resolve_encounter_challonge",
                AsyncMock(return_value={encounter.id: 777}),
            ),
            patch.object(
                sync,
                "push_single_result",
                AsyncMock(return_value=True),
            ) as push_single_result,
        ):
            await sync.auto_push_on_confirm(session, encounter.id)

        push_single_result.assert_awaited_once_with(session, tournament, encounter)
        session.commit.assert_awaited_once()

    async def test_import_resolves_match_group_player_ids_from_participant_mapping(self) -> None:
        tournament = SimpleNamespace(
            id=7,
            challonge_id=700,
            challonge_slug="sample",
            stages=[],
            groups=[
                SimpleNamespace(
                    id=10,
                    is_groups=True,
                    challonge_id=123,
                    stage=None,
                )
            ],
        )
        source = _source(group=tournament.groups[0])
        home_team = SimpleNamespace(id=1, name="Alpha")
        away_team = SimpleNamespace(id=2, name="Beta")
        mappings = [
            SimpleNamespace(
                group_id=10,
                challonge_id=101,
                team_id=home_team.id,
            ),
            SimpleNamespace(
                group_id=10,
                challonge_id=102,
                team_id=away_team.id,
            ),
        ]
        source_key = sync._source_lookup_key(source)
        source_lookup = {
            (source_key, 44066538): home_team.id,
            (source_key, 44066539): away_team.id,
        }
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(one=tournament),
                    _Result(all_values=[]),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        def add_side_effect(obj):
            if isinstance(obj, sync.models.Encounter):
                obj.id = 502

        session.add.side_effect = add_side_effect

        with (
            patch.object(sync, "discover_sources", AsyncMock(return_value=[source])),
            patch.object(
                sync.challonge_service,
                "fetch_participants",
                AsyncMock(
                    return_value=[
                        _challonge_participant(
                            participant_id=101,
                            name="Alpha",
                            group_player_ids=[44066538],
                        ),
                        _challonge_participant(
                            participant_id=102,
                            name="Beta",
                            group_player_ids=[44066539],
                        ),
                    ]
                ),
            ),
            patch.object(
                sync.challonge_service,
                "fetch_matches",
                AsyncMock(
                    return_value=[
                        _challonge_match(
                            player1_id=44066538,
                            player2_id=44066539,
                            group_id=123,
                        )
                    ]
                ),
            ),
            patch.object(
                sync,
                "_build_team_lookup",
                AsyncMock(
                    return_value=sync._TeamLookup(
                        by_source_key=source_lookup,
                        by_key={(row.group_id, row.challonge_id): row.team_id for row in mappings},
                        teams_by_id={home_team.id: home_team, away_team.id: away_team},
                    )
                ),
            ),
            patch.object(sync, "_build_match_lookup", AsyncMock(return_value=sync._MatchLookup({}, {}, set()))),
            patch.object(
                sync,
                "resolve_stage_refs_from_group",
                AsyncMock(
                    return_value=stage_refs.StageRefs(
                        stage_id=20,
                        stage_item_id=30,
                        tournament_group_id=10,
                    )
                ),
            ),
            patch.object(
                sync.standings_recalculation,
                "enqueue_tournament_recalculation",
                AsyncMock(),
            ),
        ):
            result = await sync.import_tournament(session, tournament.id)

        self.assertEqual(1, result["matches_synced"])
        self.assertEqual(1, result["matches_created"])
        self.assertEqual(0, result["errors"])
        created = next(
            obj for call in session.add.call_args_list for obj in call.args if isinstance(obj, sync.models.Encounter)
        )
        self.assertEqual((home_team.id, away_team.id), (created.home_team_id, created.away_team_id))

    async def test_legacy_encounter_challonge_wrapper_uses_unified_import(self) -> None:
        session = SimpleNamespace()
        expected = {
            "matches_synced": 1,
            "matches_created": 1,
            "matches_updated": 0,
            "matches_skipped": 0,
            "errors": 0,
        }

        with patch.object(
            encounter_flows.challonge_sync,
            "import_tournament",
            AsyncMock(return_value=expected),
        ) as import_tournament:
            result = await encounter_flows.bulk_create_for_tournament_from_challonge(
                session,
                7,
            )

        self.assertEqual(expected, result)
        import_tournament.assert_awaited_once_with(session, 7)

    async def test_bulk_legacy_encounter_challonge_wrapper_aggregates_unified_import(self) -> None:
        session = SimpleNamespace()
        tournaments = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        with (
            patch.object(
                encounter_flows.tournament_service,
                "get_all",
                AsyncMock(return_value=tournaments),
            ),
            patch.object(
                encounter_flows.challonge_sync,
                "import_tournament",
                AsyncMock(
                    side_effect=[
                        {
                            "matches_synced": 2,
                            "matches_created": 1,
                            "matches_updated": 1,
                            "matches_skipped": 0,
                            "errors": 0,
                        },
                        {"error": "Tournament has no Challonge source"},
                    ]
                ),
            ),
        ):
            result = await encounter_flows.bulk_create_for_from_challonge(session)

        self.assertEqual(
            {
                "tournaments_synced": 2,
                "matches_synced": 2,
                "matches_created": 1,
                "matches_updated": 1,
                "matches_skipped": 0,
                "errors": 1,
            },
            result,
        )

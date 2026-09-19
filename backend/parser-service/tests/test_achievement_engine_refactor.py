from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from sqlalchemy.dialects import postgresql  # noqa: E402

from shared.core.enums import StageType  # noqa: E402
from shared.models.achievements.achievement import AchievementGrain, AchievementRule  # noqa: E402
from shared.services.achievement_effective import override_applies_to_scope  # noqa: E402
from src.domain.achievement_catalog import (  # noqa: E402
    RULES,
    _all_default_rules,
    _hero_kd_rules,
    get_default_rule_slugs,
)
from src.domain.achievement_validation import (  # noqa: E402
    LEAF_GRAINS,
    infer_grain,
    leaf_grain,
    validate_condition_tree,
)
from src.services.achievement.engine import differ as differ_module  # noqa: E402
from src.services.achievement.engine.conditions import (  # noqa: E402
    get_registered_types,
    resolve_stat_name,
)
from src.services.achievement.engine.conditions.tournament_format import (  # noqa: E402
    matches_tournament_format,
)
from src.services.achievement.engine.differ import (  # noqa: E402
    EvaluationSlice,
    diff_and_apply,
    persist_slice_for_grain,
)


def _catalog_text() -> dict[str, tuple[str, str, str]]:
    return {rule.slug: (rule.name, rule.description_ru, rule.description_en) for rule in RULES}


class DiffScopeTests(IsolatedAsyncioTestCase):
    async def test_tournament_scoped_diff_does_not_delete_other_tournament_results(self) -> None:
        rule = AchievementRule(id=7, slug="afgan", rule_version=3, grain=AchievementGrain.user_tournament)

        async def execute_side_effect(query):
            sql = str(query)
            if "SELECT achievements.evaluation_result.id" in sql:
                if "tournament_id" in sql and "=" in sql:
                    return [
                        (101, 55, 10, None, None),
                    ]
                return [
                    (101, 55, 10, None, None),
                    (202, 55, 20, None, None),
                ]
            return None

        session = SimpleNamespace(
            execute=AsyncMock(side_effect=execute_side_effect),
            add=lambda _row: None,
        )

        diff = await diff_and_apply(
            session=session,
            rule=rule,
            new_results={(55, 10)},
            run_id="run-1",
            evaluation_slice=EvaluationSlice(tournament_id=10),
        )

        self.assertEqual([], diff.to_delete)

    def test_persist_slice_omits_scope_for_user_grain(self) -> None:
        self.assertIsNone(persist_slice_for_grain(AchievementGrain.user, tournament_id=10, match_id=3))

    def test_persist_slice_keeps_tournament_for_tournament_grain(self) -> None:
        slice_ = persist_slice_for_grain(AchievementGrain.user_tournament, tournament_id=10, match_id=3)
        self.assertEqual(10, slice_.tournament_id)
        self.assertIsNone(slice_.match_id)

    def test_persist_slice_keeps_match_for_match_grain(self) -> None:
        slice_ = persist_slice_for_grain(AchievementGrain.user_match, tournament_id=10, match_id=3)
        self.assertEqual(10, slice_.tournament_id)
        self.assertEqual(3, slice_.match_id)


class DiffWorkspaceMemberResolutionTests(IsolatedAsyncioTestCase):
    """P6: ``AchievementEvaluationResult`` moved onto ``workspace_member_id``.

    ``new_results`` still carries the player identity (what the condition
    evaluator returns), so the insert path must resolve/create the
    workspace_member for the rule's own workspace before persisting — and the
    existing-rows read must key off the player identity it recovers via the
    workspace_member join, so an already-qualified player is not re-inserted.

    Rows are persisted with a single ``INSERT ... ON CONFLICT DO NOTHING``
    (concurrent runs for one workspace used to collide on
    ``uq_eval_result_dedup_coalesced``), so these tests inspect the emitted
    statement rather than ``session.add`` calls.
    """

    @staticmethod
    def _fake_session(existing_rows: list[tuple[object, ...]]) -> tuple[SimpleNamespace, list[object]]:
        """Session double returning ``existing_rows`` for the diff read.

        Returns the session and the list that collects every non-read statement
        passed to ``execute`` (the reconcile insert, and any delete).
        """
        statements: list[object] = []

        async def execute_side_effect(query):
            sql = str(query)
            if "SELECT achievements.evaluation_result.id" in sql:
                return existing_rows
            statements.append(query)
            return None

        session = SimpleNamespace(
            execute=AsyncMock(side_effect=execute_side_effect),
            add=lambda _row: None,
            flush=AsyncMock(),
        )
        return session, statements

    @staticmethod
    def _insert_rows(statements: list[object]) -> list[dict]:
        """Values carried by the reconcile INSERT, asserting it is upsert-safe."""
        inserts = [s for s in statements if str(s).startswith("INSERT INTO achievements.evaluation_result")]
        assert len(inserts) == 1, f"expected exactly one reconcile insert, got {len(inserts)}"
        compiled = inserts[0].compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "ON CONFLICT" in sql and "DO NOTHING" in sql, sql
        # The conflict target must repeat the functional index's COALESCE
        # expressions with literal zeros, or Postgres will not match it and the
        # duplicate-key crash comes back (migration perfidx05).
        assert "coalesce(tournament_id, 0)" in sql, sql
        assert "coalesce(encounter_id, 0)" in sql, sql
        assert "coalesce(match_id, 0)" in sql, sql
        # Multi-row VALUES render as <column>_m<row index> bind parameters.
        rows: dict[int, dict] = {}
        for key, value in compiled.params.items():
            column, _, index = key.rpartition("_m")
            if not index.isdigit():
                continue
            rows.setdefault(int(index), {})[column] = value
        return [rows[i] for i in sorted(rows)]

    async def test_insert_path_resolves_workspace_member_for_new_player(self) -> None:
        rule = AchievementRule(id=9, slug="newcomer", rule_version=1, workspace_id=3, grain=AchievementGrain.user_match)
        session, statements = self._fake_session([])

        fake_member = SimpleNamespace(id=777)
        get_or_create = AsyncMock(return_value=fake_member)

        with patch.object(differ_module, "get_or_create_workspace_member", get_or_create):
            diff = await diff_and_apply(
                session=session,
                rule=rule,
                new_results={(55, None, None)},
                run_id="run-1",
            )

        get_or_create.assert_awaited_once_with(session, workspace_id=3, player_id=55)
        rows = self._insert_rows(statements)
        self.assertEqual(1, len(rows))
        self.assertEqual(777, rows[0]["workspace_member_id"])
        self.assertNotIn("user_id", rows[0])
        self.assertEqual(1, len(diff.to_insert))
        self.assertEqual(55, diff.to_insert[0]["user_id"])

    async def test_insert_path_memoizes_workspace_member_per_player_across_rows(self) -> None:
        """Two new rows for the same player (different tournaments) must only
        resolve/create the workspace_member once."""
        rule = AchievementRule(
            id=9, slug="newcomer", rule_version=1, workspace_id=3, grain=AchievementGrain.user_tournament
        )
        session, statements = self._fake_session([])

        fake_member = SimpleNamespace(id=888)
        get_or_create = AsyncMock(return_value=fake_member)

        with patch.object(differ_module, "get_or_create_workspace_member", get_or_create):
            diff = await diff_and_apply(
                session=session,
                rule=rule,
                new_results={(55, 10), (55, 20)},
                run_id="run-1",
            )

        get_or_create.assert_awaited_once_with(session, workspace_id=3, player_id=55)
        rows = self._insert_rows(statements)
        self.assertEqual(2, len(rows))
        self.assertTrue(all(row["workspace_member_id"] == 888 for row in rows))
        self.assertEqual(2, len(diff.to_insert))

    async def test_existing_rows_key_off_player_identity_via_workspace_member_join(self) -> None:
        """A stored row's player identity is recovered through the
        workspace_member join; a new result for the same player must not be
        re-inserted (no spurious get_or_create call, no insert at all)."""
        rule = AchievementRule(
            id=9, slug="newcomer", rule_version=1, workspace_id=3, grain=AchievementGrain.user_tournament
        )
        # (row_id, player_id, tournament_id, encounter_id, match_id) — player_id
        # recovered via the workspace_member join, not a raw column.
        session, statements = self._fake_session([(101, 55, 10, None, None)])

        get_or_create = AsyncMock()

        with patch.object(differ_module, "get_or_create_workspace_member", get_or_create):
            diff = await diff_and_apply(
                session=session,
                rule=rule,
                new_results={(55, 10)},
                run_id="run-1",
            )

        get_or_create.assert_not_awaited()
        self.assertEqual([], statements)
        self.assertEqual([], diff.to_insert)
        self.assertEqual([], diff.to_delete)


class ValidationTests(TestCase):
    def test_resolve_stat_name_maps_legacy_critical_hit_kills_alias(self) -> None:
        self.assertEqual("ScopedCriticalHitKills", resolve_stat_name("CriticalHitKills"))

    def test_rejects_top_level_player_role_condition(self) -> None:
        errors = validate_condition_tree({"type": "player_role", "params": {"role": "Damage"}})
        self.assertTrue(any("top-level" in error for error in errors))

    def test_rejects_legacy_stat_alias_in_condition_tree(self) -> None:
        errors = validate_condition_tree(
            {
                "type": "stat_threshold",
                "params": {"stat": "CriticalHitKills", "op": ">=", "value": 10},
            }
        )
        self.assertTrue(any("ScopedCriticalHitKills" in error for error in errors))

    def test_distinct_count_with_tournament_scope_infers_tournament_grain(self) -> None:
        grain = infer_grain(
            {
                "type": "distinct_count",
                "params": {"field": "hero", "op": ">=", "value": 7, "scope": "tournament"},
            }
        )
        self.assertEqual(AchievementGrain.user_tournament, grain)

    def test_default_rule_grains_match_inferred_grains(self) -> None:
        mismatches = [
            (rule.slug, rule.grain, infer_grain(rule.condition_tree))
            for rule in _all_default_rules(1)
            if rule.condition_tree and infer_grain(rule.condition_tree) != rule.grain
        ]
        self.assertEqual([], mismatches)

    def test_all_default_rules_are_implemented(self) -> None:
        """Every canonical achievement has a real condition tree (no placeholders)."""
        placeholders = [rule.slug for rule in _all_default_rules(1) if not rule.condition_tree]
        self.assertEqual([], placeholders)

    def test_all_default_condition_trees_validate(self) -> None:
        errors = {
            rule.slug: validate_condition_tree(rule.condition_tree)
            for rule in _all_default_rules(1)
            if rule.condition_tree and validate_condition_tree(rule.condition_tree)
        }
        self.assertEqual({}, errors)

    def test_new_leaf_types_registered_with_grain(self) -> None:
        registered = set(get_registered_types())
        for ctype in (
            "log_stat_rank",
            "standing_count",
            "tournament_winrate",
            "div_span",
            "hero_pickrate",
            "teammate_recurrence",
            "team_otp_count",
            "reached_playoffs",
        ):
            self.assertIn(ctype, registered)
            self.assertIn(ctype, LEAF_GRAINS)

    def test_reached_playoffs_scope_drives_grain(self) -> None:
        self.assertEqual(
            AchievementGrain.user,
            infer_grain({"type": "reached_playoffs", "params": {"scope": "global", "op": "==", "value": 0}}),
        )
        self.assertEqual(
            AchievementGrain.user_tournament,
            infer_grain({"type": "reached_playoffs", "params": {"scope": "tournament"}}),
        )

    def test_is_newcomer_count_mode_is_user_grain(self) -> None:
        self.assertEqual(AchievementGrain.user_tournament, leaf_grain("is_newcomer", {}))
        self.assertEqual(
            AchievementGrain.user,
            leaf_grain("is_newcomer", {"op": ">=", "value": 2}),
        )
        self.assertEqual(
            AchievementGrain.user,
            infer_grain({"type": "is_newcomer", "params": {"op": ">=", "value": 2}}),
        )

    def test_mixed_grains_are_rejected(self) -> None:
        errors = validate_condition_tree(
            {
                "AND": [
                    {"type": "is_captain"},
                    {"type": "match_win"},
                ]
            }
        )
        self.assertTrue(any("mixed result grains" in error for error in errors))

    def test_standing_record_rejects_unknown_field(self) -> None:
        errors = validate_condition_tree(
            {"type": "standing_record", "params": {"field": "not_a_field", "op": "==", "value": 0}}
        )
        self.assertTrue(any("params.field" in error for error in errors))

    def test_log_stat_rank_requires_stat(self) -> None:
        self.assertTrue(validate_condition_tree({"type": "log_stat_rank", "params": {}}))
        self.assertEqual([], validate_condition_tree({"type": "log_stat_rank", "params": {"stat": "Deaths"}}))

    def test_standing_count_requires_op_and_value(self) -> None:
        self.assertTrue(validate_condition_tree({"type": "standing_count", "params": {}}))
        self.assertEqual(
            [],
            validate_condition_tree({"type": "standing_count", "params": {"op": ">=", "value": 2}}),
        )

    def test_every_seeded_rule_is_named_in_both_languages(self) -> None:
        """A rule with no description is a blank card in the UI, not a caught bug."""
        unnamed = [slug for slug, text in _catalog_text().items() if not all(text)]
        self.assertEqual([], unnamed)

    def test_default_seed_covers_the_declared_rules(self) -> None:
        slugs = set(get_default_rule_slugs())
        self.assertTrue(set(_catalog_text()).issubset(slugs))
        # Retired rules stay retired: they live on in workspaces that already
        # have them, but the seed never puts them back.
        for retired in ("welcome", "regular-boar", "my-strength-is-growing", "well-balanced"):
            self.assertNotIn(retired, slugs)


class TournamentFormatTests(TestCase):
    def test_round_robin_detected_from_stage_type(self) -> None:
        self.assertTrue(matches_tournament_format({StageType.ROUND_ROBIN}, "round_robin"))
        self.assertFalse(matches_tournament_format({StageType.ROUND_ROBIN}, "has_bracket"))

    def test_single_elimination_detected_from_stage_type(self) -> None:
        self.assertTrue(matches_tournament_format({StageType.SINGLE_ELIMINATION}, "single_elim"))
        self.assertTrue(matches_tournament_format({StageType.SINGLE_ELIMINATION}, "has_bracket"))
        self.assertFalse(matches_tournament_format({StageType.SINGLE_ELIMINATION}, "double_elim"))

    def test_double_elimination_detected_from_stage_type(self) -> None:
        self.assertTrue(matches_tournament_format({StageType.DOUBLE_ELIMINATION}, "double_elim"))
        self.assertTrue(matches_tournament_format({StageType.DOUBLE_ELIMINATION}, "has_bracket"))
        self.assertFalse(matches_tournament_format({StageType.DOUBLE_ELIMINATION}, "single_elim"))

    def test_swiss_only_is_not_round_robin(self) -> None:
        self.assertFalse(matches_tournament_format({StageType.SWISS}, "round_robin"))
        self.assertFalse(matches_tournament_format({StageType.SWISS}, "has_bracket"))
        self.assertTrue(matches_tournament_format({StageType.ROUND_ROBIN, StageType.SINGLE_ELIMINATION}, "round_robin"))


class DynamicHeroRuleTests(TestCase):
    @staticmethod
    def _hero(hero_id: int, slug: str, name: str, image_path: str = "/img.png") -> SimpleNamespace:
        return SimpleNamespace(id=hero_id, slug=slug, name=name, image_path=image_path)

    def test_db_heroes_generate_kd_rules_with_metadata(self) -> None:
        heroes = [
            self._hero(1, "tracer", "Tracer"),  # known catalog hero
            self._hero(2, "newhero", "New Hero"),  # synced hero not in catalog
            self._hero(3, "freak", "Freak"),  # non-K/D slug → must be skipped
        ]
        rules = {rule.slug: rule for rule in _hero_kd_rules(1, heroes)}

        # Catalog hero keeps its legacy flavour name and gains hero linkage.
        self.assertEqual("Déjà vu", rules["tracer"].name)
        self.assertEqual(1, rules["tracer"].hero_id)
        self.assertEqual("/img.png", rules["tracer"].image_url)
        self.assertEqual(
            {"type": "hero_kd_best", "params": {"hero_slug": "tracer", "min_time": 600, "min_matches": 3}},
            rules["tracer"].condition_tree,
        )

        # Unknown hero gets generic metadata and hero linkage.
        self.assertIn("newhero", rules)
        self.assertEqual("New Hero", rules["newhero"].name)
        self.assertIn("New Hero", rules["newhero"].description_en)
        self.assertEqual(2, rules["newhero"].hero_id)
        self.assertEqual("/img.png", rules["newhero"].image_url)

        # Non-K/D hero slugs never become hero K/D rules.
        self.assertNotIn("freak", rules)

    def test_catalog_heroes_covered_when_missing_from_db(self) -> None:
        # Only one hero in the DB, but every catalog K/D hero must still be covered.
        rules = {rule.slug: rule for rule in _hero_kd_rules(1, [self._hero(1, "tracer", "Tracer")])}
        self.assertIn("dva", rules)  # catalog hero absent from the DB
        self.assertIsNone(rules["dva"].hero_id)

    def test_sync_path_uses_catalog_only(self) -> None:
        rules = {rule.slug: rule for rule in _hero_kd_rules(1, None)}
        self.assertIn("tracer", rules)
        self.assertIsNone(rules["tracer"].hero_id)


class OverrideScopeTests(TestCase):
    def test_global_revoke_matches_any_scope(self) -> None:
        self.assertTrue(override_applies_to_scope(None, None, None, None))
        self.assertTrue(override_applies_to_scope(None, None, 10, None))
        self.assertTrue(override_applies_to_scope(None, None, 10, 501))

    def test_tournament_revoke_matches_tournament_and_match_rows_in_same_tournament(self) -> None:
        self.assertTrue(override_applies_to_scope(10, None, 10, None))
        self.assertTrue(override_applies_to_scope(10, None, 10, 501))
        self.assertFalse(override_applies_to_scope(10, None, 11, None))

    def test_match_revoke_matches_only_exact_match(self) -> None:
        self.assertTrue(override_applies_to_scope(10, 501, 10, 501))
        self.assertFalse(override_applies_to_scope(10, 501, 10, 502))
        self.assertFalse(override_applies_to_scope(10, 501, 10, None))

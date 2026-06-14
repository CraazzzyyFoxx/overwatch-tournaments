from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from shared.core.enums import StageType  # noqa: E402
from shared.models.achievement import AchievementGrain, AchievementRule  # noqa: E402
from shared.services.achievement_effective import override_applies_to_scope  # noqa: E402

from src.services.achievement.engine.conditions import (  # noqa: E402
    get_registered_types,
    resolve_stat_name,
)
from src.services.achievement.engine.conditions.tournament_format import (  # noqa: E402
    matches_tournament_format,
)
from src.services.achievement.engine.differ import EvaluationSlice, diff_and_apply  # noqa: E402
from src.services.achievement.engine.seeder import (  # noqa: E402
    _all_default_rules,
    _hero_kd_rules,
    get_canonical_rule_catalog,
)
from src.services.achievement.engine.validation import (  # noqa: E402
    LEAF_GRAINS,
    infer_grain,
    validate_condition_tree,
)


def _legacy_rule_catalog() -> dict[str, tuple[str, str, str]]:
    catalog: dict[str, tuple[str, str, str]] = {}
    for achievement in get_canonical_rule_catalog():
        catalog[achievement.slug] = (
            achievement.name,
            achievement.description_ru,
            achievement.description_en,
        )
    return catalog


EXPECTED_LEGACY_RULES = _legacy_rule_catalog()


class DiffScopeTests(IsolatedAsyncioTestCase):
    async def test_tournament_scoped_diff_does_not_delete_other_tournament_results(self) -> None:
        rule = AchievementRule(id=7, slug="afgan", rule_version=3)

        async def execute_side_effect(query):
            sql = str(query)
            if "SELECT achievements.evaluation_result.id" in sql:
                if "tournament_id" in sql and "=" in sql:
                    return [
                        (101, 55, 10, None),
                    ]
                return [
                    (101, 55, 10, None),
                    (202, 55, 20, None),
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
            infer_grain(
                {"type": "reached_playoffs", "params": {"scope": "global", "op": "==", "value": 0}}
            ),
        )
        self.assertEqual(
            AchievementGrain.user_tournament,
            infer_grain({"type": "reached_playoffs", "params": {"scope": "tournament"}}),
        )

    def test_log_stat_rank_requires_stat(self) -> None:
        self.assertTrue(validate_condition_tree({"type": "log_stat_rank", "params": {}}))
        self.assertEqual(
            [], validate_condition_tree({"type": "log_stat_rank", "params": {"stat": "Deaths"}})
        )

    def test_standing_count_requires_op_and_value(self) -> None:
        self.assertTrue(validate_condition_tree({"type": "standing_count", "params": {}}))
        self.assertEqual(
            [],
            validate_condition_tree(
                {"type": "standing_count", "params": {"op": ">=", "value": 2}}
            ),
        )

    def test_default_rule_catalog_matches_legacy_consts(self) -> None:
        rules = {rule.slug: rule for rule in _all_default_rules(1)}
        self.assertEqual(sorted(EXPECTED_LEGACY_RULES), sorted(rules))

        metadata_mismatches = [
            (
                slug,
                EXPECTED_LEGACY_RULES[slug],
                (
                    rules[slug].name,
                    rules[slug].description_ru,
                    rules[slug].description_en,
                ),
            )
            for slug in sorted(EXPECTED_LEGACY_RULES)
            if (
                rules[slug].name,
                rules[slug].description_ru,
                rules[slug].description_en,
            ) != EXPECTED_LEGACY_RULES[slug]
        ]
        self.assertEqual([], metadata_mismatches)


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

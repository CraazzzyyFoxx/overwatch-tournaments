"""Workspace seeder for the achievement engine.

The default engine catalog mirrors the migrated legacy metadata from
`engine/catalog.py`.
Rules that do not have engine parity yet are seeded as disabled placeholders
with empty condition trees, so the engine catalog stays complete without
evaluating incomplete logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from loguru import logger
from shared.models.achievement import (
    AchievementCategory,
    AchievementEvaluationResult,
    AchievementGrain,
    AchievementRule,
    AchievementScope,
    EvaluationRun,
    EvaluationRunTrigger,
)
from shared.models.hero import Hero
from sqlalchemy.ext.asyncio import AsyncSession

from .catalog import CANONICAL_ACHIEVEMENT_CATALOG
from .runner import run_evaluation
from .validation import infer_grain

# Fallback flavour text for heroes synced from OW that are not in the legacy catalog.
_GENERIC_HERO_NAME = "{name}"
_GENERIC_HERO_DESC_RU = "Иметь лучшее K/D на {name} за турнир"
_GENERIC_HERO_DESC_EN = "Have the best K/D as {name} during the tournament"


@dataclass(frozen=True, slots=True)
class CanonicalRuleMeta:
    slug: str
    name: str
    description_ru: str
    description_en: str
    category: AchievementCategory


def _build_canonical_rule_catalog() -> list[CanonicalRuleMeta]:
    category_map = {
        "hero": AchievementCategory.hero,
        "overall": AchievementCategory.overall,
        "division": AchievementCategory.division,
        "team": AchievementCategory.team,
        "standing": AchievementCategory.standing,
        "match": AchievementCategory.match,
    }

    catalog: list[CanonicalRuleMeta] = []
    seen_slugs: set[str] = set()
    for item in CANONICAL_ACHIEVEMENT_CATALOG:
        slug = item["slug"]
        if slug in seen_slugs:
            raise ValueError(f"Duplicate achievement slug in canonical catalog: {slug}")
        seen_slugs.add(slug)
        catalog.append(
            CanonicalRuleMeta(
                slug=slug,
                name=item["name"],
                description_ru=item["description_ru"],
                description_en=item["description_en"],
                category=category_map[item["category"]],
            )
        )
    return catalog


_CANONICAL_RULES = _build_canonical_rule_catalog()
_CANONICAL_RULES_BY_SLUG = {rule.slug: rule for rule in _CANONICAL_RULES}

_PLACEHOLDER_DEFAULTS_BY_CATEGORY = {
    AchievementCategory.overall: (AchievementScope.glob, AchievementGrain.user),
    AchievementCategory.hero: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.division: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.team: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.standing: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.match: (AchievementScope.match, AchievementGrain.user_match),
}

_HERO_NON_KD_SLUGS = {"freak", "mystery-heroes", "swiss-knife"}
_HERO_KD_SLUGS = [
    meta.slug
    for meta in _CANONICAL_RULES
    if meta.category == AchievementCategory.hero and meta.slug not in _HERO_NON_KD_SLUGS
]


def _catalog_rule(
    workspace_id: int,
    slug: str,
    *,
    scope: AchievementScope,
    grain: AchievementGrain,
    condition_tree: dict,
    depends_on: list[str] | None = None,
    enabled: bool = True,
    min_tournament_id: int | None = None,
    hero_id: int | None = None,
    image_url: str | None = None,
) -> AchievementRule:
    meta = _CANONICAL_RULES_BY_SLUG[slug]
    return AchievementRule(
        workspace_id=workspace_id,
        slug=meta.slug,
        name=meta.name,
        description_ru=meta.description_ru,
        description_en=meta.description_en,
        category=meta.category,
        scope=scope,
        grain=grain,
        condition_tree=condition_tree,
        depends_on=depends_on or [],
        enabled=enabled,
        min_tournament_id=min_tournament_id,
        hero_id=hero_id,
        image_url=image_url,
    )


def _placeholder_rule(workspace_id: int, slug: str) -> AchievementRule:
    meta = _CANONICAL_RULES_BY_SLUG[slug]
    scope, grain = _PLACEHOLDER_DEFAULTS_BY_CATEGORY[meta.category]
    return _catalog_rule(
        workspace_id,
        slug,
        scope=scope,
        grain=grain,
        condition_tree={},
        depends_on=[],
        enabled=False,
    )


def _hero_kd_condition_tree(slug: str) -> dict:
    return {
        "type": "hero_kd_best",
        "params": {"hero_slug": slug, "min_time": 600, "min_matches": 3},
    }


def _hero_kd_rule_from_db(workspace_id: int, hero: Hero) -> AchievementRule:
    """Build a hero K/D rule for a DB hero, using legacy flavour text when known."""
    meta = _CANONICAL_RULES_BY_SLUG.get(hero.slug)
    name = meta.name if meta else _GENERIC_HERO_NAME.format(name=hero.name)
    description_ru = meta.description_ru if meta else _GENERIC_HERO_DESC_RU.format(name=hero.name)
    description_en = meta.description_en if meta else _GENERIC_HERO_DESC_EN.format(name=hero.name)
    return AchievementRule(
        workspace_id=workspace_id,
        slug=hero.slug,
        name=name,
        description_ru=description_ru,
        description_en=description_en,
        category=AchievementCategory.hero,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree=_hero_kd_condition_tree(hero.slug),
        depends_on=["matches.statistics"],
        enabled=True,
        hero_id=hero.id,
        image_url=hero.image_path,
    )


def _hero_kd_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    """Hero K/D rules.

    When ``heroes`` is provided (during DB-backed seeding), one rule is generated
    per hero in ``overwatch.hero`` — so newly synced heroes automatically get an
    achievement. Catalog flavour text is used when the slug is known, otherwise a
    generic name/description is generated. Catalog heroes missing from the DB still
    get a (catalog-based) rule, so the canonical catalog stays fully covered.

    When ``heroes`` is None (sync callers / tests), only the catalog hero slugs are
    used — preserving backward-compatible, DB-free behaviour.
    """
    rules: list[AchievementRule] = []
    seen: set[str] = set()

    if heroes is not None:
        for hero in heroes:
            if hero.slug in _HERO_NON_KD_SLUGS or hero.slug in seen:
                continue
            rules.append(_hero_kd_rule_from_db(workspace_id, hero))
            seen.add(hero.slug)

    for slug in _HERO_KD_SLUGS:
        if slug in seen:
            continue
        rules.append(
            _catalog_rule(
                workspace_id,
                slug,
                scope=AchievementScope.tournament,
                grain=AchievementGrain.user_tournament,
                condition_tree=_hero_kd_condition_tree(slug),
                depends_on=["matches.statistics"],
            )
        )

    return rules


def _match_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "balanced",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "closeness", "op": "==", "value": 0}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "hard_game",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "closeness", "op": "==", "value": 1}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "7_years_in_azkaban",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "match_time", "op": ">=", "value": 1500}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "fast",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "match_time", "op": "<=", "value": 300}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "friendly",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "Eliminations", "op": "==", "value": 0}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "boris_dick",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "AND": [
                    {"type": "stat_threshold", "params": {"stat": "Deaths", "op": "==", "value": 0}},
                    {"type": "match_win"},
                ]
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "john_wick",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "Eliminations", "op": ">=", "value": 60}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "just_dont_fuck_around",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "Deaths", "op": ">=", "value": 20}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "the-shift-factory-is-done",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "HealingDealt", "op": ">=", "value": 30000}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "shooting_and_screaming",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "HeroDamageDealt", "op": ">=", "value": 35000},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "fiasko",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "EnvironmentalDeaths", "op": ">=", "value": 3},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "boop_master",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "EnvironmentalKills", "op": ">=", "value": 3},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "bullet-is-not-stupid",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "ScopedCriticalHitKills", "op": ">=", "value": 10},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
    ]


def _overall_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "welcome",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 1}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "honor-and-glory",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "standing_position", "params": {"op": "==", "value": 1}},
            depends_on=["tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "versatile-player",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "distinct_count", "params": {"field": "role", "op": ">=", "value": 3, "scope": "global"}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "captain-jack-sparrow",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "is_captain"},
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "worst-player-winrate",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "global_winrate", "params": {"order": "asc", "limit": 20}},
            depends_on=["tournament.player", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "best-player-winrate",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "global_winrate", "params": {"order": "desc", "limit": 20}},
            depends_on=["tournament.player", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "space-created",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "global_stat_sum", "params": {"stat": "Deaths", "op": ">=", "value": 1000}},
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "fucking-casino-mouth",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 20}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "regular-boar",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 30}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "old",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "tournament_count",
                "params": {"op": ">=", "value": 1, "is_league": False, "number_max": 18},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "young-blood",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "tournament_count",
                "params": {"op": ">=", "value": 1, "is_league": False, "number_min": 19},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "backyard-cyber-athlete",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "tournament_count",
                "params": {"op": ">=", "value": 1, "is_league": True},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "well-deserved-anomaly",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "tournament_type", "params": {"is_league": True}},
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                ]
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "its-genetics",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "AND": [
                    {
                        "type": "distinct_count",
                        "params": {"field": "hero", "op": "==", "value": 1, "scope": "global", "min_playtime": 60},
                    },
                    {
                        "type": "distinct_count",
                        "params": {"field": "match", "op": ">", "value": 5, "scope": "global"},
                    },
                ]
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "two-wins-players",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "tournament", "op": ">=", "value": 2},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "three-wins-players",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "tournament", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "sisyphus-and-stone",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 2, "count_by": "tournament", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "dahao",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 2},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "pathological-sucker",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 2, "count_by": "role", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "lord-of-all-the-elements",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "consistent-winner",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "global_winrate",
                "params": {"metric": "won_maps", "order": "desc", "limit": 20},
            },
            depends_on=["tournament.player", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "just-shooting",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {"type": "tournament_winrate", "params": {"op": ">=", "value": 0.89}},
                ]
            },
            depends_on=["tournament.player", "tournament.standing", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "ill-definitely-survive",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "Deaths", "order": "asc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "killer-machine",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "Eliminations", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "just-shoot-in-the-head",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "CriticalHitAccuracy", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "poop_forever",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "HeroDamageDealt", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "one-shot-one-kill",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "ScopedCriticalHitAccuracy", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
    ]


def _division_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "my-strength-is-growing",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "up", "min_shift": 1}},
            depends_on=["analytics.tournament", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "not-good-enough",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "down", "min_shift": 1}},
            depends_on=["analytics.tournament", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "i-need-more-power",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_level", "params": {"op": "<=", "value": 3}},
            depends_on=["analytics.tournament", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "balance-from-anak",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "up", "min_shift": 4}},
            depends_on=["analytics.tournament", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "critical-failure",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "down", "min_shift": 4}},
            depends_on=["analytics.tournament", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "im-fine-with-that",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "stable_streak", "params": {"fields": ["role", "division"], "min_streak": 7}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "my-drill-will-pierce-the-sky",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "div_span", "params": {"op": ">=", "value": 10}},
            depends_on=["analytics.tournament", "tournament.player"],
        ),
    ]


def _standing_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "dirty-smurf",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "is_newcomer"},
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {"type": "tournament_type", "params": {"is_league": False}},
                ]
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "revenge-is-sweet",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "encounter_revenge"},
            depends_on=["tournament.encounter", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "reverse-sweep-champion",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {"type": "bracket_path", "params": {"played_lower_bracket": True}},
                    {"type": "tournament_format", "params": {"format": "double_elim"}},
                ]
            },
            depends_on=["tournament.encounter", "tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "win-2-plus-consecutive",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "consecutive", "params": {"metric": "win", "min_streak": 2}},
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "beginners-are-lucky",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "reached_playoffs", "params": {"scope": "tournament"}},
                    {
                        "type": "team_players_match",
                        "params": {"mode": "any", "condition": {"type": "is_newcomer"}},
                    },
                ]
            },
            depends_on=["tournament.player", "tournament.standing", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "were-not-suckers",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "encounter_score",
                "params": {"scores": [[2, 3], [3, 2]], "round_type": "final", "side": "loser"},
            },
            depends_on=["tournament.encounter", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "to-the-bottom",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_record", "params": {"field": "wins", "op": "==", "value": 0, "groups_only": True}},
                    {"type": "standing_record", "params": {"field": "draws", "op": "==", "value": 0, "groups_only": True}},
                ]
            },
            depends_on=["tournament.standing", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "samurai-has-no-purpose",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "reached_playoffs",
                "params": {"scope": "global", "op": "==", "value": 0},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "the-best-among-the-best",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_record", "params": {"field": "wins", "op": ">=", "value": 5, "groups_only": True}},
                    {"type": "standing_record", "params": {"field": "losses", "op": "==", "value": 0, "groups_only": True}},
                    {"type": "standing_record", "params": {"field": "draws", "op": "==", "value": 0, "groups_only": True}},
                ]
            },
            depends_on=["tournament.standing", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "i-killed-i-stole",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "<=", "value": 2}},
                    {"type": "bracket_path", "params": {"played_lower_bracket": True}},
                ]
            },
            depends_on=["tournament.standing", "tournament.encounter", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "well-balanced",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_record", "params": {"field": "draws", "op": "==", "value": 5, "groups_only": True}},
                    {"type": "standing_record", "params": {"field": "wins", "op": "==", "value": 0, "groups_only": True}},
                    {"type": "standing_record", "params": {"field": "losses", "op": "==", "value": 0, "groups_only": True}},
                ]
            },
            depends_on=["tournament.standing", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "anchor-in-my-throat",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {
                        "type": "team_players_match",
                        "params": {
                            "mode": "any",
                            "condition": {"type": "player_div", "params": {"op": ">=", "value": 20}},
                        },
                    },
                ]
            },
            depends_on=["analytics.tournament", "tournament.player", "tournament.standing", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "five-second-day-streak",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "consecutive", "params": {"metric": "playoffs", "min_streak": 5}},
            depends_on=["tournament.player", "tournament.standing"],
        ),
    ]


def _team_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "accuracy-is-above-all-else",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "team_players_match",
                "params": {
                    "mode": "count",
                    "count_op": ">=",
                    "count_value": 2,
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Damage"}},
                            {"type": "player_sub_role", "params": {"sub_role": "hitscan"}},
                        ]
                    },
                },
            },
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "simple-geometry",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "team_players_match",
                "params": {
                    "mode": "count",
                    "count_op": ">=",
                    "count_value": 2,
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Damage"}},
                            {"type": "player_sub_role", "params": {"sub_role": "projectile"}},
                        ]
                    },
                },
            },
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "no_mercy",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "team_players_match",
                "params": {
                    "mode": "count",
                    "count_op": ">=",
                    "count_value": 2,
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Support"}},
                            {"type": "player_sub_role", "params": {"sub_role": "main_heal"}},
                        ]
                    },
                },
            },
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "heal_for_a_fee",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "team_players_match",
                "params": {
                    "mode": "count",
                    "count_op": ">=",
                    "count_value": 2,
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Support"}},
                            {"type": "player_sub_role", "params": {"sub_role": "light_heal"}},
                        ]
                    },
                },
            },
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "damage-above-5-division",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "captain_property",
                "params": {
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Damage"}},
                            {"type": "player_div", "params": {"op": "<=", "value": 5}},
                        ]
                    }
                },
            },
            depends_on=["analytics.tournament", "tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "tank-above-5-division",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "captain_property",
                "params": {
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Tank"}},
                            {"type": "player_div", "params": {"op": "<=", "value": 5}},
                        ]
                    }
                },
            },
            depends_on=["analytics.tournament", "tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "support-above-5-division",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "captain_property",
                "params": {
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Support"}},
                            {"type": "player_div", "params": {"op": "<=", "value": 5}},
                        ]
                    }
                },
            },
            depends_on=["analytics.tournament", "tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "im-screwed-run",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {
                        "type": "distinct_count",
                        "params": {"field": "hero", "op": "==", "value": 1, "scope": "tournament", "min_playtime": 60},
                    },
                    {
                        "type": "distinct_count",
                        "params": {"field": "match", "op": ">", "value": 5, "scope": "tournament"},
                    },
                ]
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "lfs-4500",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "teammate_recurrence", "params": {"op": ">=", "value": 3}},
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "we-work-with-what-we-have",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "team_otp_count", "params": {"op": ">=", "value": 1}},
            depends_on=["matches.statistics", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "were-so-fucked",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "team_otp_count", "params": {"op": ">=", "value": 3}},
            depends_on=["matches.statistics", "tournament.team"],
        ),
    ]


def _hero_misc_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "freak",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "hero_pickrate", "params": {"op": "<", "value": 0.001}},
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "mystery-heroes",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "distinct_count",
                "params": {"field": "hero", "op": ">=", "value": 7, "scope": "tournament", "min_playtime": 60},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "swiss-knife",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "distinct_count",
                "params": {"field": "hero", "op": ">=", "value": 20, "scope": "global", "min_playtime": 60},
            },
            depends_on=["matches.statistics"],
        ),
    ]


def _implemented_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    return [
        *_match_rules(workspace_id),
        *_overall_rules(workspace_id),
        *_division_rules(workspace_id),
        *_standing_rules(workspace_id),
        *_team_rules(workspace_id),
        *_hero_misc_rules(workspace_id),
        *_hero_kd_rules(workspace_id, heroes),
    ]


def _placeholder_rules(
    workspace_id: int,
    implemented_slugs: set[str],
) -> list[AchievementRule]:
    return [
        _placeholder_rule(workspace_id, meta.slug)
        for meta in _CANONICAL_RULES
        if meta.slug not in implemented_slugs
    ]


def _all_default_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    implemented_rules = _implemented_rules(workspace_id, heroes)
    implemented_slugs = {rule.slug for rule in implemented_rules}
    placeholder_rules = _placeholder_rules(workspace_id, implemented_slugs)
    all_rules = [*implemented_rules, *placeholder_rules]

    seen_slugs: set[str] = set()
    duplicates = [rule.slug for rule in all_rules if rule.slug in seen_slugs or seen_slugs.add(rule.slug)]
    if duplicates:
        raise ValueError(f"Duplicate slugs in default engine catalog: {duplicates}")

    return all_rules


def get_default_rule_slugs() -> list[str]:
    return sorted(rule.slug for rule in _all_default_rules(0))


def get_canonical_rule_catalog() -> list[CanonicalRuleMeta]:
    return list(_CANONICAL_RULES)


async def seed_workspace(
    session: AsyncSession,
    workspace_id: int,
    *,
    replace_catalog: bool = False,
) -> tuple[int, int]:
    """Seed the default achievement catalog for a workspace (upsert).

    If a rule with the same slug already exists in the workspace, its metadata
    and engine definition are updated in place. Legacy engine-only slugs are
    normalized to the canonical legacy slugs before upsert.

    When `replace_catalog=True`, unsupported rules are removed from the
    workspace after alias normalization.

    Hero K/D rules are generated from the live `overwatch.hero` table, so heroes
    synced from OW automatically get an achievement on the next seed.
    """

    heroes = list((await session.execute(sa.select(Hero))).scalars())
    all_rules = _all_default_rules(workspace_id, heroes)
    count = 0
    removed = 0
    supported_slugs = {rule.slug for rule in all_rules}

    existing_rules = list(
        (
            await session.execute(
                sa.select(AchievementRule).where(
                    AchievementRule.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    existing_by_slug = {rule.slug: rule for rule in existing_rules}

    if replace_catalog:
        for existing in existing_rules:
            if existing.slug in supported_slugs:
                continue
            await session.delete(existing)
            removed += 1

    for rule in all_rules:
        if rule.condition_tree:
            inferred_grain = infer_grain(rule.condition_tree)
            if inferred_grain != rule.grain:
                raise ValueError(
                    f"Seed rule '{rule.slug}' has grain '{rule.grain}' but infers '{inferred_grain.value}'"
                )

        existing = existing_by_slug.get(rule.slug)

        if existing:
            existing.condition_tree = rule.condition_tree
            existing.category = rule.category
            existing.scope = rule.scope
            existing.grain = rule.grain
            existing.depends_on = rule.depends_on
            existing.name = rule.name
            existing.description_ru = rule.description_ru
            existing.description_en = rule.description_en
            existing.min_tournament_id = rule.min_tournament_id
            # Only refresh hero linkage when the seed provides it (hero rules),
            # so admin-customised images on other rules are preserved.
            if rule.hero_id is not None:
                existing.hero_id = rule.hero_id
            if rule.image_url is not None:
                existing.image_url = rule.image_url
        else:
            session.add(rule)

        count += 1

    await session.flush()
    logger.info(
        "Seeded workspace {} with {} achievement rules (upsert), removed {}",
        workspace_id,
        count,
        removed
    )
    return count, removed


async def hard_reset_workspace(
    session: AsyncSession,
    workspace_id: int,
) -> tuple[int, int, int, EvaluationRun]:
    seeded, removed = await seed_workspace(
        session,
        workspace_id,
        replace_catalog=True,
    )

    workspace_rule_ids = sa.select(AchievementRule.id).where(
        AchievementRule.workspace_id == workspace_id
    )
    deleted_results = await session.execute(
        sa.delete(AchievementEvaluationResult).where(
            AchievementEvaluationResult.achievement_rule_id.in_(workspace_rule_ids)
        )
    )
    cleared_results = deleted_results.rowcount or 0

    run = await run_evaluation(
        session=session,
        workspace_id=workspace_id,
        trigger=EvaluationRunTrigger.manual,
    )
    logger.info(
        "Hard-reset workspace {}: seeded={}, removed={}, cleared_results={}, run={}",
        workspace_id,
        seeded,
        removed,
        cleared_results,
        run.id,
    )
    return seeded, removed, cleared_results, run

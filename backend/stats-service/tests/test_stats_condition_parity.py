"""Real P3 condition outputs, captured before the native reader cutover.

Main captures ``collect_outputs`` in a parser-only frozen-source process. Tests
only read that immutable oracle; they never regenerate expected values.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared import models
from shared.core.enums import LogStatsName
from shared.core.enums import MatchEvent as MatchEventName
from shared.disciplines.overwatch.achievements import conditions
from shared.disciplines.overwatch.achievements.conditions import log_stat_rank
from shared.disciplines.overwatch.achievements.eligibility import eligible_keys
from shared.domain.achievements.context import EvalContext
from shared.domain.achievements.validation import infer_grain, validate_condition_tree
from shared.models.achievements.achievement import (
    AchievementEvaluationResult,
    AchievementGrain,
    AchievementOverride,
    AchievementRule,
    EvaluationRunTrigger,
)
from shared.services.achievements import evaluator
from src.services.achievement.engine.runner import AchievementEvaluationRunnerService
from src.services.achievement.rule_service import AchievementRuleService

GOLDEN = Path(__file__).parent / "fixtures" / "stats_condition_parity.json"
# Triggers use native storage names; the frozen semantic outputs stay unchanged.
_EVENT_TABLES = ["stats.event"]
_STAT_TABLES = ["stats.fact"]


def _leaf(kind: str, **params: object) -> dict:
    return {"type": kind, "params": params}


def _trees(hero: models.CatalogEntity, support: models.CatalogEntity, map_: models.CatalogEntity) -> dict[str, dict]:
    trees = {
        "aggregate/stat_sum": _leaf("global_stat_sum", stat="hero_damage_dealt", op=">=", value=18000),
        "aggregate/stat_sum_high": _leaf("global_stat_sum", stat="HeroDamageDealt", op=">", value=600000),
        "aggregate/winrate": _leaf("global_winrate", op=">=", value=0.5),
        "aggregate/won_maps": _leaf("global_winrate", metric="won_maps", order="asc", include_league=True),
        "hero/stat": _leaf("hero_stat", hero_slug=hero.slug, stat="HeroDamageDealt", op=">=", value=13500),
        "hero/stat_strict": _leaf("hero_stat", hero_slug=hero.slug, stat="HeroDamageDealt", op=">", value=13500),
        "hero/kd": _leaf("hero_kd_best", hero_slug=hero.slug, min_matches=2, min_time=600, min_match_time=60),
        "hero/kd_support": _leaf(
            "hero_kd_best", hero_slug=support.slug, min_matches=2, min_time=600, min_match_time=60
        ),
        "hero/kd_ineligible": _leaf(
            "hero_kd_best", hero_slug=hero.slug, min_matches=2, min_time=600, min_match_time=8000
        ),
        "hero/pickrate": _leaf("hero_pickrate", op="<", value=0.6),
        "hero/pickrate_rare": _leaf("hero_pickrate", op="<", value=0.001),
        "hero/team_otp": _leaf("team_otp_count", op=">=", value=1),
        "hero/team_otp_many": _leaf("team_otp_count", op=">=", value=2),
        "rank/count_rate": _leaf("log_stat_rank", stat="HeroDamageDealt", limit=2),
        "rank/count_total": _leaf("log_stat_rank", stat="HeroDamageDealt", normalize_by_time=False, limit=2),
        # Include the whole tie group: the old SQL has no secondary row_number key.
        "rank/fraction_ties": _leaf("log_stat_rank", stat="WeaponAccuracy", normalize_by_time=True, limit=100),
        "rank/weighted_rate": _leaf("log_stat_rank", stat="KD", order="asc", limit=2),
        "rank/impact": _leaf("log_stat_rank", stat="ImpactPoints", limit=2),
        "mvp/ascending": _leaf("match_mvp_check", stat="Performance", top_n=1, op=">=", value=1),
        "mvp/descending": _leaf("match_mvp_check", stat="Eliminations", top_n=1, op=">=", value=1),
        "mvp/no_top_player": _leaf("match_mvp_check", stat="Eliminations", top_n=1, op="==", value=0),
        "kill/fights": _leaf("fight_multikill", min_kills=1, op=">=", value=1),
        "kill/multikill": _leaf("fight_multikill", min_kills=2, op=">=", value=1),
        "kill/duel": _leaf("duel_dominance", min_kills=1, min_diff=1, op=">=", value=1),
        "kill/duel_tournament": _leaf("duel_dominance", scope="tournament", min_kills=2, min_diff=2, op=">=", value=1),
        "event/duplicates": _leaf("match_event_count", event="OffensiveAssist", op="==", value=2),
        "event/hero_filter": _leaf("match_event_count", event="OffensiveAssist", hero_slug=hero.slug, op=">=", value=1),
        "match/duration": _leaf("match_criteria", field="match_time", op=">=", value=5400),
        "match/duration_strict": _leaf("match_criteria", field="time", op=">", value=5400),
        "match/closeness": _leaf("match_criteria", field="closeness", op=">=", value=0.5),
        "match/closeness_strict": _leaf("match_criteria", field="closeness", op=">", value=0.5),
        "win/played_and_no_facts": _leaf("match_win"),
        "encounter/winner": _leaf("encounter_result", outcome="win", margin=1, opponent_score=1),
        "encounter/loser": _leaf("encounter_result", outcome="loss"),
        "encounter/comeback": _leaf("encounter_comeback", min_deficit=1),
        "encounter/comeback_high": _leaf("encounter_comeback", min_deficit=100),
        "map/played": _leaf("map_coverage", field="map", op=">=", value=2),
        "map/won": _leaf("map_coverage", field="map", outcome="won", scope="tournament", op=">=", value=1),
        "map/modes": _leaf("map_coverage", field="gamemode", scope="tournament", op=">=", value=1),
        "map/winrate": _leaf("map_winrate", map_name=map_.name, min_matches=1, op=">=", value=0.5),
        "map/winrate_sample": _leaf("map_winrate", map_name=map_.name, min_matches=100, op=">=", value=0.5),
        "threshold/exact": _leaf("stat_threshold", stat="HeroDamageDealt", op="==", value=18000),
        "threshold/strict": _leaf("stat_threshold", stat="HeroDamageDealt", op=">", value=18000),
    }
    for stat in LogStatsName:
        trees[f"threshold/code/{stat.value}"] = _leaf("stat_threshold", stat=stat.value, op=">=", value=0)
    for field in ("hero", "match", "role"):
        for scope in ("global", "tournament"):
            params = {"field": field, "scope": scope, "op": ">=", "value": 1}
            if field == "hero":
                params["min_playtime"] = 6000
            trees[f"aggregate/distinct/{field}/{scope}"] = _leaf("distinct_count", **params)
    for event in MatchEventName:
        trees[f"event/{event.value}"] = _leaf("match_event_count", event=event.name, op=">=", value=1)
    for scope in ("global", "tournament"):
        for status in ("done", "pending", "any"):
            trees[f"upload/{scope}/{status}"] = _leaf("log_upload_count", scope=scope, status=status, op=">=", value=1)
    for metric in ("series_reported", "map_reports", "map_codes", "readiness"):
        for minimum in (1, 2):
            trees[f"participation/{metric}/{minimum}"] = _leaf(
                "captain_report_activity", metric=metric, op=">=", value=minimum
            )
    trees["tree/winner_with_damage"] = {"AND": [trees["win/played_and_no_facts"], trees["threshold/strict"]]}
    trees["tree/kill_or_event"] = {"OR": [trees["kill/fights"], trees["event/duplicates"]]}
    trees["tree/not_winner"] = {"NOT": trees["win/played_and_no_facts"]}
    return trees


async def _evaluate(session: AsyncSession, tree: dict, context: EvalContext) -> dict:
    errors = validate_condition_tree(tree, discipline="overwatch")
    assert not errors, errors
    keys = await evaluator.evaluate(session, tree, context)
    return {
        "grain": infer_grain(tree, discipline="overwatch").value,
        "keys": [list(key) for key in sorted(keys)],
        # Keep evidence for non-surviving AND/NOT keys too: it is an actual
        # evaluator side channel, not a value invented by the capture.
        "evidence": [{"key": list(key), "value": value} for key, value in sorted(context.evidence.items())],
    }


async def _stored_state(session: AsyncSession, workspace_id: int) -> dict:
    result = AchievementEvaluationResult
    override = AchievementOverride
    result_rows = (
        (
            await session.execute(
                sa.select(
                    AchievementRule.slug.label("rule"),
                    models.WorkspaceMember.player_id.label("player_id"),
                    result.workspace_member_id,
                    result.tournament_id,
                    result.encounter_id,
                    result.match_id,
                    result.rule_version,
                    result.evidence_json,
                )
                .join(AchievementRule, AchievementRule.id == result.achievement_rule_id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == result.workspace_member_id)
                .where(AchievementRule.workspace_id == workspace_id)
                .order_by(
                    AchievementRule.slug,
                    result.workspace_member_id,
                    result.tournament_id,
                    result.encounter_id,
                    result.match_id,
                )
            )
        )
        .mappings()
        .all()
    )
    override_rows = (
        (
            await session.execute(
                sa.select(
                    AchievementRule.slug.label("rule"),
                    override.workspace_member_id,
                    override.tournament_id,
                    override.match_id,
                    override.action,
                    override.reason,
                    override.granted_by,
                )
                .join(AchievementRule, AchievementRule.id == override.achievement_rule_id)
                .where(AchievementRule.workspace_id == workspace_id)
                .order_by(
                    AchievementRule.slug,
                    override.workspace_member_id,
                    override.tournament_id,
                    override.match_id,
                    override.action,
                )
            )
        )
        .mappings()
        .all()
    )
    return {"results": [dict(row) for row in result_rows], "overrides": [dict(row) for row in override_rows]}


async def _runner_outputs(session: AsyncSession, ids: dict[str, int], trees: dict[str, dict]) -> dict:
    runner = AchievementEvaluationRunnerService()
    service = AchievementRuleService()
    # Updating a disabled rule exercises real dependency derivation without
    # sending a deferred manual run to RabbitMQ. parse_complete runs inline.
    rule = await service.update_rule(
        session,
        workspace_id=ids["workspace"],
        rule_id=ids["rule"],
        update_data={
            "enabled": False,
            "grain": "user_match",
            "condition_tree": trees["threshold/strict"],
            "depends_on": ["not.a.real_dependency"],
        },
    )
    rule.enabled = True
    await session.flush()
    output = {"before": await _stored_state(session, ids["workspace"])}

    async def run(rule_ids: list[int], changed_tables: list[str]) -> dict:
        run = await runner.run_evaluation(
            session,
            ids["workspace"],
            EvaluationRunTrigger.parse_complete,
            tournament_id=ids["tournament"],
            changed_tables=changed_tables,
            rule_ids=rule_ids,
        )
        assert run.status == "done", run.error_message
        return {
            "status": run.status,
            "rules_evaluated": run.rules_evaluated,
            "results_created": run.results_created,
            "results_removed": run.results_removed,
            "error_message": run.error_message,
            "state": await _stored_state(session, ids["workspace"]),
        }

    output["stats_changed"] = await run([rule.id], _STAT_TABLES)
    revoke = await service.create_override(
        session,
        AchievementOverride(
            achievement_rule_id=rule.id,
            workspace_member_id=ids["member"],
            tournament_id=ids["tournament"],
            match_id=ids["match"],
            action="revoke",
            reason="P4 parity revoke",
            granted_by=ids["auth_user"],
        ),
    )
    output["with_revoke"] = await run([rule.id], _STAT_TABLES)
    event_rules = []
    for slug, name in (("p4-kill", "kill/fights"), ("p4-event", "event/duplicates"), ("p4-both", "tree/kill_or_event")):
        created = await service.create_rule(
            session,
            workspace_id=ids["workspace"],
            rule_data={
                "slug": slug,
                "name": slug,
                "description_ru": slug,
                "description_en": slug,
                "discipline": "overwatch",
                "category": "match",
                "scope": "match",
                "grain": "user_match",
                "condition_tree": trees[name],
                "depends_on": ["not.a.real_dependency"],
            },
        )
        event_rules.append(created.id)
    output["events_changed"] = await run(event_rules, _EVENT_TABLES)
    output["events_changed_again"] = await run(event_rules, _EVENT_TABLES)
    output["unrelated_change"] = await run(event_rules, ["catalog.alias_miss"])
    rule.condition_tree = _leaf("stat_threshold", stat="HeroDamageDealt", op=">", value=1e12)
    await session.flush()
    output["no_longer_qualified"] = await run([rule.id], _STAT_TABLES)
    await service.delete_override(session, revoke)
    output["revoke_deleted"] = await _stored_state(session, ids["workspace"])
    return output


async def _condition_outputs(session: AsyncSession, ids: dict[str, int]) -> dict:
    """Read condition families without changing the shared fixture."""
    hero = await session.get(models.CatalogEntity, ids["hero"])
    support = await session.get(models.CatalogEntity, ids["hero_other"])
    map_ = await session.get(models.CatalogEntity, ids["map"])
    assert hero is not None and support is not None and map_ is not None
    trees = _trees(hero, support, map_)
    scopes = (
        ("workspace", ids["workspace"], None),
        ("tournament", ids["workspace"], ids["tournament"]),
        ("hidden", ids["workspace"], ids["tournament_hidden"]),
        ("foreign_workspace", ids["workspace_other"], ids["tournament_other"]),
    )
    output = {"trees": trees, "scopes": {}}
    for label, workspace_id, tournament_id in scopes:
        tournament = await session.get(models.Tournament, tournament_id) if tournament_id is not None else None
        values = {}
        for name, tree in trees.items():
            values[name] = await _evaluate(
                session, tree, EvalContext(workspace_id=workspace_id, discipline="overwatch", tournament=tournament)
            )
        eligible = {}
        for grain in AchievementGrain:
            keys = await eligible_keys(
                session, EvalContext(workspace_id=workspace_id, discipline="overwatch", tournament=tournament), grain
            )
            eligible[grain.value] = [list(key) for key in sorted(keys)]
        context = EvalContext(workspace_id=workspace_id, discipline="overwatch", tournament=tournament)
        rank_values = {}
        for name, query in (
            (
                "count_rate",
                log_stat_rank._count_query(
                    conditions.resolve_stat_name("HeroDamageDealt"), context, normalize_by_time=True
                ),
            ),
            (
                "count_total",
                log_stat_rank._count_query(
                    conditions.resolve_stat_name("HeroDamageDealt"), context, normalize_by_time=False
                ),
            ),
            ("fraction", log_stat_rank._fraction_query(conditions.resolve_stat_name("WeaponAccuracy"), context)),
            ("weighted_rate", log_stat_rank._time_weighted_rate_query(conditions.resolve_stat_name("KD"), context)),
        ):
            rows = (await session.execute(query)).mappings().all()
            rank_values[name] = sorted(
                (dict(row) for row in rows), key=lambda row: (row["user_id"], row["tournament_id"])
            )
        output["scopes"][label] = {"conditions": values, "eligible": eligible, "rank_values": rank_values}
    # At least one genuine nonempty result in every required family. Missing
    # shared seed additions must fail capture, never become an empty oracle.
    primary = output["scopes"]["tournament"]["conditions"]
    for name in ("hero/team_otp", "match/closeness", "encounter/comeback", "kill/fights", "event/duplicates"):
        assert primary[name]["keys"], f"shared fixture does not exercise {name}"
    for metric in ("series_reported", "map_reports", "map_codes", "readiness"):
        assert primary[f"participation/{metric}/1"]["keys"], f"missing shared participation fixture: {metric}"
    return output


async def collect_outputs(session: AsyncSession, ids: dict[str, int]) -> dict:
    """Execute real SQL and real runner writes in Main's private capture clone."""
    output = await _condition_outputs(session, ids)
    output["runner"] = await _runner_outputs(session, ids, output["trees"])
    return output


async def assert_condition_golden(session: AsyncSession, ids: dict[str, int], actual: dict) -> None:
    # The collector itself must also import under frozen P3; its native-only
    # numerical proof is intentionally loaded only at the assertion boundary.
    from tests.stats_condition_numeric_parity import assert_condition_golden as assert_native

    await assert_native(session, ids, actual)


def test_native_conditions_preserve_frozen_keys_values_and_overrides(stats_parity_database):
    url, ids = stats_parity_database

    async def compare() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await assert_condition_golden(session, ids, await collect_outputs(session, ids))
        finally:
            await engine.dispose()

    asyncio.run(compare())


def test_overwatch_conditions_ignore_same_code_native_lol_rows(stats_parity_database):
    from shared.testing.stats_parity import seed_native_sentinel

    url, ids = stats_parity_database

    async def compare() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                before = await _condition_outputs(session, ids)
                await session.run_sync(lambda sync: seed_native_sentinel(sync.connection(), ids))
                # Add the other former event family and every uploader lifecycle
                # on that same LoL owner, not just a kill/stat-only sentinel.
                event_type = models.EventType(
                    discipline="lol",
                    code=MatchEventName.OffensiveAssist.value,
                    name="Offensive assist",
                    active=True,
                )
                session.add(event_type)
                await session.flush()
                for _ in range(2):
                    session.add(
                        models.StatsEvent(
                            match_id=ids["match_lol"],
                            segment=0,
                            t=12.0,
                            type_id=event_type.id,
                            actor_member_id=ids["member"],
                            actor_team_id=ids["encounter_team_lol_home"],
                            entity_id=ids["hero_lol"],
                        )
                    )
                job_table = models.IngestJob.__table__
                source = dict(
                    (await session.execute(sa.select(job_table).where(job_table.c.id == ids["record"])))
                    .mappings()
                    .one()
                )
                for status in models.IngestJobStatus:
                    values = dict(source)
                    values.pop("id")
                    values.update(
                        discipline="lol",
                        external_id=f"p4-condition-lol-{status.value}",
                        hint_tournament_id=ids["tournament_lol"],
                        hint_encounter_id=ids["encounter_lol"],
                        hint_encounter_game_id=ids["game_lol"],
                        status=status,
                    )
                    await session.execute(sa.insert(job_table).values(**values))
                await session.commit()
                after = await _condition_outputs(session, ids)
                # Generic universes are not silently redefined as OW-only.
                # These are the real OW condition and aggregate outcomes.
                for scope in before["scopes"]:
                    assert before["scopes"][scope]["conditions"] == after["scopes"][scope]["conditions"]
                    assert before["scopes"][scope]["rank_values"] == after["scopes"][scope]["rank_values"]
                    assert (
                        before["scopes"][scope]["eligible"]["user_match"]
                        == after["scopes"][scope]["eligible"]["user_match"]
                    )
        finally:
            await engine.dispose()

    asyncio.run(compare())


def test_native_reference_mutations_are_atomic_bounded_and_idempotent(stats_parity_database):
    """A real runner/import/seed/reset lifecycle records every reference change."""
    from dataclasses import replace
    from unittest.mock import AsyncMock, patch

    from shared.models.platform.audit import AuditLog
    from shared.repository.support import AchievementEvaluationResultRepository, AchievementRuleRepository
    from shared.services.stats_evidence import validate_transition
    from src.services.achievement.engine.seeder import AchievementSeederService
    from src.services.achievement.import_export import PortableAchievementRule, import_portable_rules

    url, ids = stats_parity_database

    async def exercise() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                initial_audit = await session.scalar(sa.select(sa.func.max(AuditLog.id))) or 0
                service = AchievementRuleService()
                rule = await service.create_rule(
                    session,
                    workspace_id=ids["workspace"],
                    rule_data={
                        "slug": "p4-series-evidence",
                        "name": "Series evidence",
                        "description_ru": "Series",
                        "description_en": "Series",
                        "discipline": "overwatch",
                        "category": "tournament",
                        "scope": "tournament",
                        "grain": "user_encounter",
                        "enabled": False,
                        "condition_tree": _leaf("encounter_result", outcome="win"),
                        "depends_on": ["untrusted.client.input"],
                    },
                )
                assert rule.depends_on == ["tournament.encounter", "tournament.player", "tournament.stage"]
                rule.enabled = True
                await session.flush()
                runner = AchievementEvaluationRunnerService()
                run = await runner.run_evaluation(
                    session,
                    ids["workspace"],
                    EvaluationRunTrigger.parse_complete,
                    tournament_id=ids["tournament"],
                    rule_ids=[rule.id],
                    changed_tables=["tournament.encounter"],
                )
                assert run.status == "done"
                stored = (
                    (
                        await session.execute(
                            sa.select(AchievementEvaluationResult).where(
                                AchievementEvaluationResult.achievement_rule_id == rule.id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert stored
                assert any(row.encounter_id == ids["encounter"] for row in stored)
                assert all(row.encounter_id is not None and row.match_id is None for row in stored)
                member_ids = {row.workspace_member_id for row in stored}
                # Frozen official slot scores are 1:2, independently of parsed-log scores.
                assert member_ids == {ids["member_away"]}
                assert all("winner_score" in row.evidence_json for row in stored)
                result_ids = {row.id for row in stored}
                run_id = run.id
                audited_before_repeat = await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.action == "stats.reference_update",
                    )
                )
                repeat = await runner.run_evaluation(
                    session,
                    ids["workspace"],
                    EvaluationRunTrigger.parse_complete,
                    tournament_id=ids["tournament"],
                    rule_ids=[rule.id],
                    changed_tables=["tournament.encounter"],
                )
                assert (repeat.results_created, repeat.results_removed) == (0, 0)
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(AuditLog)
                        .where(
                            AuditLog.action == "stats.reference_update",
                        )
                    )
                    == audited_before_repeat
                )

                # A repository update and its evidence must roll back together.
                original_dependencies = list(rule.depends_on)
                await AchievementRuleRepository().update_fields(session, rule, {"depends_on": ["stats.event"]})
                await session.rollback()
                await session.refresh(rule)
                assert rule.depends_on == original_dependencies
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(AuditLog)
                        .where(
                            AuditLog.action == "stats.reference_update",
                        )
                    )
                    == audited_before_repeat
                )

                workspace = await session.get(models.Workspace, ids["workspace"])
                source_workspace = await session.get(models.Workspace, ids["workspace_other"])
                copied_image = f"https://cdn/assets/achievements/{workspace.slug}/p4-series-evidence.webp"
                payload = PortableAchievementRule(
                    slug=rule.slug,
                    name="Imported native rule",
                    description_ru="RU",
                    description_en="EN",
                    image_url=f"https://cdn/assets/achievements/{source_workspace.slug}/series.webp",
                    discipline="overwatch",
                    entity_id=ids["hero"],
                    category="match",
                    scope="match",
                    grain="user_match",
                    condition_tree={
                        "OR": [
                            _leaf("fight_multikill"),
                            _leaf(
                                "match_event_count",
                                event="OffensiveAssist",
                                op=">=",
                                value=1,
                            ),
                        ]
                    },
                    depends_on=["untrusted.export"],
                    enabled=False,
                    rule_version=2,
                    min_tournament_id=None,
                )
                new_payload = replace(
                    payload,
                    slug="p4-import-new",
                    image_url=None,
                    entity_id=None,
                    condition_tree=_leaf("match_win"),
                )
                with patch(
                    "src.services.achievement.import_export.copy_workspace_achievement_image",
                    AsyncMock(return_value=(copied_image, None)),
                ):
                    imported = await import_portable_rules(
                        session,
                        object(),
                        target_workspace=workspace,
                        rules=[payload, new_payload],
                        source_workspace=source_workspace,
                    )
                await session.commit()
                assert imported == {"created": 1, "updated": 1, "warnings": []}
                assert rule.image_url == copied_image and rule.entity_id == ids["hero"]
                assert rule.depends_on == ["stats.event", "stats.match", "tournament.encounter"]
                override = await service.create_override(
                    session,
                    AchievementOverride(
                        achievement_rule_id=rule.id,
                        workspace_member_id=ids["member"],
                        tournament_id=ids["tournament"],
                        match_id=ids["match"],
                        action="grant",
                        reason="Native reference lifecycle",
                        granted_by=ids["auth_user"],
                    ),
                )
                override_id = override.id
                # More than one evidence chunk, including duplicates within and
                # across chunks: PostgreSQL's functional conflict index is the oracle.
                values = [
                    {
                        "achievement_rule_id": rule.id,
                        "workspace_member_id": ids["member"],
                        "tournament_id": ids["tournament"],
                        "encounter_id": None,
                        "match_id": ids["match"],
                        "run_id": run_id,
                        "rule_version": rule.rule_version,
                        "evidence_json": {"rule_slug": rule.slug},
                    }
                ] * 201
                result_repo = AchievementEvaluationResultRepository()
                await result_repo.bulk_upsert_ignore_conflicts(session, values)
                await result_repo.bulk_upsert_ignore_conflicts(session, values)
                bulk_results = list(
                    await session.scalars(
                        sa.select(AchievementEvaluationResult.id).where(
                            AchievementEvaluationResult.achievement_rule_id == rule.id,
                            AchievementEvaluationResult.match_id == ids["match"],
                        )
                    )
                )
                assert len(bulk_results) == 1
                result_ids.update(bulk_results)
                rule_id = rule.id
                await service.delete_rule(session, workspace_id=rule.workspace_id, rule_id=rule_id)
                assert await session.get(AchievementOverride, override_id, populate_existing=True) is None
                assert not list(
                    await session.scalars(
                        sa.select(AchievementEvaluationResult.id).where(
                            AchievementEvaluationResult.id.in_(result_ids),
                        )
                    )
                )

                # Seeding runs real repository paths and derives dependencies on
                # every upsert; no client arrays or seeded old-table aliases.
                seeder = AchievementSeederService()
                seeded, _ = await seeder.seed_workspace(session, ids["workspace"], discipline="overwatch")
                assert seeded > 0
                seeded_audit_count = await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.action == "stats.reference_update",
                    )
                )
                assert (await seeder.seed_workspace(session, ids["workspace"], discipline="overwatch"))[0] == seeded
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(AuditLog)
                        .where(
                            AuditLog.action == "stats.reference_update",
                        )
                    )
                    == seeded_audit_count
                )
                seeded_rule_id = await session.scalar(
                    sa.select(AchievementRule.id)
                    .where(
                        AchievementRule.workspace_id == ids["workspace"],
                        AchievementRule.grain == "user_match",
                        AchievementRule.slug == "balanced",
                    )
                    .order_by(AchievementRule.id)
                    .limit(1)
                )
                await result_repo.bulk_upsert_ignore_conflicts(
                    session,
                    [
                        dict(values[0], achievement_rule_id=seeded_rule_id),
                    ],
                )
                workspace.verification_status = "verified"
                await session.flush()
                _, _, cleared, reset_run = await seeder.hard_reset_workspace(
                    session, ids["workspace"], discipline="overwatch"
                )
                assert cleared >= 1
                assert reset_run.status == "done", reset_run.error_message

                audits = list(
                    await session.scalars(
                        sa.select(AuditLog)
                        .where(
                            AuditLog.id > initial_audit,
                            AuditLog.action == "stats.reference_update",
                        )
                        .order_by(AuditLog.id)
                    )
                )
                transitions = set()
                for audit in audits:
                    before = audit.before_json["stats_evidence"]["states"]
                    after = audit.after_json["stats_evidence"]["states"]
                    assert 1 <= len(before) <= 100
                    assert validate_transition(
                        "stats.reference_update",
                        before,
                        after,
                        before_values=audit.before_json["stats_values"],
                        after_values=audit.after_json["stats_values"],
                    )
                    for old, new in zip(before, after, strict=True):
                        transitions.add(
                            (old["owner_kind"], tuple(old["owner_key"]), old["owner_exists"], new["owner_exists"])
                        )
                for kind, row_ids in (("rule", {rule_id}), ("override", {override_id}), ("evaluation", result_ids)):
                    for row_id in row_ids:
                        assert (kind, (row_id,), False, True) in transitions
                        assert (kind, (row_id,), True, False) in transitions
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_diff_resolves_global_identity_to_one_scoped_member(stats_parity_database):
    """Real PostgreSQL replaces the former compiled-SQL/fake-session tests."""
    from shared.models.platform.audit import AuditLog
    from src.services.achievement.engine.differ import diff_and_apply

    url, ids = stats_parity_database

    async def exercise() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rule = await AchievementRuleService().create_rule(
                    session,
                    workspace_id=ids["workspace"],
                    rule_data={
                        "slug": "p4-member-resolution",
                        "name": "Member resolution",
                        "description_ru": "RU",
                        "description_en": "EN",
                        "discipline": "overwatch",
                        "category": "tournament",
                        "scope": "tournament",
                        "grain": "user_tournament",
                        "enabled": False,
                        "condition_tree": _leaf("log_upload_count", scope="tournament", op=">=", value=1),
                    },
                )
                run = await AchievementEvaluationRunnerService().run_evaluation(
                    session,
                    ids["workspace"],
                    EvaluationRunTrigger.parse_complete,
                    tournament_id=ids["tournament"],
                    rule_ids=[rule.id],
                    changed_tables=["stats.ingest_job"],
                )
                assert run.status == "done"
                results = {
                    (ids["player_no_member"], ids["tournament"]),
                    (ids["player_no_member"], ids["tournament_hidden"]),
                    (ids["player"], ids["tournament"]),
                }
                member_audits = await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.action == "stats.member_create",
                    )
                )
                first = await diff_and_apply(session, rule, results, run.id)
                await session.commit()
                assert len(first.to_insert) == 3 and not first.to_delete
                members = list(
                    await session.scalars(
                        sa.select(models.WorkspaceMember).where(
                            models.WorkspaceMember.workspace_id == ids["workspace"],
                            models.WorkspaceMember.player_id == ids["player_no_member"],
                        )
                    )
                )
                assert len(members) == 1
                rows = list(
                    await session.scalars(
                        sa.select(AchievementEvaluationResult).where(
                            AchievementEvaluationResult.achievement_rule_id == rule.id,
                        )
                    )
                )
                assert {(row.workspace_member_id, row.tournament_id) for row in rows} == {
                    (members[0].id, ids["tournament"]),
                    (members[0].id, ids["tournament_hidden"]),
                    (ids["member"], ids["tournament"]),
                }
                assert all(row.workspace_member_id != ids["member_other"] for row in rows)
                repeated = await diff_and_apply(session, rule, results, run.id)
                assert repeated.to_insert == [] and repeated.to_delete == []
                deleted = await diff_and_apply(session, rule, set(), run.id)
                await session.commit()
                assert not deleted.to_insert and len(deleted.to_delete) == 3
                assert not list(
                    await session.scalars(
                        sa.select(AchievementEvaluationResult.id).where(
                            AchievementEvaluationResult.achievement_rule_id == rule.id,
                        )
                    )
                )
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(AuditLog)
                        .where(
                            AuditLog.action == "stats.member_create",
                        )
                    )
                    == member_audits + 1
                )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_runner_preserves_unknown_series_awards_without_freezing_other_rules(stats_parity_database):
    """Unknown chronology cannot grant/revoke awards, even after NOT composition."""
    url, ids = stats_parity_database

    async def exercise() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rules = []
                for slug, tree in (
                    ("history-comeback", _leaf("encounter_comeback", min_deficit=1)),
                    ("history-not-comeback", {"NOT": _leaf("encounter_comeback", min_deficit=1)}),
                    ("history-winner", _leaf("encounter_result", outcome="win")),
                ):
                    rules.append(
                        await AchievementRuleService().create_rule(
                            session,
                            workspace_id=ids["workspace"],
                            rule_data={
                                "slug": slug,
                                "name": slug,
                                "description_ru": "RU",
                                "description_en": "EN",
                                "discipline": "overwatch",
                                "category": "tournament",
                                "scope": "tournament",
                                "grain": "user_encounter",
                                "enabled": True,
                                "condition_tree": tree,
                            },
                        )
                    )
                comeback, negated, ordinary = rules
                runner = AchievementEvaluationRunnerService()
                run = await runner.run_evaluation(
                    session,
                    ids["workspace"],
                    EvaluationRunTrigger.parse_complete,
                    rule_ids=[rule.id for rule in rules],
                )
                assert run.status == "done"
                table = AchievementEvaluationResult.__table__

                async def awards(rule_id, encounter_id):
                    return [
                        dict(row)
                        for row in (
                            await session.execute(
                                sa.select(table)
                                .where(
                                    table.c.achievement_rule_id == rule_id,
                                    table.c.encounter_id == encounter_id,
                                )
                                .order_by(table.c.id)
                            )
                        ).mappings()
                    ]

                preserved = await awards(comeback.id, ids["encounter"])
                assert len(preserved) == 1
                assert preserved[0]["workspace_member_id"] == ids["member_away"]
                assert preserved[0]["evidence_json"]["max_deficit"] == 3
                # This different, fully bound series has a one-map deficit.
                assert len(await awards(comeback.id, ids["encounter_hidden"])) == 1
                assert await awards(negated.id, ids["encounter"])
                assert await awards(ordinary.id, ids["encounter"])
                await session.execute(
                    sa.update(models.StatsMatch)
                    .where(models.StatsMatch.id == ids["match"])
                    .values(encounter_game_id=None)
                )
                # No prior NOT award must not become a new award on missing order.
                # The ordinary winner must still be awarded in this same run.
                await session.execute(
                    sa.delete(table).where(
                        table.c.achievement_rule_id.in_([negated.id, ordinary.id]),
                        table.c.encounter_id == ids["encounter"],
                    )
                )
                comeback.condition_tree = _leaf("encounter_comeback", min_deficit=2)
                await session.commit()

                run = await runner.run_evaluation(
                    session,
                    ids["workspace"],
                    EvaluationRunTrigger.parse_complete,
                    rule_ids=[rule.id for rule in rules],
                )
                assert run.status == "partial"
                assert run.rules_evaluated == 3
                # Includes id, qualified_at, original run_id, version and evidence.
                assert await awards(comeback.id, ids["encounter"]) == preserved
                assert await awards(negated.id, ids["encounter"]) == []
                ordinary_awards = await awards(ordinary.id, ids["encounter"])
                assert len(ordinary_awards) == 1
                assert ordinary_awards[0]["workspace_member_id"] == ids["member_away"]
                assert str(ordinary_awards[0]["run_id"]) == str(run.id)
                assert await awards(comeback.id, ids["encounter_hidden"]) == []

                # A later known-order evaluation reconciles the held row normally.
                await session.execute(
                    sa.update(models.StatsMatch)
                    .where(models.StatsMatch.id == ids["match"])
                    .values(encounter_game_id=ids["game"])
                )
                comeback.condition_tree = _leaf("encounter_comeback", min_deficit=100)
                await session.commit()
                run = await runner.run_evaluation(
                    session,
                    ids["workspace"],
                    EvaluationRunTrigger.parse_complete,
                    rule_ids=[comeback.id],
                )
                assert run.status == "done"
                assert await awards(comeback.id, ids["encounter"]) == []
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_weighted_rank_reduction_is_stable_across_scopes_and_join_plans(stats_parity_database):
    """The native arithmetic order comes from immutable observations, not a query plan."""
    from collections import defaultdict

    from shared.repository.stats_queries import player_facts

    url, ids = stats_parity_database

    async def exercise() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rate = player_facts(discipline="overwatch")
                time = rate.alias("rank_time_operand")
                operands = (
                    await session.execute(
                        sa.select(
                            rate.c.player_id,
                            rate.c.tournament_id,
                            rate.c.value,
                            time.c.value.label("playtime"),
                        )
                        .select_from(rate)
                        .join(
                            time,
                            sa.and_(
                                time.c.match_id == rate.c.match_id,
                                time.c.workspace_member_id == rate.c.workspace_member_id,
                                time.c.encounter_team_id == rate.c.encounter_team_id,
                                time.c.segment == 0,
                                time.c.entity_id.is_(None),
                                time.c.stat_code == "hero_time_played",
                            ),
                        )
                        .where(
                            rate.c.workspace_id == ids["workspace"],
                            rate.c.stat_code == "kd",
                            rate.c.segment == 0,
                            rate.c.entity_id.is_(None),
                        )
                        .order_by(rate.c.match_id, rate.c.workspace_member_id)
                    )
                ).all()
                totals = defaultdict(lambda: [0.0, 0.0])
                for row in operands:
                    totals[row.player_id, row.tournament_id][0] += row.value * row.playtime
                    totals[row.player_id, row.tournament_id][1] += row.playtime
                expected = {
                    key: (numerator / denominator).hex() if denominator else None
                    for key, (numerator, denominator) in totals.items()
                }
                tournament = await session.get(models.Tournament, ids["tournament"])
                for hash_join in ("on", "off"):
                    await session.execute(sa.text(f"SET LOCAL enable_hashjoin = {hash_join}"))
                    for scoped_tournament in (None, tournament):
                        context = EvalContext(
                            workspace_id=ids["workspace"], discipline="overwatch", tournament=scoped_tournament
                        )
                        rows = (await session.execute(log_stat_rank._time_weighted_rate_query("kd", context))).all()
                        actual = {
                            (row.user_id, row.tournament_id): row.metric.hex() if row.metric is not None else None
                            for row in rows
                        }
                        scoped_expected = {
                            key: value
                            for key, value in expected.items()
                            if scoped_tournament is None or key[1] == scoped_tournament.id
                        }
                        assert actual == scoped_expected
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_weighted_numeric_proof_rejects_one_ulp_and_nonmetric_changes():
    """An operation-derived bound is not permission to alter measured values."""
    import math

    import pytest

    from tests.stats_condition_numeric_parity import _prove, _strict

    pool = [(1, 2, 3, 4, 5, "kd", "hero_time_played", (1.0).hex(), (2.0).hex(), (2.0).hex(), 6)]
    group = {
        "operand_indices": [0],
        "numerator_hex": (2.0).hex(),
        "denominator_hex": (2.0).hex(),
        "metric_hex": (1.0).hex(),
    }
    _prove(group, pool, 2.0, 2.0, 1.0, native_operands=pool)
    # Both native stat rows may agree on the wrong participant. Their member,
    # source team, raw bits and arithmetic are unchanged, but this is not parity.
    altered_participant = [(*pool[0][:-1], 7)]
    with pytest.raises(AssertionError, match="Weighted operands or owners differ"):
        _prove(group, pool, 2.0, 2.0, 1.0, native_operands=altered_participant)
    for index in range(3):
        altered = [2.0, 2.0, 1.0]
        altered[index] = math.nextafter(altered[index], math.inf)
        with pytest.raises(AssertionError):
            _prove(group, pool, *altered, native_operands=pool)
    altered_operand = (*pool[0][:7], math.nextafter(1.0, math.inf).hex(), *pool[0][8:])
    with pytest.raises(AssertionError):
        _prove(group, [altered_operand], 2.0, 2.0, 1.0, native_operands=pool)
    for field in ("rank", "threshold", "evidence", "runner", "metadata"):
        with pytest.raises(AssertionError):
            _strict({field: 1.0}, {field: math.nextafter(1.0, math.inf)})

"""App-only P4 floating-reduction proof; the frozen output golden never changes.

Allowed raw paths are hero_compare_raw.values[*][2], witnessed user/tournament
hero_statistics[*][2,4], and global_hero_records[*][3]. Nine regular-comparison
leaves have a separate, explicitly scoped population proof below. Hero DTO
overall/avg_10 must equal round(the proven raw value, 2) on BOTH sides. Everything
else, including best values/owners, metadata, ranks and thresholds, stays exact.

The operand witness is distilled solely from Main's faithful frozen-P3 probe.
Native outputs are verified by an explicit binary64 left fold, NOT used as new
expected captures. No general float tolerance or hundredth-place waiver exists.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.sql import visitors
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.selectable import CTE

from shared import models
from shared.core import enums
from shared.division_grid import DEFAULT_GRID, ladder_grid
from shared.models.stats import StatDef, StatsFact, StatsMatch, StatsMatchPlayer
from shared.schemas.role import RoleRef
from shared.testing.stats_parity import is_mvp_stat, without_mvp
from src.services.user.queries import UserCompareQueries, UserProfileQueries

compare_queries = UserCompareQueries.of("overwatch")
profile_queries = UserProfileQueries.of("overwatch")

_FIXTURES = Path(__file__).parent / "fixtures"
_UNIT_ROUNDOFF = Fraction(1, 2**53)
_HALF_SUBNORMAL = Fraction(1, 2**1075)


def _bits(value):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), value
    assert math.isfinite(value), value
    return float(value).hex()


def _fold(values):
    # Python's built-in sum may use compensated summation; PostgreSQL float8 SUM does not.
    result = 0.0
    for value in values:
        result += value
    return result


def _cte(statement, name):
    matches = {id(node): node for node in visitors.iterate(statement) if isinstance(node, CTE) and node.name == name}
    assert len(matches) == 1, (name, len(matches))
    return next(iter(matches.values()))


def _operand_columns(facts, duration, participant):
    return (
        facts.c.match_id,
        facts.c.workspace_member_id,
        facts.c.player_id,
        facts.c.entity_id,
        facts.c.stat_code,
        facts.c.value,
        duration,
        participant,
    )


async def _operands(session, query):
    return [(*row[:5], _bits(row[5]), _bits(row[6]), row[7]) for row in (await session.execute(query)).all()]


async def _all_native_operands(session):
    """Independent native fact/owner/qualification read, not a legacy reader or adapter."""
    fact, match, stat = StatsFact.__table__, StatsMatch.__table__, StatDef.__table__
    member, entity = models.WorkspaceMember.__table__, models.CatalogEntity.__table__
    player = StatsMatchPlayer.__table__
    time_fact, time_stat = fact.alias("time_fact"), stat.alias("time_stat")
    query = (
        sa.select(
            fact.c.match_id,
            fact.c.workspace_member_id,
            member.c.player_id,
            fact.c.entity_id,
            stat.c.code,
            fact.c.value,
            match.c.duration_s,
            fact.c.encounter_team_id,
        )
        .select_from(fact)
        .join(match, match.c.id == fact.c.match_id)
        .join(
            player,
            sa.and_(
                player.c.match_id == fact.c.match_id,
                player.c.workspace_member_id == fact.c.workspace_member_id,
                player.c.encounter_team_id == fact.c.encounter_team_id,
            ),
        )
        .join(member, sa.and_(member.c.id == fact.c.workspace_member_id, member.c.workspace_id == match.c.workspace_id))
        .join(stat, sa.and_(stat.c.id == fact.c.stat_id, stat.c.discipline == match.c.discipline))
        .join(
            entity,
            sa.and_(
                entity.c.id == fact.c.entity_id, entity.c.discipline == match.c.discipline, entity.c.kind == "character"
            ),
        )
        .where(
            match.c.discipline == "overwatch",
            fact.c.segment == 0,
            sa.exists(
                sa.select(1)
                .select_from(time_fact)
                .join(
                    time_stat,
                    sa.and_(time_stat.c.id == time_fact.c.stat_id, time_stat.c.discipline == match.c.discipline),
                )
                .where(
                    time_fact.c.match_id == fact.c.match_id,
                    time_fact.c.workspace_member_id == fact.c.workspace_member_id,
                    time_fact.c.entity_id == fact.c.entity_id,
                    time_fact.c.segment == 0,
                    time_stat.c.code == "hero_time_played",
                    time_fact.c.value > 60,
                )
            ),
        )
    )
    return await _operands(session, query)


def _without_mvp_operands(rows):
    """Operand rows (stat code at index 4) of the stats the parity proof still compares."""
    return [row for row in rows if not is_mvp_stat(row[4])]


def _prove(group, pool, native_sum, native_time, native_avg):
    """Exact operand/denominator checks plus a data-derived binary64 error bound."""
    _identity, _stat, indices, old_sum_hex, old_time_hex, old_avg_hex = group
    old_operands = [pool[index] for index in indices]
    native_operands = sorted(old_operands, key=lambda row: (row[0], row[1], row[3]))
    values = [float.fromhex(row[5]) for row in native_operands]
    durations = [float.fromhex(row[6]) for row in native_operands]
    old_sum, old_time, old_avg = map(float.fromhex, (old_sum_hex, old_time_hex, old_avg_hex))
    # The faithful frozen sequence reconstructs the actual old SUM, not just a nearby number.
    assert _bits(_fold(float.fromhex(row[5]) for row in old_operands)) == old_sum_hex
    assert _bits(_fold(float.fromhex(row[6]) for row in old_operands)) == old_time_hex
    assert _bits(native_sum) == _bits(_fold(values))
    assert _bits(native_time) == old_time_hex == _bits(_fold(durations))
    denominator = sum(map(Fraction, durations), Fraction())
    assert denominator == Fraction(native_time) and denominator > 0  # No denominator tolerance.
    assert _bits(old_avg) == _bits(old_sum / old_time * 600)
    assert _bits(native_avg) == _bits(native_sum / native_time * 600)

    exact_sum = sum(map(Fraction, values), Fraction())
    magnitude = sum((abs(Fraction(value)) for value in values), Fraction())
    additions = len(values) - 1
    gamma = additions * _UNIT_ROUNDOFF / (1 - additions * _UNIT_ROUNDOFF)
    sum_bound = gamma * magnitude + additions * _HALF_SUBNORMAL
    for total, average in ((old_sum, old_avg), (native_sum, native_avg)):
        assert abs(Fraction(total) - exact_sum) <= sum_bound
        quotient = Fraction(total) / denominator
        division_bound = abs(quotient) * _UNIT_ROUNDOFF + _HALF_SUBNORMAL
        rounded_quotient = total / float(denominator)
        multiplication_bound = abs(Fraction(rounded_quotient) * 600) * _UNIT_ROUNDOFF + _HALF_SUBNORMAL
        bound = sum_bound / denominator * 600 + division_bound * 600 + multiplication_bound
        assert abs(Fraction(average) - exact_sum / denominator * 600) <= bound


def _at(value, path):
    for part in path:
        value = value[part]
    return value


def _strict(expected, actual, path=()):
    """Compare the entire output, with no numerical catch-all or skipped subtree."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), path
        for key, value in expected.items():
            _strict(value, actual[key], (*path, key))
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, (old, new) in enumerate(zip(expected, actual, strict=True)):
            _strict(old, new, (*path, index))
    elif isinstance(expected, float) and isinstance(actual, float):
        assert _bits(expected) == _bits(actual), (path, expected, actual)
    else:
        assert expected == actual, (path, expected, actual)


async def assert_app_golden(session, ids, actual):
    """Prove the named numerical exceptions, then compare every remaining leaf exactly.

    The MVP surface (``without_mvp``: impact/performance stats, placements, badges, MVP columns) is excluded on both
    sides: the frozen legacy golden cannot produce impact_v2, so it is neither compared nor proven here.
    """
    actual = without_mvp(actual)
    golden_bytes = (_FIXTURES / "stats_reader_parity.json").read_bytes()
    expected = without_mvp(json.loads(golden_bytes))
    witness_bytes = (_FIXTURES / "stats_reader_operands.json").read_bytes()
    witness = json.loads(witness_bytes)
    population_witness = json.loads((_FIXTURES / "stats_reader_population_operands.json").read_bytes())
    population_provenance = population_witness["provenance"]
    assert sha256(witness_bytes).hexdigest() == population_provenance["base_witness_sha256"]
    assert sha256(golden_bytes).hexdigest() == population_provenance["golden_sha256"]
    assert all(
        population_provenance[gate]
        for gate in (
            "all_frozen_outputs_match_golden",
            "all_population_links_exact",
            "all_frozen_probes_faithful",
            "workspace_population_matches_golden",
        )
    )
    provenance = witness["provenance"]
    assert sha256(golden_bytes).hexdigest() == provenance["golden_sha256"]
    assert provenance["all_frozen_outputs_match_golden"] and provenance["all_frozen_probes_faithful"]
    # Expected identities come from the frozen seed, never current native ownership.
    owners = {
        (match, player): (member, participant)
        for match, player, member, participant in population_witness["participants"]
    }
    assert len(owners) == len(population_witness["participants"])
    pool = []
    for row in witness["operands"]:
        member, participant = owners[(row[0], row[2])]
        assert row[1] == member
        pool.append((*row, participant))
    assert Counter(_without_mvp_operands(await _all_native_operands(session))) == Counter(
        _without_mvp_operands(pool)
    ), "Frozen/native operand bits or owners changed"

    # The fact/match subqueries are the OW-bound instances' own (built once per discipline), so the operand columns
    # below are the very objects the readers' statements embed.
    compare_module = compare_queries
    profile_module = profile_queries

    for scope, workspace in (
        ("all", None),
        ("workspace", ids["workspace"]),
        ("workspace_other", ids["workspace_other"]),
    ):
        statement = compare_queries._users_hero_compare_query_v2(
            user_ids=None,
            hero_id=None,
            map_id=None,
            stats=list(enums.LogStatsName),
            role=None,
            div_min=None,
            div_max=None,
            tournament_id=None,
            workspace_id=workspace,
            grid=DEFAULT_GRID,
        )
        aggregate = _cte(statement, "compare_hero_stats")
        columns = _operand_columns(
            compare_module._facts,
            compare_module._matches.c.duration_s,
            compare_module._facts.c.encounter_team_id,
        )
        observed = await _operands(
            session,
            aggregate.element.with_only_columns(
                *columns,
                maintain_column_froms=True,
            ).group_by(None),
        )
        groups = [group for group in witness["scopes"][scope] if not is_mvp_stat(group[1])]
        assert Counter(_without_mvp_operands(observed)) == Counter(
            pool[index] for group in groups for index in group[2]
        ), scope
        # Extract the actual SUM expressions; a changed denominator/expression cannot hide behind a ratio.
        terms = {}
        for node in visitors.iterate(aggregate.element.selected_columns.avg_10):
            if isinstance(node, FunctionElement) and node.name == "sum":
                argument = next(iter(node.clauses))
                assert isinstance(argument, aggregate_order_by)
                for label, column in (
                    ("sum", compare_module._facts.c.value),
                    ("time", compare_module._matches.c.duration_s),
                ):
                    if argument.target.shares_lineage(column):
                        terms[label] = node.label(f"proof_{label}")
        assert terms.keys() == {"sum", "time"}
        reductions = {
            (row.user_id, row.name): row
            for row in (await session.execute(aggregate.element.add_columns(terms["sum"], terms["time"]))).all()
            if not is_mvp_stat(row.name)
        }
        old_rows = {(row[0], row[1]): row for row in expected[scope]["hero_compare_raw"]["values"]}
        new_rows = {(row[0], row[1]): row for row in actual[scope]["hero_compare_raw"]["values"]}
        assert old_rows.keys() == new_rows.keys() == reductions.keys() == {(g[0], g[1]) for g in groups}
        for group in groups:
            key = (group[0], group[1])
            row, old, new = reductions[key], old_rows[key], new_rows[key]
            assert _bits(old[2]) == group[5]
            assert _bits(new[2]) == _bits(row.avg_10)
            _prove(group, pool, row.proof_sum, row.proof_time, row.avg_10)
            old[2] = new[2]

    profiles = (
        ("all_user", ("all", "user"), ids["player"], None, None),
        ("workspace_user", ("workspace", "user"), ids["player"], ids["workspace"], None),
        ("workspace_other_user", ("workspace_other", "user"), ids["player"], ids["workspace_other"], None),
        ("away", ("edge_users", "player_away"), ids["player_away"], ids["workspace"], None),
        ("removed", ("edge_users", "player_removed"), ids["player_removed"], ids["workspace"], None),
        ("tournament", ("tournaments", "tournament"), ids["player"], None, ids["tournament"]),
    )
    for case, path, player, workspace, tournament in profiles:
        statement = profile_queries._statistics_by_heroes_query(
            user_id=player,
            stats=None,
            workspace_id=workspace,
            tournament_id=tournament,
        )
        eligible, aggregate = _cte(statement, "eligible_user_hero_stats"), _cte(statement, "hero_stats_agg")
        player = StatsMatchPlayer.__table__
        observed = await _operands(
            session,
            sa.select(
                *_operand_columns(
                    eligible,
                    profile_module._matches.c.duration_s,
                    player.c.encounter_team_id,
                )
            )
            .select_from(eligible)
            .join(
                profile_module._matches,
                profile_module._matches.c.id == eligible.c.match_id,
            )
            .join(
                player,
                sa.and_(
                    player.c.match_id == eligible.c.match_id,
                    player.c.workspace_member_id == eligible.c.workspace_member_id,
                ),
            ),
        )
        groups = [group for group in witness["profiles"][case] if not is_mvp_stat(group[1])]
        assert Counter(_without_mvp_operands(observed)) == Counter(
            pool[index] for group in groups for index in group[2]
        ), case
        reductions = {
            (row.entity_id, row.stat_code): row
            for row in (await session.execute(sa.select(aggregate))).all()
            if not is_mvp_stat(row.stat_code)
        }
        old_parent, new_parent = _at(expected, path), _at(actual, path)
        old_rows = {(row[1]["id"], row[0]): row for row in old_parent["hero_statistics"]}
        new_rows = {(row[1]["id"], row[0]): row for row in new_parent["hero_statistics"]}
        assert old_rows.keys() == new_rows.keys() == reductions.keys() == {(g[0], g[1]) for g in groups}
        old_dtos = {
            (hero["hero"]["id"], stat["name"]): stat
            for hero in old_parent.get("heroes", {}).get("results", [])
            for stat in hero["stats"]
        }
        new_dtos = {
            (hero["hero"]["id"], stat["name"]): stat
            for hero in new_parent.get("heroes", {}).get("results", [])
            for stat in hero["stats"]
        }
        assert old_dtos.keys() == new_dtos.keys(), path
        for group in groups:
            key = (group[0], group[1])
            row, old, new = reductions[key], old_rows[key], new_rows[key]
            assert _bits(old[2]) == group[3] and _bits(old[4]) == group[5]
            assert _bits(new[2]) == _bits(row.total_value)
            _prove(group, pool, row.total_value, row.total_time, new[4])
            if key in old_dtos:
                for field, index in (("overall", 2), ("avg_10", 4)):
                    assert _bits(old_dtos[key][field]) == _bits(round(old[index], 2)), (path, key, field, "frozen")
                    assert _bits(new_dtos[key][field]) == _bits(round(new[index], 2)), (path, key, field, "native")
                    old_dtos[key][field] = new_dtos[key][field]
            old[2], old[4] = new[2], new[4]

    # Existing MV-only exception: <=1e-12 cross-model average, exact native derivation.
    mv_operands = defaultdict(list)
    for row in _without_mvp_operands(pool):
        mv_operands[(row[4], row[3])].append(row)
    old_records = {(row[0], row[1]): row for row in expected["global_hero_records"]}
    new_records = {(row[0], row[1]): row for row in actual["global_hero_records"]}
    assert old_records.keys() == new_records.keys() == mv_operands.keys()
    for key, operands in mv_operands.items():
        ordered = sorted(operands, key=lambda row: (row[0], row[1]))
        numerator = _fold(float.fromhex(row[5]) for row in ordered)
        denominator = _fold(float.fromhex(row[6]) for row in ordered)
        old, new = old_records[key], new_records[key]
        assert _bits(new[3]) == _bits(numerator / denominator * 600), ("native MV", key)
        assert abs(Fraction(old[3]) - Fraction(new[3])) <= Fraction(1, 10**12), ("MV average", key)
        old[3] = new[3]
    await _prove_comparison_population(session, ids, expected, actual, compare_module, pool, population_witness)
    _accept_observed_history_of_the_event_only_player(ids, expected, actual)
    _accept_p6_achievement_wire(actual)
    _accept_earned_ids_from_links(actual)
    _accept_canonical_all_workspaces_divisions(expected, actual)
    _strict(expected, actual)


def _accept_observed_history_of_the_event_only_player(ids, expected, actual):
    """The one approved difference between the frozen P3 golden and the P4 history reader.

    P4 (``d7a05b79e``; P4 ledger, "detailed DTO/readers/UI now use native observed participations/members rather than
    source rosters") lists every encounter a player has an observed participation in, retired seats included. The
    event-only player has no statistics but does have an observed participation in the main match, so the frozen
    page of ``[]`` becomes exactly that one encounter. Nothing else moves: the golden stays untouched on disk and only
    this leaf pair is replaced, after proving it is exactly that encounter.
    """
    frozen = expected["edge_users"]["player_event_only"]["encounters"]
    native = actual["edge_users"]["player_event_only"]["encounters"]
    assert frozen["results"] == [] and frozen["total"] == 0
    assert [row["id"] for row in native["results"]] == [ids["encounter"]] and native["total"] == 1
    frozen["results"], frozen["total"] = native["results"], native["total"]


def _accept_canonical_all_workspaces_divisions(expected, actual):
    """All-workspaces overview divisions became canonical native-ladder numbers with no stored grid behind them.

    Each role's ``division_grid_version_id`` is now null and the page's ``division_grids`` empty. The frozen numbers
    were on the seed's system grid, which is tier for tier the Overwatch native ladder, so every number stays put:
    the golden stays untouched on disk and only the grid references are replaced, after proving that.
    """
    ladder = [(tier.number, tier.rank_min, tier.rank_max) for tier in ladder_grid("overwatch").tiers]
    for label, frozen in expected["all"]["overview"].items():
        if "division_grids" not in frozen:
            continue  # a KPI header: its division_counts are compared exactly
        native = actual["all"]["overview"][label]
        for grid in frozen["division_grids"]:
            assert [(tier["number"], tier["rank_min"], tier["rank_max"]) for tier in grid["tiers"]] == ladder, label
        assert native["division_grids"] == [], label
        for frozen_row, native_row in zip(frozen["results"], native["results"], strict=True):
            for frozen_role, native_role in zip(frozen_row["roles"], native_row["roles"], strict=True):
                assert native_role["division_grid_version_id"] is None, label
                frozen_role["division_grid_version_id"] = None
        frozen["division_grids"] = []


def _accept_p6_achievement_wire(actual):
    """P6's wire cutover is the only change to the frozen achievement payloads.

    ``hero_id``/``hero`` became ``discipline``/``entity_id``/``entity`` (the catalog entity DTO). The golden stays
    untouched on disk; the native payload is rewritten into the P3 spelling only after proving the rule is an
    Overwatch rule and rebuilding the frozen ``hero`` object field by field from the entity, so a wrong entity,
    class or colour still fails the exact comparison.
    """

    def walk(node):
        if isinstance(node, dict):
            if {"entity_id", "entity", "discipline", "rarity"} <= node.keys():
                assert node.pop("discipline") == "overwatch"
                node["hero_id"] = node.pop("entity_id")
                entity = node.pop("entity")
                node["hero"] = (
                    None
                    if entity is None
                    else {
                        "id": entity["id"],
                        "slug": entity["slug"],
                        "name": entity["name"],
                        "image_path": entity["image_path"] or "",
                        "aliases": entity["aliases"],
                        "type": enums.HeroClass[entity["attrs"]["class"]].value,
                        "color": entity["attrs"].get("color", "#ffffff"),
                    }
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(actual)


def _accept_earned_ids_from_links(actual):
    """The user-achievement wire dropped ``tournaments_ids``/``matches_ids`` (no reader; 2026-10-23).

    Every frozen user read expanded ``tournaments`` and ``matches``, which list exactly those ids in the same sorted
    order, so the arrays are rebuilt from the links and still compared leaf by leaf.
    """

    def walk(node):
        if isinstance(node, dict):
            if {"tournaments", "matches", "count", "rarity"} <= node.keys() and "tournaments_ids" not in node:
                node["tournaments_ids"] = [tournament["id"] for tournament in node["tournaments"]]
                node["matches_ids"] = [match["id"] for match in node["matches"]]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(actual)


def _prove_two_person_mean(values, observed):
    """The three authorized baseline leaves have exactly two non-null participants."""
    assert len(values) == 2
    total = _fold(values)
    assert _bits(observed) == _bits(total / 2)
    exact = sum(map(Fraction, values), Fraction())
    magnitude = sum((abs(Fraction(value)) for value in values), Fraction())
    sum_bound = _UNIT_ROUNDOFF / (1 - _UNIT_ROUNDOFF) * magnitude + _HALF_SUBNORMAL
    assert abs(Fraction(total) - exact) <= sum_bound
    division_bound = abs(Fraction(total) / 2) * _UNIT_ROUNDOFF + _HALF_SUBNORMAL
    assert abs(Fraction(observed) - exact / 2) <= sum_bound / 2 + division_bound


async def _prove_comparison_population(session, ids, expected, actual, module, pool, witness):
    """Only the nine observed regular-compare leaves; no general metric/display waiver."""
    damage = RoleRef(dimension="player_role", role="damage")
    cases = (
        (
            "all",
            "damage",
            None,
            None,
            damage,
            {
                "eliminations": ("subject_value", "baseline_value"),
            },
        ),
        (
            "workspace",
            "global",
            ids["workspace"],
            None,
            None,
            {
                "final_blows": ("subject_value",),
            },
        ),
        (
            "workspace",
            "target",
            ids["workspace"],
            [ids["player"], ids["player_away"]],
            None,
            {
                "final_blows": ("subject_value",),
            },
        ),
        (
            "workspace",
            "damage",
            ids["workspace"],
            None,
            damage,
            {
                "eliminations": ("subject_value", "baseline_value"),
                "final_blows": ("subject_value", "baseline_value"),
            },
        ),
    )
    assert witness["nested_rows_per_stat"] == 1
    for scope, label, workspace, user_ids, role, allowed in cases:
        name = f"{scope}.{label}"
        case = witness["cases"][name]
        old_population = {row["id"]: without_mvp(row) for row in case["population"]}
        params = {
            "user_ids": user_ids,
            "role": role,
            "div_min": None,
            "div_max": None,
            "tournament_id": None,
            "workspace_id": workspace,
            "grid": DEFAULT_GRID,
        }
        statement = compare_queries._compare_metrics_query_v2(**params)
        native_population = await compare_queries.get_compare_population(session, **params)
        population = {row["id"]: without_mvp(row) for row in native_population}
        assert len(population) == len(native_population) == len(old_population)
        assert population.keys() == old_population.keys(), name
        inner, aggregate = _cte(statement, "compare_hero_match_stats"), _cte(statement, "compare_match_stats")
        player = StatsMatchPlayer.__table__
        inner_rows = (
            (
                await session.execute(
                    sa.select(
                        inner,
                        module._matches.c.duration_s.label("proof_duration"),
                        player.c.encounter_team_id.label("proof_participant"),
                    )
                    .select_from(inner)
                    .join(
                        module._matches,
                        module._matches.c.id == inner.c.match_id,
                    )
                    .join(
                        player,
                        sa.and_(
                            player.c.match_id == inner.c.match_id,
                            player.c.workspace_member_id == inner.c.workspace_member_id,
                        ),
                    )
                )
            )
            .mappings()
            .all()
        )
        observed = []
        for row in inner_rows:
            for code in allowed:
                metric = f"{code}_avg_10"
                # The faithful frozen capture has one raw observation per inner stat.
                # Never flatten a fan-out, missing stat, or multi-row reduction.
                assert row[f"{metric}_rows"] == 1, (name, row["match_id"], code)
                observed.append(
                    (
                        row["match_id"],
                        row["workspace_member_id"],
                        row["user_id"],
                        row["entity_id"],
                        code,
                        _bits(row[f"{metric}_value"]),
                        _bits(row["proof_duration"]),
                        row["proof_participant"],
                    )
                )
        groups = case["groups"]
        assert Counter(observed) == Counter(pool[index] for group in groups for index in group[2]), name

        # Observe the actual outer numerator/denominator expressions, not a guessed equivalent.
        extras = []
        for code in allowed:
            metric = f"{code}_avg_10"
            targets = {
                "sum": inner.c[f"{metric}_value"],
                "time": module._matches.c.duration_s * inner.c[f"{metric}_rows"],
            }
            terms = {}
            for node in visitors.iterate(aggregate.element.selected_columns[metric]):
                if isinstance(node, FunctionElement) and node.name == "sum":
                    argument = next(iter(node.clauses))
                    assert isinstance(argument, aggregate_order_by)
                    for part, target in targets.items():
                        if argument.target.compare(target):
                            terms[part] = node.label(f"proof_{metric}_{part}")
            assert terms.keys() == targets.keys(), (name, metric)
            extras.extend(terms.values())
        reductions = {
            row["user_id"]: row
            for row in (
                await session.execute(
                    aggregate.element.add_columns(*extras),
                )
            )
            .mappings()
            .all()
        }
        assert reductions.keys() == population.keys(), name
        expected_population = {user: dict(row) for user, row in old_population.items()}
        assert {(group[0], group[1]) for group in groups} == {(user, code) for user in population for code in allowed}
        for group in groups:
            user, code = group[:2]
            metric = f"{code}_avg_10"
            row = reductions[user]
            assert _bits(old_population[user][metric]) == group[5]
            assert _bits(population[user][metric]) == _bits(row[metric])
            _prove(group, pool, row[f"proof_{metric}_sum"], row[f"proof_{metric}_time"], row[metric])
            if user == ids["player"]:
                expected_population[user][metric] = population[user][metric]
        # Other users' inputs, cohort membership, counts and all non-selected metrics stay exact.
        _strict(expected_population, population, ("population proof", name))

        old_response, new_response = expected[scope]["compare"][label], actual[scope]["compare"][label]
        old_metrics = {metric["key"]: metric for metric in old_response["metrics"]}
        new_metrics = {metric["key"]: metric for metric in new_response["metrics"]}
        for code, fields in allowed.items():
            metric = f"{code}_avg_10"
            old, new = old_metrics[metric], new_metrics[metric]
            assert _bits(old["subject_value"]) == _bits(old_population[ids["player"]][metric])
            assert _bits(new["subject_value"]) == _bits(population[ids["player"]][metric])
            if "baseline_value" in fields:
                assert old_response["baseline"]["sample_size"] == new_response["baseline"]["sample_size"] == 2
                _prove_two_person_mean([row[metric] for row in case["population"]], old["baseline_value"])
                _prove_two_person_mean([population[user][metric] for user in sorted(population)], new["baseline_value"])
            for field in fields:
                old[field] = new[field]

        if name == "workspace.global":
            metric = "final_blows_avg_10"
            old = next(row for row in expected["workspace"]["compare_population"] if row["id"] == ids["player"])
            new = next(row for row in actual["workspace"]["compare_population"] if row["id"] == ids["player"])
            assert _bits(old[metric]) == _bits(old_population[ids["player"]][metric])
            assert _bits(new[metric]) == _bits(population[ids["player"]][metric])
            old[metric] = new[metric]

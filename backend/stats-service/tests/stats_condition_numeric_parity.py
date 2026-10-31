"""Prove only the four approved P4 KD weighted-rate metric differences.

Witness operands come from a faithful frozen query, never native expected-output
capture. Every raw rate/time/product bit and owner must match. Native reductions
must equal the immutable-grain binary64 fold exactly. Every other output leaf,
including condition keys, ranks, thresholds, evidence and runner state, is strict.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression
from sqlalchemy.sql.functions import FunctionElement

from shared import models
from shared.disciplines.overwatch.achievements.conditions import log_stat_rank
from shared.domain.achievements.context import EvalContext
from shared.testing.stats_parity import _json_default

_FIXTURES = Path(__file__).parent / "fixtures"
_UNIT_ROUNDOFF = Fraction(1, 2**53)
_HALF_SUBNORMAL = Fraction(1, 2**1075)


def _bits(value):
    assert isinstance(value, float) and math.isfinite(value), value
    return value.hex()


def _fold(values):
    # PostgreSQL float8 SUM is a binary64 left fold, not Python's compensated sum.
    result = 0.0
    for value in values:
        result += value
    return result


def _strict(expected, actual, path=()):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and expected.keys() == actual.keys(), path
        for key, value in expected.items():
            _strict(value, actual[key], (*path, key))
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(expected) == len(actual), path
        for index, (old, new) in enumerate(zip(expected, actual, strict=True)):
            _strict(old, new, (*path, index))
    elif isinstance(expected, float):
        assert _bits(expected) == _bits(actual), (path, expected, actual)
    else:
        assert type(expected) is type(actual) and expected == actual, (path, expected, actual)


def _reductions(statement):
    terms = {}
    for node in visitors.iterate(statement.selected_columns.metric):
        if not isinstance(node, FunctionElement) or node.name != "sum":
            continue
        ordered = next(iter(node.clauses))
        assert isinstance(ordered, aggregate_order_by), "Weighted sum lost its native reduction order"
        target = ordered.target
        if isinstance(target, BinaryExpression) and target.operator is operators.mul:
            terms["numerator"] = node
            rate, time = target.left.table.c, target.right.table.c
        else:
            terms["denominator"] = node
    assert terms.keys() == {"numerator", "denominator"}
    assert next(iter(terms["denominator"].clauses)).target.shares_lineage(time.value)
    for term in terms.values():
        order = tuple(next(iter(term.clauses)).order_by.clauses)
        assert len(order) == 2
        assert all(
            a.shares_lineage(b)
            for a, b in zip(
                order,
                (rate.match_id, rate.workspace_member_id),
                strict=True,
            )
        )
    return terms, rate, time


def _prove(group, pool, native_numerator, native_denominator, native_metric, *, native_operands):
    """Exact operands/owners/operations, then a product/sum/division bound."""
    frozen = [pool[index] for index in group["operand_indices"]]
    assert Counter(native_operands) == Counter(frozen), "Weighted operands or owners differ"
    assert frozen and len({(row[0], row[1]) for row in frozen}) == len(frozen)
    ordered = sorted(frozen, key=lambda row: (row[0], row[1]))
    for row in frozen:
        assert row[5:7] == ("kd", "hero_time_played")
        rate, time, product = map(float.fromhex, row[7:10])
        assert _bits(rate * time) == _bits(product) == row[9]
    old_numerator, old_denominator, old_metric = map(
        float.fromhex,
        (
            group["numerator_hex"],
            group["denominator_hex"],
            group["metric_hex"],
        ),
    )
    assert _bits(_fold(float.fromhex(row[9]) for row in frozen)) == group["numerator_hex"]
    assert _bits(_fold(float.fromhex(row[8]) for row in frozen)) == group["denominator_hex"]
    assert _bits(native_numerator) == _bits(_fold(float.fromhex(row[9]) for row in ordered))
    assert (
        _bits(native_denominator) == group["denominator_hex"] == _bits(_fold(float.fromhex(row[8]) for row in ordered))
    )
    denominator = sum((Fraction(float.fromhex(row[8])) for row in frozen), Fraction())
    assert denominator > 0 and denominator == Fraction(native_denominator)
    assert _bits(old_metric) == _bits(old_numerator / old_denominator)
    assert _bits(native_metric) == _bits(native_numerator / native_denominator)

    exact_products = [Fraction(float.fromhex(row[7])) * Fraction(float.fromhex(row[8])) for row in frozen]
    products = [Fraction(float.fromhex(row[9])) for row in frozen]
    product_bound = Fraction()
    for exact, rounded in zip(exact_products, products, strict=True):
        bound = abs(exact) * _UNIT_ROUNDOFF + _HALF_SUBNORMAL
        assert abs(rounded - exact) <= bound
        product_bound += bound
    additions = len(products) - 1
    gamma = additions * _UNIT_ROUNDOFF / (1 - additions * _UNIT_ROUNDOFF)
    sum_bound = gamma * sum(map(abs, products), Fraction()) + additions * _HALF_SUBNORMAL
    exact_numerator = sum(exact_products, Fraction())
    for numerator, metric in ((old_numerator, old_metric), (native_numerator, native_metric)):
        numerator_bound = product_bound + sum_bound
        assert abs(Fraction(numerator) - exact_numerator) <= numerator_bound
        quotient = Fraction(numerator) / denominator
        division_bound = abs(quotient) * _UNIT_ROUNDOFF + _HALF_SUBNORMAL
        assert abs(Fraction(metric) - exact_numerator / denominator) <= numerator_bound / denominator + division_bound


async def assert_condition_golden(session, ids, actual):
    # Keep the existing golden's JSON boundary (enums/dates/Decimal), without
    # rounding or changing any binary64 numeric value.
    actual = json.loads(json.dumps(actual, default=_json_default, allow_nan=False))
    golden_bytes = (_FIXTURES / "stats_condition_parity.json").read_bytes()
    expected = json.loads(golden_bytes)
    # The golden is the frozen legacy implementation's output and stays untouched; compare only the cases that still
    # exist. A case drops out for a changed semantics: a retired stat (``threshold/code/<code>`` of a code no longer
    # in ``LogStatsName``) or the MVP rank, now ``impact_rank`` (``mvp/ascending``, tested in
    # ``test_stats_condition_parity``). Any other missing case is a real regression and still fails ``_strict``.
    dropped = expected["trees"].keys() - actual["trees"].keys()
    assert all(name == "mvp/ascending" or name.startswith("threshold/code/") for name in dropped), dropped
    for name in dropped:
        del expected["trees"][name]
        for scope in expected["scopes"].values():
            del scope["conditions"][name]
    witness = json.loads((_FIXTURES / "stats_condition_weighted_operands.json").read_text(encoding="utf-8"))
    assert witness["format"] == 1
    provenance = witness["provenance"]
    assert sha256(golden_bytes).hexdigest() == provenance["golden_sha256"]
    assert provenance["all_frozen_outputs_match_golden"] and provenance["all_frozen_probes_faithful"]
    assert provenance["all_frozen_sequences_reconstruct_original"]
    allowed = {
        (scope, player, ids["tournament"])
        for scope in ("tournament", "workspace")
        for player in (ids["player"], ids["player_away"])
    }
    groups = {(group["scope"], group["user_id"], group["tournament_id"]): group for group in witness["groups"]}
    assert len(groups) == len(witness["groups"]) == 4 and groups.keys() == allowed
    pool = [tuple(row) for row in witness["operands"]]
    participant_owners = {
        (row["encounter_id"], row["tournament_team_id"]): row["encounter_team_id"]
        for row in witness["participant_owners"]
    }
    # These fixture ids name the original seeded encounter participants; they
    # are not recovered from current native observations or their query joins.
    assert len(participant_owners) == len(witness["participant_owners"]) == 2
    assert participant_owners == {
        (ids["encounter"], ids["team_home"]): ids["encounter_team_home"],
        (ids["encounter"], ids["team_away"]): ids["encounter_team_away"],
    }
    for operand in pool:
        assert len(operand) == 11
        assert operand[10] == participant_owners[operand[4], operand[3]]
    assert len(set(pool)) == len(pool)
    assert {index for group in groups.values() for index in group["operand_indices"]} == set(range(len(pool)))

    for scope in ("tournament", "workspace"):
        tournament = await session.get(models.Tournament, ids["tournament"]) if scope == "tournament" else None
        statement = log_stat_rank._time_weighted_rate_query(
            "kd",
            EvalContext(
                workspace_id=ids["workspace"],
                discipline="overwatch",
                tournament=tournament,
            ),
        )
        terms, rate, time = _reductions(statement)
        operands = defaultdict(list)
        projected = statement.with_only_columns(
            rate.match_id,
            rate.workspace_member_id,
            rate.player_id,
            rate.tournament_team_id,
            rate.encounter_id,
            rate.stat_code,
            time.stat_code,
            rate.value,
            time.value,
            rate.value * time.value,
            rate.tournament_id,
            rate.workspace_id,
            rate.discipline,
            rate.encounter_team_id,
            time.match_id,
            time.workspace_member_id,
            time.encounter_team_id,
            time.workspace_id,
            time.discipline,
            maintain_column_froms=True,
        ).group_by(None)
        for row in (await session.execute(projected)).all():
            assert row[11:13] == (ids["workspace"], "overwatch")
            assert row[14:19] == (row[0], row[1], row[13], row[11], row[12])
            operands[row[2], row[10]].append((*row[:7], *map(_bits, row[7:10]), row[13]))
        reductions = {
            (row.user_id, row.tournament_id): row
            for row in (
                await session.execute(
                    statement.add_columns(
                        terms["numerator"].label("proof_numerator"), terms["denominator"].label("proof_denominator")
                    ),
                )
            ).all()
        }
        old_list = expected["scopes"][scope]["rank_values"]["weighted_rate"]
        new_list = actual["scopes"][scope]["rank_values"]["weighted_rate"]
        old_rows = {(row["user_id"], row["tournament_id"]): row for row in old_list}
        new_rows = {(row["user_id"], row["tournament_id"]): row for row in new_list}
        assert len(old_rows) == len(old_list) and len(new_rows) == len(new_list)
        assert old_rows.keys() == new_rows.keys() == reductions.keys() == operands.keys()
        for player in (ids["player"], ids["player_away"]):
            key = (player, ids["tournament"])
            group = groups[scope, *key]
            native, old, new = reductions[key], old_rows[key], new_rows[key]
            assert _bits(old["metric"]) == group["metric_hex"]
            assert _bits(new["metric"]) == _bits(native.metric)
            _prove(
                group,
                pool,
                native.proof_numerator,
                native.proof_denominator,
                native.metric,
                native_operands=operands[key],
            )
            # Only these four witnessed scalar leaves are reconciled. The full
            # frozen structure, ordering and every other scalar remain strict.
            old["metric"] = new["metric"]
    _strict(expected, actual)

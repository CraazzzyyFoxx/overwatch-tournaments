"""participation — organisational work a player does around the matches themselves.

Two nodes that read the paperwork trail instead of the telemetry:
``captain_report_activity`` (result reports, per-map reports, replay codes,
readiness confirmations) and ``log_upload_count`` (match logs uploaded).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementGrain
from src import models

from ..context import EvalContext
from . import ResultSet, register

OPERATORS = {
    "==": lambda col, val: col == val,
    "!=": lambda col, val: col != val,
    ">=": lambda col, val: col >= val,
    ">": lambda col, val: col > val,
    "<=": lambda col, val: col <= val,
    "<": lambda col, val: col < val,
}


@register(
    "captain_report_activity",
    grain=AchievementGrain.user_tournament,
    description="How much of the result reporting the player did for their team",
    required=("metric", "op", "value"),
    depends_on=("tournament.encounter_report", "tournament.encounter"),
)
async def execute_captain_report_activity(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count reporting rows a player filed, per tournament. Grain: user_tournament."""
    metric = params["metric"]
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]

    if metric == "series_reported":
        source = models.EncounterCaptainReport
        user_col = models.EncounterCaptainReport.reporter_user_id
        encounter_col = models.EncounterCaptainReport.encounter_id
        counted = models.EncounterCaptainReport.id
    elif metric == "map_reports":
        source = models.EncounterMapReport
        user_col = models.EncounterMapReport.reporter_user_id
        encounter_col = models.EncounterMapReport.encounter_id
        counted = models.EncounterMapReport.id
    elif metric == "map_codes":
        # Codes hang off the filer's own captain report, which is what carries
        # both the reporter identity and the encounter.
        source = models.EncounterMapCode
        user_col = models.EncounterCaptainReport.reporter_user_id
        encounter_col = models.EncounterCaptainReport.encounter_id
        counted = models.EncounterMapCode.id
    elif metric == "readiness":
        source = models.EncounterReadiness
        user_col = models.EncounterReadiness.ready_user_id
        encounter_col = models.EncounterReadiness.encounter_id
        counted = models.EncounterReadiness.id
    else:
        raise ValueError(f"Unsupported captain_report_activity metric: {metric!r}")

    count_expr = sa.func.count(sa.distinct(counted))
    query = sa.select(user_col, models.Encounter.tournament_id, count_expr).select_from(source)

    if metric == "map_codes":
        query = query.join(
            models.EncounterCaptainReport,
            models.EncounterCaptainReport.id == models.EncounterMapCode.report_id,
        )

    query = (
        query.join(models.Encounter, models.Encounter.id == encounter_col)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            user_col.isnot(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(user_col, models.Encounter.tournament_id)
        .having(op_fn(count_expr, value))
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = (row[0], row[1])
        keys.add(key)
        context.record_evidence(key, metric=metric, count=int(row[2]))
    return keys


@register(
    "log_upload_count",
    grain=AchievementGrain.user,
    description="Match logs the player uploaded",
    required=("op", "value"),
    optional=("scope", "status"),
    depends_on=("log_processing.record",),
    grain_for=lambda params: (
        AchievementGrain.user_tournament if params.get("scope") == "tournament" else AchievementGrain.user
    ),
)
async def execute_log_upload_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count uploaded log files. Grain: user, or user_tournament with scope="tournament"."""
    op = params["op"]
    value = params["value"]
    scope = params.get("scope", "global")
    status = params.get("status", "done")
    op_fn = OPERATORS[op]

    group_cols = [models.LogProcessingRecord.uploader_id]
    if scope == "tournament":
        group_cols.append(models.LogProcessingRecord.tournament_id)

    count_expr = sa.func.count(sa.distinct(models.LogProcessingRecord.id))
    query = (
        sa.select(*group_cols, count_expr)
        .join(models.Tournament, models.Tournament.id == models.LogProcessingRecord.tournament_id)
        .where(
            models.LogProcessingRecord.uploader_id.isnot(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(*group_cols)
        .having(op_fn(count_expr, value))
    )

    if status != "any":
        query = query.where(models.LogProcessingRecord.status == models.LogProcessingStatus(status))

    if context.tournament and scope == "tournament":
        query = query.where(models.LogProcessingRecord.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = tuple(row[:-1])
        keys.add(key)
        context.record_evidence(key, count=int(row[-1]), status=status)
    return keys

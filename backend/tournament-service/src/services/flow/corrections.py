"""Corrections over the flow: a result change is refused once a node downstream already started (spec §8.4)."""

from collections import defaultdict

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.flow_state import LIFECYCLE_KINDS

__all__ = ("assert_encounter_correction_allowed", "assert_stage_correction_allowed", "started_cut")

#: Per lifecycle kind, the statuses at which its input is frozen: a playing or finished stage, a forming or finished
#: formation. ``ready`` is not here: the stage is re-seated instead (``reseat_ready_stages``).
_STARTED: dict[FlowNodeKind, frozenset[FlowNodeStatus]] = {
    FlowNodeKind.STAGE: frozenset({FlowNodeStatus.LIVE, FlowNodeStatus.COMPLETED}),
    FlowNodeKind.FORMATION: frozenset({FlowNodeStatus.FORMING, FlowNodeStatus.COMPLETED}),
}


async def _started_downstream(session: AsyncSession, node_id: int, tournament_id: int) -> list[str]:
    """Names of the started lifecycle nodes reached from ``node_id`` through pure nodes only."""
    edges = await session.execute(
        select(models.FlowEdge.source_node_id, models.FlowEdge.target_node_id).where(
            models.FlowEdge.tournament_id == tournament_id
        )
    )
    targets: defaultdict[int, list[int]] = defaultdict(list)
    for source, target in edges:
        targets[source].append(target)
    nodes = {
        row.id: row
        for row in await session.execute(
            select(models.FlowNode.id, models.FlowNode.kind, models.FlowNode.name, models.FlowNode.status).where(
                models.FlowNode.tournament_id == tournament_id
            )
        )
    }
    seen, queue, started = {node_id}, [node_id], []
    while queue:
        for target in targets[queue.pop()]:
            if target in seen:
                continue
            seen.add(target)
            node = nodes[target]
            if node.kind not in LIFECYCLE_KINDS:
                queue.append(target)
            elif node.status in _STARTED.get(FlowNodeKind(node.kind), ()):
                started.append(node.name)
    return started


async def assert_stage_correction_allowed(session: AsyncSession, stage_id: int) -> None:
    """409 ``downstream_started`` while a node fed by this stage's results has started; no-op for a stage without a node."""
    node = (
        await session.execute(
            select(models.FlowNode.id, models.FlowNode.tournament_id).where(models.FlowNode.stage_id == stage_id)
        )
    ).first()
    if node is None:
        return
    started = await _started_downstream(session, node.id, node.tournament_id)
    if started:
        raise ApiHTTPException(
            status_code=409,
            detail=[
                ApiExc(
                    code="downstream_started",
                    msg=f"Downstream {', '.join(started)} already started; correct it there or reopen it first",
                )
            ],
        )


async def assert_encounter_correction_allowed(session: AsyncSession, encounter: models.Encounter) -> None:
    """The stage rule for the stage ``encounter`` belongs to; no-op for an encounter outside a stage."""
    stage_id = await session.scalar(
        select(models.BracketEncounter.stage_id).where(models.BracketEncounter.encounter_id == encounter.id)
    )
    if stage_id is not None:
        await assert_stage_correction_allowed(session, stage_id)


async def started_cut(session: AsyncSession, stage_item_id: int) -> int | None:
    """The deepest ``item_rank`` of ``stage_item_id`` seated in a started stage or fed to a started formation, ``None``
    when there is none.

    Every place down to it is frozen into a node that can no longer be re-seated; places below it qualified nobody who
    is playing.
    """
    seated = await session.scalar(
        select(func.max(models.FlowNodeResult.item_rank))
        .join(models.StageItemInput, models.StageItemInput.source_result_id == models.FlowNodeResult.id)
        .join(models.StageItem, models.StageItem.id == models.StageItemInput.stage_item_id)
        .join(models.FlowNode, models.FlowNode.stage_id == models.StageItem.stage_id)
        .where(
            models.FlowNodeResult.stage_item_id == stage_item_id,
            models.FlowNode.status.in_([status.value for status in _STARTED[FlowNodeKind.STAGE]]),
        )
    )
    # A formation seats nobody: what it consumed is the rows of the node that feeds it.
    consumed = await session.scalar(
        select(func.max(models.FlowNodeResult.item_rank))
        .join(
            models.FlowEdge,
            and_(
                models.FlowEdge.source_node_id == models.FlowNodeResult.node_id,
                models.FlowEdge.source_port == models.FlowNodeResult.port,
            ),
        )
        .join(models.FlowNode, models.FlowNode.id == models.FlowEdge.target_node_id)
        .where(
            models.FlowNodeResult.stage_item_id == stage_item_id,
            models.FlowNode.kind == FlowNodeKind.FORMATION,
            models.FlowNode.status.in_([status.value for status in _STARTED[FlowNodeKind.FORMATION]]),
        )
    )
    return max((cut for cut in (seated, consumed) if cut is not None), default=None)

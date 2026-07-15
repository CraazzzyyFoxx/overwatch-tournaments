"""OpenAPI request/response model map for balancer-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
Models mirror the handlers' direct model construction / serializer return types
(src/rpc/*.py + src/schemas). Nullable-on-empty reads (tournament_config_get,
balance_get) and bare-dict / 204 handlers are omitted.
"""

from __future__ import annotations

from shared.rpc.openapi import Op
from src import schemas
from src.schemas import draft as draft_schemas
from src.schemas.admin import balancer as admin_schemas

OPERATIONS: dict[str, Op] = {
    # ── config (public) ────────────────────────────────────────────────────
    "rpc.balancer.config": Op(response=schemas.BalancerConfigResponse),
    # ── admin: configs + balance ───────────────────────────────────────────
    "rpc.balancer.admin.tournament_config_upsert": Op(
        request=admin_schemas.BalancerTournamentConfigUpsert, response=admin_schemas.BalancerTournamentConfigRead
    ),
    "rpc.balancer.admin.balance_save": Op(request=admin_schemas.BalanceSaveRequest, response=admin_schemas.BalanceRead),
    "rpc.balancer.admin.balance_export": Op(response=admin_schemas.BalanceExportResponse),
    "rpc.balancer.admin.workspace_config_get": Op(response=admin_schemas.WorkspaceBalancerConfigRead),
    "rpc.balancer.admin.workspace_config_upsert": Op(
        request=admin_schemas.WorkspaceBalancerConfigUpsert, response=admin_schemas.WorkspaceBalancerConfigRead
    ),
    # ── jobs (public, Redis-backed) ────────────────────────────────────────
    "rpc.balancer.jobs.status": Op(response=schemas.JobStatusResponse),
    "rpc.balancer.jobs.result": Op(response=schemas.BalanceJobResult),
    "rpc.balancer.jobs.create": Op(response=schemas.CreateJobResponse),
    # ── draft: public reads ────────────────────────────────────────────────
    "rpc.balancer.draft.tournament_board": Op(response=draft_schemas.DraftBoardSnapshot),
    "rpc.balancer.draft.session_get": Op(response=draft_schemas.DraftSessionRead),
    "rpc.balancer.draft.session_board": Op(response=draft_schemas.DraftBoardSnapshot),
    "rpc.balancer.draft.suggestions": Op(response=draft_schemas.DraftSuggestionsResponse),
    "rpc.balancer.draft.feasibility": Op(response=draft_schemas.DraftFeasibilityResponse),
    "rpc.balancer.draft.pick_options": Op(response=draft_schemas.DraftPickOptionsResponse),
    "rpc.balancer.draft.player_role_edit": Op(
        request=draft_schemas.DraftRoleEditRequest,
        response=draft_schemas.DraftRoleEditResponse,
    ),
    # ── draft: admin lifecycle (all -> DraftSessionRead) ───────────────────
    "rpc.balancer.draft.session_create": Op(
        request=draft_schemas.DraftSessionCreateRequest, response=draft_schemas.DraftSessionRead
    ),
    "rpc.balancer.draft.seed": Op(request=draft_schemas.DraftSeedRequest, response=draft_schemas.DraftSeedResponse),
    "rpc.balancer.draft.session_patch": Op(
        request=draft_schemas.DraftSessionPatchRequest, response=draft_schemas.DraftSessionRead
    ),
    "rpc.balancer.draft.start": Op(response=draft_schemas.DraftSessionRead),
    "rpc.balancer.draft.pause": Op(response=draft_schemas.DraftSessionRead),
    "rpc.balancer.draft.resume": Op(response=draft_schemas.DraftSessionRead),
    "rpc.balancer.draft.cancel": Op(response=draft_schemas.DraftSessionRead),
    "rpc.balancer.draft.rollback": Op(response=draft_schemas.DraftSessionRead),
    "rpc.balancer.draft.export": Op(response=draft_schemas.DraftSessionRead),
    # ── draft: pick actions (all -> DraftSessionRead) ──────────────────────
    "rpc.balancer.draft.pick_select": Op(
        request=draft_schemas.DraftPickSelectRequest, response=draft_schemas.DraftSessionRead
    ),
    "rpc.balancer.draft.pick_autopick": Op(
        request=draft_schemas.DraftPickAutopickRequest, response=draft_schemas.DraftSessionRead
    ),
    "rpc.balancer.draft.pick_override": Op(
        request=draft_schemas.DraftPickOverrideRequest, response=draft_schemas.DraftSessionRead
    ),
}

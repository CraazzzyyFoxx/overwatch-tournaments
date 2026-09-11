"""OpenAPI request/response model map for balancer-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
Models mirror the handlers' direct model construction / serializer return types
(src/rpc/*.py + src/schemas). Nullable-on-empty reads (tournament_config_get,
balance_get) and bare-dict / 204 handlers are omitted.
"""

from __future__ import annotations

from shared.rpc.openapi import Op, QueryParam
from src import schemas
from src.schemas import custom_game

OPERATIONS: dict[str, Op] = {
    # ── config (public) ────────────────────────────────────────────────────
    "rpc.balancer.config": Op(response=schemas.BalancerConfigResponse),
    # ── admin: configs + balance ───────────────────────────────────────────
    "rpc.balancer.admin.tournament_config_upsert": Op(
        request=schemas.BalancerTournamentConfigUpsert, response=schemas.BalancerTournamentConfigRead
    ),
    "rpc.balancer.admin.balance_save": Op(request=schemas.BalanceSaveRequest, response=schemas.BalanceRead),
    "rpc.balancer.admin.balance_export": Op(response=schemas.BalanceExportResponse),
    "rpc.balancer.admin.balance_ranks_export": Op(response=schemas.RanksExportResponse),
    "rpc.balancer.admin.workspace_config_get": Op(response=schemas.WorkspaceBalancerConfigRead),
    "rpc.balancer.admin.workspace_config_upsert": Op(
        request=schemas.WorkspaceBalancerConfigUpsert, response=schemas.WorkspaceBalancerConfigRead
    ),
    # ── jobs (public, Redis-backed) ────────────────────────────────────────
    "rpc.balancer.jobs.status": Op(response=schemas.JobStatusResponse),
    "rpc.balancer.jobs.result": Op(response=schemas.BalanceJobResult),
    "rpc.balancer.jobs.create": Op(response=schemas.CreateJobResponse),
    # No player payload: the xv-1 input is built server-side from the one roster
    # engine, so a tournament balance and its draft cannot read different ranks.
    "rpc.balancer.jobs.create_for_tournament": Op(
        request=schemas.TournamentBalanceRequest, response=schemas.CreateJobResponse
    ),
    # ── draft: public reads ────────────────────────────────────────────────
    "rpc.balancer.draft.tournament_board": Op(response=schemas.DraftBoardSnapshot),
    "rpc.balancer.draft.session_get": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.session_board": Op(response=schemas.DraftBoardSnapshot),
    "rpc.balancer.draft.suggestions": Op(response=schemas.DraftSuggestionsResponse),
    "rpc.balancer.draft.feasibility": Op(response=schemas.DraftFeasibilityResponse),
    "rpc.balancer.draft.pick_options": Op(response=schemas.DraftPickOptionsResponse),
    "rpc.balancer.draft.player_role_edit": Op(
        request=schemas.DraftRoleEditRequest,
        response=schemas.DraftRoleEditResponse,
    ),
    # ── draft: admin lifecycle (all -> DraftSessionRead) ───────────────────
    "rpc.balancer.draft.session_list": Op(response=schemas.DraftSessionRead, response_array=True),
    "rpc.balancer.draft.session_create": Op(
        request=schemas.DraftSessionCreateRequest, response=schemas.DraftSessionRead
    ),
    "rpc.balancer.draft.seed": Op(request=schemas.DraftSeedRequest, response=schemas.DraftSeedResponse),
    "rpc.balancer.draft.session_patch": Op(request=schemas.DraftSessionPatchRequest, response=schemas.DraftSessionRead),
    "rpc.balancer.draft.start": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.pause": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.resume": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.cancel": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.rollback": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.export": Op(response=schemas.DraftSessionRead),
    "rpc.balancer.draft.export_ranks": Op(response=schemas.RanksExportResponse),
    # ── draft: pick actions (all -> DraftSessionRead) ──────────────────────
    "rpc.balancer.draft.pick_select": Op(request=schemas.DraftPickSelectRequest, response=schemas.DraftSessionRead),
    "rpc.balancer.draft.pick_autopick": Op(request=schemas.DraftPickAutopickRequest, response=schemas.DraftSessionRead),
    "rpc.balancer.draft.pick_override": Op(request=schemas.DraftPickOverrideRequest, response=schemas.DraftSessionRead),
    # ── pickup mixes: writes (responses are hand-built dicts, see DOCS) ─────
    "rpc.balancer.custom.create": Op(request=custom_game.CustomGameCreate),
    "rpc.balancer.custom.update_roster": Op(request=custom_game.CustomGameRosterUpdate),
    "rpc.balancer.custom.update_player": Op(request=custom_game.CustomGamePlayerPatch),
    "rpc.balancer.custom.set_participation": Op(request=custom_game.CustomGamePlayersParticipationPatch),
    "rpc.balancer.custom.set_team_names": Op(request=custom_game.CustomGameTeamNamesPatch),
    "rpc.balancer.custom.set_role_mask": Op(request=custom_game.CustomGameRoleMaskPatch),
    "rpc.balancer.custom.set_points_per_win": Op(request=custom_game.CustomGamePointsPerWinPatch),
    "rpc.balancer.custom.set_next_map": Op(request=custom_game.CustomGameNextMapPatch),
    "rpc.balancer.custom.set_discord_channel": Op(request=custom_game.CustomGameDiscordChannelPatch),
    "rpc.balancer.custom.post_discord": Op(request=custom_game.CustomGamePostDiscord),
    "rpc.balancer.custom.set_balancer_config": Op(request=custom_game.CustomGameBalancerConfigPatch),
    "rpc.balancer.custom.transfer_host": Op(request=custom_game.CustomGameHostTransfer),
    "rpc.balancer.custom.add_co_host": Op(request=custom_game.CustomGameCoHostPatch),
    "rpc.balancer.custom.swap_seats": Op(request=custom_game.CustomGameSeatSwap),
    "rpc.balancer.custom.record_outcome": Op(request=custom_game.CustomGameRecordOutcome),
    # ── workspace roster + rank layers ─────────────────────────────────────
    # Ad-hoc query keys read by ``src/rpc/players.py`` (``_list_params``,
    # ``_author_to_read``, ``_author_only``) rather than a query model.
    "rpc.balancer.players.list": Op(
        query_params=(
            QueryParam("page", "integer", description="1-based page, default 1."),
            QueryParam("per_page", "integer", description="Page size, clamped to 1..100, default 30."),
            QueryParam("query", description="Needle matched against battle_tag, display_name and name."),
            QueryParam(
                "author_user_id",
                "integer",
                description="Whose rank book to read into author_ranks; defaults to the caller.",
            ),
            QueryParam(
                "author_only",
                "boolean",
                description="Keep only members that read author has personally ranked.",
            ),
        )
    ),
    "rpc.balancer.players.summary": Op(
        query_params=(
            QueryParam(
                "author_user_id",
                "integer",
                description="Whose rank book author_total counts; defaults to the caller.",
            ),
        )
    ),
}

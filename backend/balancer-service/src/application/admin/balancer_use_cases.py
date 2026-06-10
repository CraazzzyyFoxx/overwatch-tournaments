from __future__ import annotations


class GetTournamentConfig:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int):
        return await self._balancer_service.get_tournament_config(session, tournament_id)


class UpsertTournamentConfig:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int, payload, user):
        return await self._balancer_service.upsert_tournament_config(
            session,
            tournament_id,
            payload.config_json,
            user,
        )


class GetSavedBalance:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int):
        return await self._balancer_service.get_balance(session, tournament_id)


class SaveBalance:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int, payload, user):
        return await self._balancer_service.save_balance(session, tournament_id, payload, user)


class ExportBalance:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, balance_id: int):
        return await self._balancer_service.export_balance(session, balance_id)


class ImportTeamsFromJson:
    def __init__(self, *, team_flows) -> None:
        self._team_flows = team_flows

    async def execute(self, *, session, tournament_id: int, teams) -> None:
        await self._team_flows.bulk_create_from_balancer(session, tournament_id, teams)


class GetWorkspaceBalancerConfig:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, workspace_id: int):
        return await self._balancer_service.get_workspace_balancer_config(session, workspace_id)


class UpsertWorkspaceBalancerConfig:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, workspace_id: int, payload, updated_by: int | None):
        return await self._balancer_service.upsert_workspace_balancer_config(
            session,
            workspace_id=workspace_id,
            rank_delta_threshold=payload.rank_delta_threshold,
            rank_delta_hide_from_pool=payload.rank_delta_hide_from_pool,
            updated_by=updated_by,
        )

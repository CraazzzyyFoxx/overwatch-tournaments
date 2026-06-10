from __future__ import annotations


class ListApplications:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int, include_inactive: bool = False):
        return await self._balancer_service.list_applications(
            session,
            tournament_id,
            include_inactive=include_inactive,
        )


class GetTournamentSheet:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int):
        return await self._registration_service.get_google_sheet_feed(session, tournament_id)


class UpsertTournamentSheet:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._registration_service.upsert_google_sheet_feed(
            session,
            tournament_id,
            source_url=payload.source_url,
            title=payload.title,
            auto_sync_enabled=payload.auto_sync_enabled,
            auto_sync_interval_seconds=payload.auto_sync_interval_seconds,
            mapping_config_json=payload.mapping_config_json,
            value_mapping_json=payload.value_mapping_json,
        )


class SyncTournamentSheet:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int):
        return await self._registration_service.sync_google_sheet_feed(session, tournament_id)


class SuggestTournamentSheetMapping:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._registration_service.suggest_google_sheet_mapping(
            session,
            tournament_id,
            source_url=payload.source_url,
        )


class PreviewTournamentSheetMapping:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._registration_service.preview_google_sheet_mapping(
            session,
            tournament_id,
            source_url=payload.source_url,
            mapping_config_json=payload.mapping_config_json,
            value_mapping_json=payload.value_mapping_json,
        )


class CreatePlayersFromApplications:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._balancer_service.create_players_from_applications(session, tournament_id, payload)


class ListPlayers:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int, in_pool_only: bool = False):
        return await self._balancer_service.list_players(session, tournament_id, in_pool_only=in_pool_only)


class UpdatePlayer:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, player_id: int, payload):
        return await self._balancer_service.update_player(session, player_id, payload)


class DeletePlayer:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, player_id: int) -> None:
        await self._balancer_service.delete_player(session, player_id)


class PreviewPlayerImport:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int, payload: dict, match_application_roles: bool):
        return await self._balancer_service.preview_player_import(
            session,
            tournament_id,
            payload,
            match_application_roles=match_application_roles,
        )


class ImportPlayers:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(
        self,
        *,
        session,
        tournament_id: int,
        payload: dict,
        duplicate_strategy,
        resolutions,
        match_application_roles: bool,
    ):
        return await self._balancer_service.import_players(
            session,
            tournament_id,
            payload,
            duplicate_strategy=duplicate_strategy,
            resolutions=resolutions,
            match_application_roles=match_application_roles,
        )


class ExportPlayers:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int):
        return await self._registration_service.export_active_registrations(session, tournament_id)


class SyncPlayerRolesFromApplications:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int):
        return await self._balancer_service.sync_player_roles_from_applications(session, tournament_id)


class ExportApplicationsToUsers:
    def __init__(self, *, balancer_service) -> None:
        self._balancer_service = balancer_service

    async def execute(self, *, session, tournament_id: int):
        return await self._balancer_service.export_applications_to_users(session, tournament_id)


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

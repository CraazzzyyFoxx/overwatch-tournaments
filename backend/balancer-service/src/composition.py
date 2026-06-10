from __future__ import annotations

from types import SimpleNamespace

from src.application.admin.background_use_cases import SyncDueRegistrationSheets
from src.application.admin.balancer_use_cases import (
    CreatePlayersFromApplications,
    DeletePlayer,
    ExportApplicationsToUsers,
    ExportBalance,
    ExportPlayers,
    GetSavedBalance,
    GetTournamentConfig,
    GetTournamentSheet,
    GetWorkspaceBalancerConfig,
    ImportPlayers,
    ImportTeamsFromJson,
    ListApplications,
    ListPlayers,
    PreviewPlayerImport,
    PreviewTournamentSheetMapping,
    SaveBalance,
    SuggestTournamentSheetMapping,
    SyncPlayerRolesFromApplications,
    SyncTournamentSheet,
    UpdatePlayer,
    UpsertTournamentConfig,
    UpsertTournamentSheet,
    UpsertWorkspaceBalancerConfig,
)
from src.application.admin.registration_status_use_cases import (
    CreateCustomStatus,
    DeleteCustomStatus,
    ListCustomStatuses,
    ListStatusCatalog,
    ResetBuiltinOverride,
    UpdateCustomStatus,
    UpsertBuiltinOverride,
)
from src.application.admin.registration_use_cases import (
    ApproveRegistration,
    BulkAddToBalancer,
    BulkApproveRegistrations,
    CreateRegistration,
    DeleteRegistration,
    ExportRegistrationsToUsers,
    GetRegistrationForm,
    ListRegistrations,
    RejectRegistration,
    RestoreRegistration,
    SetBalancerStatus,
    SetRegistrationExclusion,
    ToggleCheckIn,
    UpdateRegistration,
    UpsertRegistrationForm,
    WithdrawRegistration,
)
from src.application.balancer.public_use_cases import (
    CreateBalanceJob,
    ExecuteBalanceJob,
    GetBalanceJobResult,
    GetBalanceJobStatus,
    GetBalancerConfig,
    StreamBalanceJobEvents,
)
from src.domain.balancer.config_provider import BalancerConfigService
from src.infrastructure.gateways.service_gateways import (
    BalancerAdminGateway,
    RegistrationAdminGateway,
    RegistrationStatusGateway,
    TeamGateway,
)
from src.infrastructure.parsers.balancer_request_parser import BalancerRequestParser
from src.infrastructure.publishers.balancer_job_publisher import BalancerJobPublisher
from src.infrastructure.repositories.job_store_repository import JobStoreRepository
from src.infrastructure.security.api_key_limiter import get_api_key_limiter
from src.infrastructure.security.workspace_access_policy import WorkspaceAccessPolicy
from src.infrastructure.solvers.moo_balance_solver import MooBalanceSolver

registration_service = RegistrationAdminGateway()
balancer_service = BalancerAdminGateway()
status_service = RegistrationStatusGateway()
team_gateway = TeamGateway()


def build_public_http_use_cases(*, broker, logger):
    job_repository = JobStoreRepository()
    access_policy = WorkspaceAccessPolicy()
    api_key_limiter = get_api_key_limiter()

    return SimpleNamespace(
        get_config=GetBalancerConfig(config_provider=BalancerConfigService()),
        create_job=CreateBalanceJob(
            access_policy=access_policy,
            payload_parser=BalancerRequestParser(),
            job_repository=job_repository,
            publisher=BalancerJobPublisher(broker, logger),
            api_key_limiter=api_key_limiter,
        ),
        get_job_status=GetBalanceJobStatus(
            job_repository=job_repository,
            access_policy=access_policy,
            api_key_limiter=api_key_limiter,
        ),
        get_job_result=GetBalanceJobResult(
            job_repository=job_repository,
            access_policy=access_policy,
            api_key_limiter=api_key_limiter,
        ),
        stream_job_events=StreamBalanceJobEvents(
            job_repository=job_repository,
            access_policy=access_policy,
            api_key_limiter=api_key_limiter,
        ),
    )


def build_execute_balance_job_use_case(*, broker) -> ExecuteBalanceJob:
    return ExecuteBalanceJob(
        job_repository=JobStoreRepository(),
        solver=MooBalanceSolver(),
    )


def build_admin_registration_use_cases():
    return SimpleNamespace(
        get_registration_form=GetRegistrationForm(),
        upsert_registration_form=UpsertRegistrationForm(registration_service=registration_service),
        list_registrations=ListRegistrations(registration_service=registration_service),
        create_registration=CreateRegistration(registration_service=registration_service),
        update_registration=UpdateRegistration(registration_service=registration_service),
        approve_registration=ApproveRegistration(registration_service=registration_service),
        reject_registration=RejectRegistration(registration_service=registration_service),
        set_registration_exclusion=SetRegistrationExclusion(registration_service=registration_service),
        withdraw_registration=WithdrawRegistration(registration_service=registration_service),
        restore_registration=RestoreRegistration(registration_service=registration_service),
        delete_registration=DeleteRegistration(registration_service=registration_service),
        bulk_approve_registrations=BulkApproveRegistrations(registration_service=registration_service),
        set_balancer_status=SetBalancerStatus(registration_service=registration_service),
        bulk_add_to_balancer=BulkAddToBalancer(registration_service=registration_service),
        toggle_check_in=ToggleCheckIn(registration_service=registration_service),
        export_registrations_to_users=ExportRegistrationsToUsers(registration_service=registration_service),
    )


def build_admin_balancer_use_cases():
    return SimpleNamespace(
        get_tournament_sheet=GetTournamentSheet(registration_service=registration_service),
        upsert_tournament_sheet=UpsertTournamentSheet(registration_service=registration_service),
        sync_tournament_sheet=SyncTournamentSheet(registration_service=registration_service),
        suggest_tournament_sheet_mapping=SuggestTournamentSheetMapping(registration_service=registration_service),
        preview_tournament_sheet_mapping=PreviewTournamentSheetMapping(registration_service=registration_service),
        list_applications=ListApplications(balancer_service=balancer_service),
        create_players_from_applications=CreatePlayersFromApplications(balancer_service=balancer_service),
        list_players=ListPlayers(balancer_service=balancer_service),
        update_player=UpdatePlayer(balancer_service=balancer_service),
        delete_player=DeletePlayer(balancer_service=balancer_service),
        preview_player_import=PreviewPlayerImport(balancer_service=balancer_service),
        import_players=ImportPlayers(balancer_service=balancer_service),
        export_players=ExportPlayers(registration_service=registration_service),
        sync_player_roles_from_applications=SyncPlayerRolesFromApplications(balancer_service=balancer_service),
        export_applications_to_users=ExportApplicationsToUsers(balancer_service=balancer_service),
        get_tournament_config=GetTournamentConfig(balancer_service=balancer_service),
        upsert_tournament_config=UpsertTournamentConfig(balancer_service=balancer_service),
        get_saved_balance=GetSavedBalance(balancer_service=balancer_service),
        save_balance=SaveBalance(balancer_service=balancer_service),
        export_balance=ExportBalance(balancer_service=balancer_service),
        import_teams_from_json=ImportTeamsFromJson(team_flows=team_gateway),
        get_workspace_balancer_config=GetWorkspaceBalancerConfig(balancer_service=balancer_service),
        upsert_workspace_balancer_config=UpsertWorkspaceBalancerConfig(balancer_service=balancer_service),
    )


def build_registration_status_use_cases():
    return SimpleNamespace(
        list_status_catalog=ListStatusCatalog(status_service=status_service),
        list_custom_statuses=ListCustomStatuses(status_service=status_service),
        create_custom_status=CreateCustomStatus(status_service=status_service),
        update_custom_status=UpdateCustomStatus(status_service=status_service),
        delete_custom_status=DeleteCustomStatus(status_service=status_service),
        upsert_builtin_override=UpsertBuiltinOverride(status_service=status_service),
        reset_builtin_override=ResetBuiltinOverride(status_service=status_service),
    )


def build_due_registration_sheet_sync_use_case():
    return SyncDueRegistrationSheets(registration_service=registration_service)

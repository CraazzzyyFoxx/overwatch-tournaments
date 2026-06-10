from __future__ import annotations

from types import SimpleNamespace

from src.application.admin.balancer_use_cases import (
    ExportBalance,
    GetSavedBalance,
    GetTournamentConfig,
    GetWorkspaceBalancerConfig,
    ImportTeamsFromJson,
    SaveBalance,
    UpsertTournamentConfig,
    UpsertWorkspaceBalancerConfig,
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
    TeamGateway,
)
from src.infrastructure.parsers.balancer_request_parser import BalancerRequestParser
from src.infrastructure.publishers.balancer_job_publisher import BalancerJobPublisher
from src.infrastructure.repositories.job_store_repository import JobStoreRepository
from src.infrastructure.security.api_key_limiter import get_api_key_limiter
from src.infrastructure.security.workspace_access_policy import WorkspaceAccessPolicy
from src.infrastructure.solvers.moo_balance_solver import MooBalanceSolver

balancer_service = BalancerAdminGateway()
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


def build_admin_balancer_use_cases():
    return SimpleNamespace(
        get_tournament_config=GetTournamentConfig(balancer_service=balancer_service),
        upsert_tournament_config=UpsertTournamentConfig(balancer_service=balancer_service),
        get_saved_balance=GetSavedBalance(balancer_service=balancer_service),
        save_balance=SaveBalance(balancer_service=balancer_service),
        export_balance=ExportBalance(balancer_service=balancer_service),
        import_teams_from_json=ImportTeamsFromJson(team_flows=team_gateway),
        get_workspace_balancer_config=GetWorkspaceBalancerConfig(balancer_service=balancer_service),
        upsert_workspace_balancer_config=UpsertWorkspaceBalancerConfig(balancer_service=balancer_service),
    )

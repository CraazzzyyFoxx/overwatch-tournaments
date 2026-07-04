from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    "app-service",
    "auth-service",
    "balancer-service",
    "discord-service",
    "parser-service",
    "realtime-service",
    "tournament-service",
    "analytics-service",
    "shared",
)

DIRECT_WRITE_RE = re.compile(
    r"session\.(?:add|add_all|delete|merge)\(|await session\.get\(|sa\.(?:insert|update|delete)\("
)

APPROVED_DIRECT_WRITE_FILES = {
    "analytics-service/src/services/analytics/flows.py",
    "analytics-service/src/services/analytics_read/service.py",
    "analytics-service/src/services/jobs/service.py",
    "analytics-service/src/services/ml/inference/match_quality_runner.py",
    "analytics-service/src/services/ml/inference/player_anomaly_runner.py",
    "analytics-service/src/services/ml/inference/runner.py",
    "analytics-service/src/services/ml/training/registry.py",
    "analytics-service/src/worker/balance_snapshot.py",
    "app-service/src/routes/assets.py",
    "app-service/src/routes/registration.py",
    "app-service/src/services/division_grid/marketplace.py",
    "app-service/src/services/division_grid/service.py",
    "app-service/src/services/registration/service.py",
    "app-service/src/services/workspace/service.py",
    "auth-service/src/routes/auth.py",
    "auth-service/src/routes/oauth.py",
    "auth-service/src/routes/player.py",
    "auth-service/src/routes/rbac.py",
    "auth-service/src/services/auth_service.py",
    "auth-service/src/services/oauth_service.py",
    "auth-service/src/services/player_link_service.py",
    "balancer-service/src/application/admin/registration_use_cases.py",
    "balancer-service/src/services/admin/balance_analytics.py",
    "balancer-service/src/services/admin/balancer.py",
    "balancer-service/src/services/admin/balancer_dual_write.py",
    "balancer-service/src/services/admin/balancer_registration.py",
    "balancer-service/src/services/admin/registration_status.py",
    "balancer-service/src/services/team.py",
    "balancer-service/src/services/user.py",
    "parser-service/src/routes/achievement.py",
    "parser-service/src/routes/admin/achievement_rule.py",
    "parser-service/src/routes/admin/discord_channel.py",
    "parser-service/src/services/achievement/engine/differ.py",
    "parser-service/src/services/achievement/engine/runner.py",
    "parser-service/src/services/achievement/engine/seeder.py",
    "parser-service/src/services/achievement/import_export.py",
    "parser-service/src/services/admin/encounter.py",
    "parser-service/src/services/admin/player_sub_role.py",
    "parser-service/src/services/admin/stage.py",
    "parser-service/src/services/admin/standing.py",
    "parser-service/src/services/admin/team.py",
    "parser-service/src/services/admin/tournament.py",
    "parser-service/src/services/admin/user.py",
    "parser-service/src/services/admin/user_merge.py",
    "parser-service/src/services/challonge/sync.py",
    "parser-service/src/services/encounter/map_veto.py",
    "parser-service/src/services/encounter/service.py",
    "parser-service/src/services/gamemode/service.py",
    "parser-service/src/services/hero/service.py",
    "parser-service/src/services/map/service.py",
    "parser-service/src/services/match_logs/flows.py",
    "parser-service/src/services/match_logs/log_records.py",
    "parser-service/src/services/standings/service.py",
    "parser-service/src/services/team/flows.py",
    "parser-service/src/services/team/service.py",
    "parser-service/src/services/tournament/service.py",
    "parser-service/src/services/user/service.py",
    "shared/messaging/outbox.py",
    "shared/rbac/bootstrap.py",
    "shared/services/bracket/advancement.py",
    "shared/services/division_grid_access.py",
    "shared/services/realtime_publisher.py",
    "shared/services/stage_refs.py",
    "tournament-service/src/routes/admin/registration.py",
    "tournament-service/src/routes/admin/registration_status.py",
    "tournament-service/src/routes/registration.py",
    "tournament-service/src/services/admin/encounter.py",
    "tournament-service/src/services/admin/player_sub_role.py",
    "tournament-service/src/services/admin/stage.py",
    "tournament-service/src/services/admin/standing.py",
    "tournament-service/src/services/admin/team.py",
    "tournament-service/src/services/admin/tournament.py",
    "tournament-service/src/services/challonge/sync.py",
    "tournament-service/src/services/encounter/map_veto.py",
    "tournament-service/src/services/encounter/service.py",
    "tournament-service/src/services/registration/admin.py",
    "tournament-service/src/services/registration/admin_use_cases.py",
    "tournament-service/src/services/registration/service.py",
    "tournament-service/src/services/registration/status_catalog.py",
    "tournament-service/src/services/standings/service.py",
    "tournament-service/src/services/tournament/realtime_commit.py",
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = BACKEND_ROOT / root_name
        if not root.exists():
            continue
        files.extend(
            path
            for path in root.rglob("*.py")
            if "tests" not in path.parts and "__pycache__" not in path.parts
        )
    return files


def test_new_direct_db_writes_go_through_shared_repositories() -> None:
    offenders: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative.startswith("shared/repository/"):
            continue
        if relative in APPROVED_DIRECT_WRITE_FILES:
            continue
        if DIRECT_WRITE_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(relative)

    assert offenders == []

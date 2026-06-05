from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from faststream import FastStream
from fastapi.routing import APIRoute


def _import_serve():
    backend_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(backend_root))
    sys.path.insert(0, str(backend_root / "parser-service"))

    os.environ["DEBUG"] = "true"
    os.environ.setdefault("PROJECT_URL", "http://localhost")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
    os.environ.setdefault("POSTGRES_USER", "postgres")
    os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
    os.environ.setdefault("POSTGRES_DB", "postgres")
    os.environ.setdefault("POSTGRES_HOST", "localhost")
    os.environ.setdefault("POSTGRES_PORT", "5432")
    os.environ.setdefault("S3_ACCESS_KEY", "test")
    os.environ.setdefault("S3_SECRET_KEY", "test")
    os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
    os.environ.setdefault("S3_BUCKET_NAME", "test")
    os.environ.setdefault("CHALLONGE_USERNAME", "test")
    os.environ.setdefault("CHALLONGE_API_KEY", "test")

    return importlib.import_module("serve")


def test_serve_module_exposes_faststream_app() -> None:
    serve = _import_serve()

    assert isinstance(serve.app, FastStream)


def test_serve_module_leaves_tournament_worker_queues_to_tournament_service() -> None:
    serve = _import_serve()

    queue_names = {subscriber.queue.name for subscriber in serve.broker.subscribers}

    assert "tournament_encounter_completed" in queue_names
    assert "swiss_next_round" not in queue_names
    assert "tournament_recalc" not in queue_names
    assert not hasattr(serve, "scheduler")


def _route_paths(router) -> set[str]:
    return {route.path for route in router.routes if isinstance(route, APIRoute)}


def test_parser_api_unmounts_cutover_tournament_routes() -> None:
    _import_serve()
    routes = importlib.import_module("src.routes")
    admin_routes = importlib.import_module("src.routes.admin")

    public_paths = _route_paths(routes.router)
    admin_paths = _route_paths(admin_routes.admin_router)

    assert "/encounters/{encounter_id}/submit-result" not in public_paths
    assert "/encounters/{encounter_id}/map-pool" not in public_paths
    assert "/tournament/create/with_groups" in public_paths
    assert "/teams/create/balancer" in public_paths
    assert "/encounter/challonge" in public_paths

    allowed_parser_admin_tournament_paths = {
        "/admin/tournaments/{tournament_id}/discord-channel",
    }
    removed_admin_prefixes = (
        "/admin/tournaments",
        "/admin/stages",
        "/admin/teams",
        "/admin/encounters",
        "/admin/standings",
        "/admin/player-sub-roles",
    )
    unexpected_admin_paths = admin_paths - allowed_parser_admin_tournament_paths
    assert not any(path.startswith(removed_admin_prefixes) for path in unexpected_admin_paths)
    assert "/admin/tournaments/{tournament_id}/discord-channel" in admin_paths
    assert "/admin/players" in admin_paths

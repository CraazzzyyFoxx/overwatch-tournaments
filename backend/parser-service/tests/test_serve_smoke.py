from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from faststream import FastStream


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


def test_serve_registers_parser_unique_rpc_subjects() -> None:
    """The FastAPI HTTP face was removed; the parser-unique admin/read surface now
    runs as ``rpc.parser.*`` FastStream subscribers registered in ``serve.py``."""
    serve = _import_serve()

    subjects = {
        getattr(subscriber, "subject", None) or getattr(getattr(subscriber, "queue", None), "name", None)
        for subscriber in serve.broker.subscribers
    }

    assert "rpc.parser.logs.upload" in subjects
    assert "rpc.parser.logs.history" in subjects
    assert "rpc.parser.rank.user_history" in subjects
    assert "rpc.parser.ach.calculate" in subjects

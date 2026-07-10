from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

# ``src.services.match_logs.flows`` imports ``src.core.config.settings`` at
# module load, which reads these from the environment (see test_match_log_parser).
os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from src.services.match_logs import impact  # noqa: E402
from src.services.match_logs.flows import MatchLogProcessor  # noqa: E402


def test_create_stats_accepts_kill_feed():
    sig = inspect.signature(MatchLogProcessor.create_stats)
    assert "kill_feed" in sig.parameters


def test_impact_context_shape():
    ctx = impact.ImpactContext(players={}, baselines=None, has_killfeed=False)
    assert ctx.baselines is None

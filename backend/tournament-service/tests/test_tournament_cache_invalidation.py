from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

cache_invalidation = importlib.import_module("src.services.tournament.cache_invalidation")


class TournamentCacheInvalidationTests(TestCase):
    def test_bracket_change_invalidates_encounters_only(self) -> None:
        patterns = cache_invalidation.tournament_cache_patterns(42, "bracket_changed")

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertTrue(any("encounters*:None:" in pattern for pattern in patterns))
        self.assertFalse(any("tournaments/42" in pattern for pattern in patterns))
        self.assertFalse(any("teams" in pattern for pattern in patterns))

    def test_results_change_invalidates_all_tournament_reads(self) -> None:
        patterns = cache_invalidation.tournament_cache_patterns(42, "results_changed")

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertTrue(any("tournaments/42" in pattern for pattern in patterns))
        self.assertTrue(any("teams" in pattern for pattern in patterns))

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

admin_stage_schemas = importlib.import_module("src.schemas.admin.stage")
enums = importlib.import_module("shared.core.enums")


class StageMaxRoundsTests(TestCase):
    def test_stage_create_defaults_max_rounds_to_five(self) -> None:
        data = admin_stage_schemas.StageCreate(
            name="Swiss",
            stage_type=enums.StageType.SWISS,
        )

        self.assertEqual(5, data.max_rounds)

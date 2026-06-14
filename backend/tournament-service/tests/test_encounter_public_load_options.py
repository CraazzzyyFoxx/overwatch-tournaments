from __future__ import annotations

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

from src.services.encounter import service  # noqa: E402


class EncounterLoadOptionTests(TestCase):
    def test_stage_load_options_stay_summary_only(self) -> None:
        paths = "\n".join(
            str(getattr(option, "path", ""))
            for option in service.encounter_entities(["stage", "stage_item"])
        )

        self.assertIn("Encounter.stage", paths)
        self.assertIn("Encounter.stage_item", paths)
        self.assertNotIn("Stage.items", paths)
        self.assertNotIn("StageItem.inputs", paths)

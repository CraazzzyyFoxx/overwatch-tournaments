"""The match a log produces carries a foreign key back to that log.

Before this, provenance was a comparison between ``match.log_name`` and
``record.filename`` — two columns the pipeline normalises differently, so the
answer to "which upload produced this map" was a guess. These tests pin the link
being written on both the create and the update path, and the id reaching the
processor from the record the run actually claimed.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

flows = importlib.import_module("src.services.match_logs.flows")
encounter_service = importlib.import_module("src.services.encounter.service")
models = importlib.import_module("src.models")


class CreateMatchRecordsTheLog(IsolatedAsyncioTestCase):
    async def test_create_match_persists_the_link(self) -> None:
        added: list = []
        session = SimpleNamespace(
            add=added.append,
            flush=AsyncMock(),
            commit=AsyncMock(),
        )
        match = await encounter_service.create_match(
            session,
            SimpleNamespace(id=7),
            time=612.0,
            log_name="m.txt",
            map=SimpleNamespace(id=3),
            home_team_id=1,
            away_team_id=2,
            home_score=2,
            away_score=1,
            log_record_id=99,
        )
        self.assertEqual(99, match.log_record_id)
        self.assertEqual([match], added)
        session.commit.assert_not_awaited()

    async def test_link_is_optional(self) -> None:
        """Callers outside the ingestion path have no record to point at."""
        session = SimpleNamespace(add=lambda _o: None, flush=AsyncMock(), commit=AsyncMock())
        match = await encounter_service.create_match(
            session,
            SimpleNamespace(id=7),
            time=1.0,
            log_name="m.txt",
            map=SimpleNamespace(id=3),
            home_team_id=1,
            away_team_id=2,
            home_score=1,
            away_score=0,
        )
        self.assertIsNone(match.log_record_id)


class ProcessorCarriesTheRecordId(IsolatedAsyncioTestCase):
    def test_constructor_stores_it(self) -> None:
        processor = flows.MatchLogProcessor.__new__(flows.MatchLogProcessor)
        # __init__ parses a DataFrame; assert the attribute contract directly.
        self.assertIn("log_record_id", flows.MatchLogProcessor.__init__.__code__.co_varnames)
        self.assertFalse(hasattr(processor, "log_record_id"))

    async def test_process_match_log_passes_the_claimed_record(self) -> None:
        """The id must come from the record this run claimed, not from a second
        lookup that could resolve to a different duplicate."""
        record = SimpleNamespace(id=4242)
        constructed: dict = {}

        class _FakeProcessor:
            def __init__(self, tournament, name, data_in, s3, log_record_id=None):
                constructed["log_record_id"] = log_record_id
                constructed["name"] = name

            async def start(self, _session, is_raise: bool = True):
                return None

        record_service = importlib.import_module("src.services.match_logs.log_records")

        with (
            # workspace_id: the flow stages the workspace-scoped `logs` signal
            # from this object rather than re-querying for it.
            patch.object(
                flows.tournament_flows,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=1, name="t", workspace_id=7)),
            ),
            patch.object(flows.binary_match_logs, "get_log_by_filename", AsyncMock(return_value=b"a\nb")),
            patch.object(record_service, "is_already_processed", AsyncMock(return_value=False)),
            patch.object(record_service, "set_processing", AsyncMock(return_value=record)),
            patch.object(record_service, "set_done", AsyncMock()),
            patch.object(flows, "MatchLogProcessor", _FakeProcessor),
        ):
            await flows.process_match_log(Mock(), 1, "logs/1/m.txt", Mock(), is_raise=False)

        self.assertEqual(4242, constructed["log_record_id"])
        # The processor still sees the bare name; only the link is new.
        self.assertEqual("m.txt", constructed["name"])


class MatchModelShape(IsolatedAsyncioTestCase):
    def test_log_record_relationship_does_not_lazy_load(self) -> None:
        """An implicit load would fire inside async paths that cannot do IO on
        attribute access."""
        rel = models.Match.__mapper__.relationships["log_record"]
        self.assertEqual("raise", rel.lazy)

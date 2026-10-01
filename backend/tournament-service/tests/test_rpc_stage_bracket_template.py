"""The three bracket-template subjects: permission gate, audit row, error shape.

``AdminStageService.get/set/clear_bracket_template`` already have their own
service-level suite (``test_admin_stage_bracket_template.py``); what is untested
there is the RPC seam the gateway actually calls: which workspace grant each
subject demands, that the mutating two stage an audit row *before* the service
commits (so a refused write leaves no row), and that the service's 422 — a dict
detail WITHOUT ``msg``, carrying ``problems`` — survives ``_run``'s mapping as
``details["fields"][0]`` instead of reaching the browser as a Python repr.

No database and no broker: the handlers are driven through ``CapturingBroker``
with the service stubbed, the way the other rpc suites in this directory do it.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from shared.core.errors import BaseAPIException  # noqa: E402
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

stage_admin = importlib.import_module("src.rpc.stage_admin")
helpers = importlib.import_module("src.rpc._helpers")

WORKSPACE_ID = 4
STAGE_ID = 31

#: The template the editor draws for a 2+2 double elimination, in the exact
#: shape ``BracketTemplate`` accepts -- the handler validates the body itself.
TEMPLATE = {
    "version": 1,
    "upper_seeds": 2,
    "lower_seeds": 2,
    "matches": [
        {"id": 0, "round": 1, "home": {"seed": "U1"}, "away": {"seed": "U2"}},
        {"id": 1, "round": -1, "home": {"seed": "L1"}, "away": {"seed": "L2"}},
        {"id": 2, "round": -2, "home": {"winner_of": 1}, "away": {"loser_of": 0}},
        {"id": 3, "round": 2, "home": {"winner_of": 0}, "away": {"winner_of": 2}},
    ],
}

READ = {"custom": False, "template": TEMPLATE, "seeds": {"upper": 2, "lower": 2}}


def _identity(*actions: str) -> dict[str, Any]:
    return make_identity(
        username="organizer",
        workspaces=[
            {
                "workspace_id": WORKSPACE_ID,
                "rbac_roles": [],
                "rbac_permissions": [{"resource": "stage", "action": action} for action in actions],
            }
        ],
    )


class _FakeSession:
    """Records the ordered trace of audit writes and the service call."""

    def __init__(self, trace: list[str]) -> None:
        self.rows: list[Any] = []
        self.trace = trace

    def add(self, row: Any) -> None:
        self.rows.append(row)
        self.trace.append("audit")

    async def commit(self) -> None:  # pragma: no cover - the service stub commits for us
        self.trace.append("commit")

    async def flush(self) -> None:  # pragma: no cover - not reached by these paths
        pass


class StageBracketTemplateRpcTests(IsolatedAsyncioTestCase):
    async def _invoke(
        self,
        subject: str,
        data: dict[str, Any],
        *,
        service_attr: str,
        result: Any = READ,
        error: BaseAPIException | None = None,
    ) -> tuple[dict[str, Any], _FakeSession, list[str], list[tuple]]:
        broker = CapturingBroker()
        stage_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        trace: list[str] = []
        session = _FakeSession(trace)
        calls: list[tuple] = []

        async def fake_ws_id(_session, _stage_id):
            return WORKSPACE_ID

        async def fake_service(*args, **kwargs):
            trace.append("service")
            calls.append((args[1:], kwargs))
            if error is not None:
                raise error
            trace.append("commit")
            return result

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(stage_admin.auth, "get_stage_workspace_id", fake_ws_id),
            patch.object(stage_admin.stage_service, service_attr, fake_service),
        ):
            envelope = await broker.handlers[subject](data, None)
        return envelope, session, trace, calls

    # ── GET ───────────────────────────────────────────────────────────────

    async def test_get_returns_the_template_and_writes_no_audit_row(self):
        envelope, session, _, calls = await self._invoke(
            "rpc.tournament.stage_bracket_template_get",
            {"identity": _identity("read"), "stage_id": STAGE_ID},
            service_attr="get_bracket_template",
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertIs(False, envelope["data"]["custom"])
        self.assertEqual(TEMPLATE, envelope["data"]["template"])
        self.assertEqual({"upper": 2, "lower": 2}, envelope["data"]["seeds"])
        self.assertEqual([(STAGE_ID,), {}], [calls[0][0], calls[0][1]])
        self.assertEqual([], session.rows)

    async def test_get_needs_stage_read(self):
        envelope, _, trace, _ = await self._invoke(
            "rpc.tournament.stage_bracket_template_get",
            {"identity": _identity("update"), "stage_id": STAGE_ID},
            service_attr="get_bracket_template",
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], trace)

    # ── PUT ───────────────────────────────────────────────────────────────

    async def test_set_stages_the_audit_row_before_the_service_commits(self):
        envelope, session, trace, calls = await self._invoke(
            "rpc.tournament.stage_bracket_template_set",
            {"identity": _identity("update"), "stage_id": STAGE_ID, "payload": TEMPLATE},
            service_attr="set_bracket_template",
            result={"custom": True, "template": TEMPLATE, "seeds": {"upper": 2, "lower": 2}},
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertIs(True, envelope["data"]["custom"])
        self.assertEqual(["audit", "service", "commit"], trace)

        self.assertEqual(1, len(session.rows))
        row = session.rows[0]
        self.assertEqual("stage.bracket_template.set", row.action)
        self.assertEqual("stage", row.entity_type)
        self.assertEqual(STAGE_ID, row.entity_id)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual({"upper_seeds": 2, "lower_seeds": 2, "matches": 4}, row.after_json)

        # The body reached the service as a parsed model, not a dict.
        (stage_id, template), _kwargs = calls[0]
        self.assertEqual(STAGE_ID, stage_id)
        self.assertEqual(2, template.upper_seeds)
        self.assertEqual(4, len(template.matches))

    async def test_set_needs_stage_update(self):
        envelope, session, _, _ = await self._invoke(
            "rpc.tournament.stage_bracket_template_set",
            {"identity": _identity("read"), "stage_id": STAGE_ID, "payload": TEMPLATE},
            service_attr="set_bracket_template",
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], session.rows)

    async def test_set_relays_the_validators_problems_per_field(self):
        problems = [
            {"match_id": 3, "slot": "away", "code": "unknown_match", "message": "away points at no match"},
            {"match_id": None, "slot": None, "code": "seed_unused", "message": "L2 is never used"},
        ]
        envelope, _, _, _ = await self._invoke(
            "rpc.tournament.stage_bracket_template_set",
            {"identity": _identity("update"), "stage_id": STAGE_ID, "payload": TEMPLATE},
            service_attr="set_bracket_template",
            error=BaseAPIException(
                status_code=422,
                detail={
                    "code": "invalid_bracket_template",
                    "message": "bracket template has 2 problem(s)",
                    "problems": problems,
                },
            ),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"])
        field = envelope["error"]["details"]["fields"][0]
        self.assertEqual("invalid_bracket_template", field["code"])
        self.assertEqual(problems, field["problems"])

    async def test_set_rejects_a_body_the_model_refuses(self):
        envelope, session, trace, _ = await self._invoke(
            "rpc.tournament.stage_bracket_template_set",
            {
                "identity": _identity("update"),
                "stage_id": STAGE_ID,
                # Both origins set: ``TemplateSlot`` takes exactly one.
                "payload": {
                    "version": 1,
                    "upper_seeds": 2,
                    "lower_seeds": 0,
                    "matches": [{"id": 0, "round": 1, "home": {"seed": "U1", "winner_of": 0}, "away": {"seed": "U2"}}],
                },
            },
            service_attr="set_bracket_template",
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"])
        # Refused before anything was staged: no audit row, no service call.
        self.assertEqual([], trace)
        self.assertEqual([], session.rows)

    # ── DELETE ────────────────────────────────────────────────────────────

    async def test_clear_audits_then_returns_the_generated_template(self):
        envelope, session, trace, calls = await self._invoke(
            "rpc.tournament.stage_bracket_template_clear",
            {"identity": _identity("update"), "stage_id": STAGE_ID},
            service_attr="clear_bracket_template",
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertIs(False, envelope["data"]["custom"])
        self.assertEqual(["audit", "service", "commit"], trace)
        self.assertEqual((STAGE_ID,), calls[0][0])

        self.assertEqual(1, len(session.rows))
        row = session.rows[0]
        self.assertEqual("stage.bracket_template.clear", row.action)
        self.assertEqual("stage", row.entity_type)
        self.assertEqual(STAGE_ID, row.entity_id)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)

    async def test_clear_needs_stage_update(self):
        envelope, session, _, _ = await self._invoke(
            "rpc.tournament.stage_bracket_template_clear",
            {"identity": _identity("read"), "stage_id": STAGE_ID},
            service_attr="clear_bracket_template",
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], session.rows)

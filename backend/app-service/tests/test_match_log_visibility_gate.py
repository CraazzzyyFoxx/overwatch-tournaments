"""``rpc.app.matches.log`` had no permission or visibility check at all: any
authenticated account could download any match's raw log by iterating match
ids, including matches from hidden tournaments -- the gateway route only
required a session (``AuthRequired``), and the handler itself read no
identity. Fixed by splitting the DB lookup from the S3 fetch and gating
tournament visibility (the same check every other public read in this
service uses) strictly between them.
"""

from __future__ import annotations

import inspect
from unittest import TestCase

from src.rpc import binary


class MatchLogVisibilityGateTests(TestCase):
    """A public download endpoint for a resource that can belong to a hidden
    tournament must not hand out bytes before checking visibility."""

    def _handler_source(self) -> str:
        source = inspect.getsource(binary)
        start = source.index('@broker.subscriber("rpc.app.matches.log")')
        end = source.index('c.envelope(logger, "matches.log"', start)
        return source[start:end]

    def test_visibility_is_gated_between_the_db_lookup_and_the_s3_fetch(self) -> None:
        """``resolve_match_log_ref`` only touches the DB; ``fetch_log_bytes`` is
        the S3 round trip. ``gate_tournament`` must run strictly between them --
        never before (it needs the resolved tournament id) and never after
        (the bytes would already be out the door)."""
        source = self._handler_source()

        resolve_at = source.index("resolve_match_log_ref(")
        gate_at = source.index("gate_tournament(")
        fetch_at = source.index("fetch_log_bytes(")

        self.assertLess(resolve_at, gate_at)
        self.assertLess(gate_at, fetch_at)

    def test_the_gate_is_the_shared_tournament_visibility_check(self) -> None:
        """Not a bespoke permission check: the same ``gate_tournament`` helper
        every other public, non-workspace-scoped read in this service uses, so
        a hidden/preview-only tournament's logs are exactly as reachable as the
        rest of that tournament -- no stricter, no laxer."""
        source = self._handler_source()

        self.assertIn("await c.gate_tournament(session, data, tournament_id)", source)

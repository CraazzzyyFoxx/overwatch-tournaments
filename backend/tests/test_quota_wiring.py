"""A service that meters must also configure the meter.

``shared.quota`` is a process-global: a service that charges without calling
``configure`` raises ``RuntimeError`` on its first metered request. That is
loud, but it is loud in production rather than here, and the failure mode is
asymmetric -- forgetting the call in a new service means its expensive
operations are simply never accounted, which nothing else in the suite would
notice. Text parsing, so this needs no imports and no running services.
"""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[1]

CHARGE_CALLS = ("quota.charge(", "quota.lease(", "quota.check_payload(")
#: An entrypoint is any top-level module in the service directory: analytics
#: hosts its RPC subjects from ``serve_rpc.py`` and its heavy compute from
#: ``serve.py``, and only the former meters anything, so the scan cannot assume
#: a single filename.


def _service_dirs() -> list[Path]:
    return sorted(path.parent for path in BACKEND_ROOT.glob("*-service/src") if path.is_dir())


def _meters(service: Path) -> bool:
    for path in (service / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(call in text for call in CHARGE_CALLS):
            return True
    return False


def _configures(service: Path) -> bool:
    for entrypoint in sorted(service.glob("*.py")):
        text = entrypoint.read_text(encoding="utf-8")
        if "quota" in text and "configure" in text:
            return True
    return False


class QuotaWiringTests(TestCase):
    def test_the_scan_finds_services_at_all(self) -> None:
        """Guards the guard: an empty scan would make the check below vacuous."""
        self.assertGreaterEqual(len(_service_dirs()), 8)

    def test_every_metering_service_configures_the_gate(self) -> None:
        metering = [service for service in _service_dirs() if _meters(service)]
        self.assertNotEqual([], metering, "no service meters anything; the quota gate is unwired")
        unconfigured = [service.name for service in metering if not _configures(service)]
        self.assertEqual([], unconfigured, "services that charge quota without calling quota.configure()")

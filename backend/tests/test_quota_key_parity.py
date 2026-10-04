"""The per-minute request buckets are written in Go and read in Python.

The gateway spends ``q:key:{id}:rpm`` on every keyed request (and, with edge
workspace metering, ``q:ws:{id}:rpm`` / ``q:pub:ws:{id}:rpm``) in
``gateway/internal/ratelimit/redis.go``; ``shared/quota/enforcer.py`` reports
them in the usage view and, for a workspace without edge metering, charges the
workspace bucket itself on metered calls.

Which makes the key strings a cross-language contract with no compiler behind
them: rename a namespace on either side and nothing breaks loudly — the usage
view shows a permanent zero, or two layers count one tenant into two buckets.
Text parsing, so this needs no Go toolchain.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import TestCase

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

RATELIMIT_GO = REPO_ROOT / "gateway" / "internal" / "ratelimit" / "redis.go"

from shared.quota.enforcer import RPM_WINDOW_SECONDS, QuotaEnforcer, _namespace  # noqa: E402

_KEY_FORMAT_RE = re.compile(r'const\s+rpmKeyFormat\s*=\s*"([^"]+)"')
_WS_KEY_FORMAT_RE = re.compile(r'const\s+wsRPMKeyFormat\s*=\s*"([^"]+)"')
_PUBLIC_KEY_FORMAT_RE = re.compile(r'const\s+publicRPMKeyFormat\s*=\s*"([^"]+)"')
_WINDOW_RE = re.compile(r"const\s+rpmWindow\s*=\s*(\d+)\s*\*\s*time\.Second")

#: Any id: the format, not the number, is what has to agree.
API_KEY_ID = 7


def _go_format(pattern: re.Pattern[str]) -> str:
    """A key template as the Go source declares it, or "" when unparseable."""
    match = pattern.search(RATELIMIT_GO.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def _go_key_format() -> str:
    """The gateway's per-API-key per-minute key template."""
    return _go_format(_KEY_FORMAT_RE)


def _go_window_seconds() -> int:
    """The gateway's window length in seconds, or 0 when unparseable."""
    match = _WINDOW_RE.search(RATELIMIT_GO.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else 0


class KeyParityTests(TestCase):
    def test_the_parser_finds_the_go_declarations(self) -> None:
        """Guards the guard: an empty parse would make everything below vacuous
        and the drift this file exists to catch invisible."""
        self.assertEqual("q:key:%s:rpm", _go_key_format())
        self.assertEqual(60, _go_window_seconds())

    def test_both_layers_charge_the_same_key(self) -> None:
        """One API key, one per-minute bucket: the one the gateway spends is the
        one the usage view reports."""
        go_key = _go_key_format().replace("%s", str(API_KEY_ID))
        python_key = QuotaEnforcer._rpm_key(_namespace("api_key"), API_KEY_ID)
        self.assertEqual(python_key, go_key)

    def test_the_api_key_namespace_is_key(self) -> None:
        """The Go format hardcodes the namespace (it only ever meters API keys),
        so a rename of the Python namespace must fail here rather than quietly
        split the bucket in two."""
        self.assertEqual("key", _namespace("api_key"))
        self.assertTrue(_go_key_format().startswith("q:key:"))

    def test_the_gateway_never_meters_the_session_namespace(self) -> None:
        """Session traffic is metered per user inside the workers only. If the
        gateway's key ever matched the user namespace, an API key's requests
        would come out of its owner's personal budget."""
        self.assertNotEqual(_namespace("user"), _namespace("api_key"))
        self.assertNotIn(f"q:{_namespace('user')}:", _go_key_format())

    def test_the_window_agrees(self) -> None:
        """Same key with two different expiries is worse than two keys: whoever
        writes it last decides when the budget resets."""
        self.assertEqual(RPM_WINDOW_SECONDS, _go_window_seconds())

    def test_the_workspace_bucket_is_one_key_across_both_layers(self) -> None:
        """With QUOTA_EDGE_WORKSPACE_METERING the gateway counts every request
        into the tenant's minute and the usage view reads it from Python: a
        drifted name would show a permanent zero and enforce nothing."""
        go_key = _go_format(_WS_KEY_FORMAT_RE).replace("%d", "42")
        self.assertEqual(QuotaEnforcer._rpm_key("ws", 42), go_key)

    def test_public_traffic_is_read_from_the_key_the_gateway_writes(self) -> None:
        go_key = _go_format(_PUBLIC_KEY_FORMAT_RE).replace("%d", "42")
        self.assertEqual(QuotaEnforcer._public_rpm_key(42), go_key)

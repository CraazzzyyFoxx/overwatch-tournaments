"""The per-API-key request bucket is charged from two languages.

``shared/quota/enforcer.py`` charges it inside every worker; the gateway charges
it in Redis before a request ever reaches one
(``gateway/internal/ratelimit/redis.go``). Both do that ON PURPOSE against the
SAME key, so a key's published requests_per_minute is one number rather than one
per layer.

Which makes the key string a cross-language contract with no compiler behind it:
rename the namespace on either side and nothing breaks loudly — every API key
just silently gets a second, full budget, and the limit published to customers
stops being true. Text parsing, so this needs no Go toolchain.
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
_WINDOW_RE = re.compile(r"const\s+rpmWindow\s*=\s*(\d+)\s*\*\s*time\.Second")

#: Any id: the format, not the number, is what has to agree.
API_KEY_ID = 7


def _go_key_format() -> str:
    """The gateway's per-minute key template, as the Go source declares it."""
    match = _KEY_FORMAT_RE.search(RATELIMIT_GO.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


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
        """The whole point: one API key, one per-minute bucket, whichever layer
        spends it."""
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

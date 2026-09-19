"""Cross-language drift guards for balancer algorithm configuration.

The Python side no longer needs guarding: ``AlgorithmConfig`` is the only place
a knob is declared, and the write allowlist, the limit table, the editable-field
catalog, the ``ConfigOverrides`` schema and ``ConfigPresets.DEFAULT`` are all
derived from it at import time. The six tests that used to compare those lists
are gone with the lists.

What is left is the link a type system cannot close: the hand-written native
request (``moo_backend._serialize_native_request``) against the Rust
``ConfigSpec``. A knob missed there silently falls back to a serde default --
the UI shows and saves the value while the solver ignores it, with no error
anywhere. Same for a roster slot code Rust does not recognise: its role-impact
weight is dropped on the floor.

Deliberately offline/deterministic: no DB, Redis or network.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from shared.domain.roster_shape import DEFAULT_ROSTER_SLOTS  # noqa: E402
from src.domain.balancer.moo_backend import _serialize_native_request  # noqa: E402
from src.services.balancer.config.defaults import AlgorithmConfig  # noqa: E402
from src.services.balancer.config.provider import get_balancer_config_payload  # noqa: E402


def _algorithm_field_names() -> set[str]:
    return set(AlgorithmConfig().model_dump().keys())


def test_config_payload_exposes_expected_top_level_keys() -> None:
    """``get_balancer_config_payload`` returns the stable public envelope."""
    payload = get_balancer_config_payload()

    assert isinstance(payload, dict)
    assert set(payload.keys()) == {"defaults", "limits", "presets", "fields"}


# ---------------------------------------------------------------------------
# Python <-> Rust ring: native payload <-> ConfigSpec
# ---------------------------------------------------------------------------

TOURNAMENT_BALANCER_LIB_RS = BALANCER_SERVICE_ROOT / "native" / "tournament_balancer" / "src" / "lib.rs"

# Present in ConfigSpec, deliberately never sent: the Rust doc-comment says
# "Принимается по wire опционально; в Python UI пока не выставляется".
RUST_ONLY_CONFIG_FIELDS = {"team_crossover_share"}


def _rust_config_spec_fields() -> tuple[set[str], set[str]]:
    """``(all_fields, fields_with_a_serde_default)`` parsed from ``ConfigSpec``.

    Textual parsing is the only option from Python, and it is the same genre as
    ``shared/tests/test_gateway_raw_sql_matches_models.py``: compare a
    hand-written artefact against its canon.
    """
    source = TOURNAMENT_BALANCER_LIB_RS.read_text(encoding="utf-8")
    assert "struct ConfigSpec {" in source, f"ConfigSpec not found in {TOURNAMENT_BALANCER_LIB_RS}"
    body = source.split("struct ConfigSpec {", 1)[1].split("\n}", 1)[0]

    all_fields: set[str] = set()
    defaulted: set[str] = set()
    pending_default = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("#[serde(default"):
            pending_default = True
            continue
        if not line or line.startswith("#[") or line.startswith("///"):
            continue
        match = re.match(r"([a-z_0-9]+)\s*:", line)
        if match is None:
            continue
        all_fields.add(match.group(1))
        if pending_default:
            defaulted.add(match.group(1))
        pending_default = False

    assert all_fields, "parsed no fields out of ConfigSpec — the parser or the struct changed"
    return all_fields, defaulted


def _native_payload_config_keys() -> set[str]:
    """Config keys the solver actually receives, read off a real payload."""
    request = json.loads(
        _serialize_native_request(
            players=[],
            num_teams=2,
            config=AlgorithmConfig(),
            role_assignment=None,
            seed=1,
        )
    )
    return set(request["config"].keys())


def test_every_non_defaulted_rust_config_field_is_sent() -> None:
    """A ConfigSpec field without ``#[serde(default)]`` MUST be in the payload.

    Omitting one is not a silent fallback but a hard deserialization failure of
    every balance job.
    """
    rust_fields, defaulted = _rust_config_spec_fields()
    required = rust_fields - defaulted
    missing = required - _native_payload_config_keys()

    assert missing == set(), (
        f"ConfigSpec requires {sorted(missing)} but _serialize_native_request "
        "does not send them — every balance job would fail to deserialize."
    )


def test_every_shared_python_rust_field_is_sent() -> None:
    """Every knob that exists on BOTH sides must actually cross the wire.

    This is the silent class: the field has a Rust ``serde`` default, so the job
    runs, the UI saves the value, and the solver optimizes against the default.
    """
    rust_fields, _ = _rust_config_spec_fields()
    shared = rust_fields & _algorithm_field_names()
    missing = shared - _native_payload_config_keys()

    assert missing == set(), (
        f"{sorted(missing)} exist in both AlgorithmConfig and Rust ConfigSpec but are "
        "not sent by _serialize_native_request: the UI would save a value the solver ignores."
    )


def test_native_payload_sends_no_unknown_config_keys() -> None:
    """Everything sent must exist in ConfigSpec (Rust denies unknown fields)."""
    rust_fields, _ = _rust_config_spec_fields()
    unknown = _native_payload_config_keys() - rust_fields

    assert unknown == set(), f"_serialize_native_request sends keys absent from ConfigSpec: {sorted(unknown)}"


def test_rust_only_config_fields_are_documented() -> None:
    """Guard the allowlist itself: a Rust-only field must be a known exception."""
    rust_fields, _ = _rust_config_spec_fields()
    undocumented = rust_fields - _native_payload_config_keys() - RUST_ONLY_CONFIG_FIELDS

    assert undocumented == set(), (
        f"ConfigSpec fields neither sent nor documented as Rust-only: {sorted(undocumented)}. "
        "Send them from _serialize_native_request or add them to RUST_ONLY_CONFIG_FIELDS with a reason."
    )


def test_rust_only_allowlist_has_no_stale_entries() -> None:
    """A field removed from ConfigSpec must leave the allowlist too."""
    rust_fields, _ = _rust_config_spec_fields()
    stale = RUST_ONLY_CONFIG_FIELDS - rust_fields

    assert stale == set(), f"RUST_ONLY_CONFIG_FIELDS lists fields no longer in ConfigSpec: {sorted(stale)}"


# ---------------------------------------------------------------------------
# Python <-> Rust ring: roster slot codes <-> role-impact index detection
# ---------------------------------------------------------------------------

TOURNAMENT_BALANCER_CONTEXT_RS = BALANCER_SERVICE_ROOT / "native" / "tournament_balancer" / "src" / "context.rs"


def _rust_role_idx_spellings() -> set[str]:
    """Role names ``Context::from_request`` recognises for the impact weights.

    Same genre as ``_rust_config_spec_fields`` above and as
    ``shared/tests/test_gateway_raw_sql_matches_models.py``: compare a canon
    against a hand-written artefact by reading it.
    """
    source = TOURNAMENT_BALANCER_CONTEXT_RS.read_text(encoding="utf-8")
    role_idx_block = "".join(line for line in source.splitlines(keepends=True) if "eq_ignore_ascii_case" in line)
    spellings = {match.lower() for match in re.findall(r'eq_ignore_ascii_case\("([^"]+)"\)', role_idx_block)}

    assert spellings, (
        f"parsed no role spellings out of {TOURNAMENT_BALANCER_CONTEXT_RS} — the parser or the file changed"
    )
    return spellings


def test_rust_recognizes_every_canonical_role_code() -> None:
    """A role code Rust does not recognise loses its impact weight silently.

    ``objectives.rs`` picks ``tank/damage/support_impact_weight`` by comparing the
    role index against ``Context.*_role_idx``; an unmatched spelling leaves the
    index ``None`` and the objective falls back to ``impact = 1.0`` with no
    error anywhere. Rust cannot be compiled on every dev machine (the crate
    builds on Linux only), so this text check is the cheap early warning.

    ``flex`` is deliberately NOT expected here: a slot with no role has no role
    impact weight, so ``impact = 1.0`` is the correct semantics for it, not a bug.
    """
    spellings = _rust_role_idx_spellings()

    unrecognized = {code for code in DEFAULT_ROSTER_SLOTS if code not in spellings}

    assert unrecognized == set(), (
        f"native/tournament_balancer/src/context.rs does not match roster slot codes {sorted(unrecognized)}: "
        "their impact weight would silently degrade to 1.0. Add the spelling to the "
        "matching *_role_idx lookup."
    )

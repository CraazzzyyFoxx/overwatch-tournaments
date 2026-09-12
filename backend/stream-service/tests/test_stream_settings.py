"""Guards on the stream-svc settings contract.

Two things that break silently in production if they drift:

1. A key in ``backend/env/stream.env.example`` that no ``Settings`` field binds.
   ``BaseServiceSettings`` sets ``extra="ignore"``, so a renamed field leaves the
   template pointing at a variable nobody reads — the operator fills in Twitch
   credentials, the poller still reports "not configured", and nothing errors.
2. A non-``None`` default for a Twitch credential. The rollout contract is that
   the feature arrives inert: with no credentials the Helix client raises
   ``HelixNotConfigured`` and the tick no-ops. A baked-in default would make an
   unconfigured deploy start hitting the shared app-token bucket instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.core.config import Settings  # noqa: E402

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / "env" / "stream.env.example"
_ASSIGNMENT = re.compile(r"^(?:#\s*)?([A-Z][A-Z0-9_]*)=")


def _declared_env_keys() -> set[str]:
    """Every ``KEY=`` in the template, including the commented-out optional ones."""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    matches = (_ASSIGNMENT.match(line.strip()) for line in lines)
    return {m.group(1) for m in matches if m is not None}


def test_env_example_keys_all_bind_to_a_settings_field() -> None:
    bindable = {name.upper() for name in Settings.model_fields}
    assert _declared_env_keys() <= bindable


def test_twitch_credentials_default_to_unconfigured() -> None:
    fields = Settings.model_fields
    assert fields["twitch_client_id"].default is None
    assert fields["twitch_client_secret"].default is None


def test_twitch_endpoints_point_at_twitch() -> None:
    fields = Settings.model_fields
    assert fields["twitch_helix_url"].default == "https://api.twitch.tv/helix"
    assert fields["twitch_token_url"].default == "https://id.twitch.tv/oauth2/token"

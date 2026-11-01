"""Per-provider subscription verdicts on registration reads: the payload shape and the read schema."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.schemas.identity import PersonDisplayRead  # noqa: E402
from shared.services.subscriptions import SubscriptionState, SubscriptionVerdict  # noqa: E402
from src.schemas.registration import RegistrationRead  # noqa: E402
from src.services.admission.requirements.subscription import serialize_verdicts  # noqa: E402


def _v(state: str, tier: int | None = None, label: str | None = None) -> SubscriptionVerdict:
    return SubscriptionVerdict(
        state=state,
        tier_rank=tier,
        tier_label=label,
        source="test",
        checked_at=datetime.now(UTC),
        expires_at=None,
        evidence={"reason": "because"} if state == SubscriptionState.UNKNOWN else {},
    )


ACTIVE_2 = _v(SubscriptionState.ACTIVE, 2, "Уровень 2")
UNKNOWN = _v(SubscriptionState.UNKNOWN)


class TestSerializeVerdicts:
    def test_shape_is_json_friendly(self):
        payload = serialize_verdicts({"boosty": ACTIVE_2})
        assert payload["boosty"]["state"] == "active"
        assert payload["boosty"]["tier_rank"] == 2
        assert payload["boosty"]["tier_label"] == "Уровень 2"

    def test_carries_the_unknown_reason_for_the_ui_cta(self):
        """The frontend branches on `reason` to choose "link Discord" vs
        "reconnect Twitch"."""
        payload = serialize_verdicts({"twitch": UNKNOWN})
        assert payload["twitch"]["reason"] == "because"

    def test_omits_reason_when_there_is_none(self):
        payload = serialize_verdicts({"boosty": ACTIVE_2})
        assert payload["boosty"].get("reason") is None

    def test_does_not_leak_internal_evidence(self):
        """`evidence` can hold guild ids and role ids — not for public reads."""
        verdict = SubscriptionVerdict(
            state="active",
            tier_rank=1,
            tier_label=None,
            source="discord_role",
            checked_at=datetime.now(UTC),
            expires_at=None,
            evidence={"guild_id": "999", "held_role_ids": ["1", "2"], "reason": "ok"},
        )
        payload = serialize_verdicts({"boosty": verdict})
        assert "guild_id" not in payload["boosty"]
        assert "held_role_ids" not in payload["boosty"]


class TestReadSchema:
    @staticmethod
    def _read(**overrides):
        return RegistrationRead(
            id=1, tournament_id=10, workspace_id=7, display=PersonDisplayRead(name="Player"), **overrides
        )

    def test_defaults_to_absent(self):
        read = self._read()
        assert read.subscription_outcome is None
        assert read.subscription_verdicts is None

    def test_accepts_outcome_and_verdicts(self):
        read = self._read(
            subscription_outcome="refused",
            subscription_verdicts={"boosty": {"state": "inactive"}},
        )
        assert read.subscription_outcome == "refused"
        assert read.subscription_verdicts["boosty"]["state"] == "inactive"

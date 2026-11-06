"""Pin the registration node's ``subscription_stage`` — the enum and the config default.

The default VALUE is the whole behaviour decision. The gate once ran at both stages unconditionally; ``check_in``
deliberately LOOSENS it to check-in-only. Flipping it to ``registration`` would silently start refusing sign-ups on
live tournaments, so it is pinned here rather than left to a reviewer noticing a one-word diff.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.core.enums import SubscriptionEnforcementStage
from shared.domain.flow.config import RegistrationNodeConfig


class TestTheEnum:
    def test_only_two_stages_exist(self):
        """Off is ``require_subscription=False``, not a third member: a stage nobody
        can reach is a stage somebody will eventually store."""
        assert [m.value for m in SubscriptionEnforcementStage] == ["registration", "check_in"]


class TestTheNodeConfig:
    def test_the_stage_defaults_to_check_in(self):
        assert RegistrationNodeConfig().subscription_stage is SubscriptionEnforcementStage.check_in

    def test_a_stored_stage_parses_to_the_enum(self):
        config = RegistrationNodeConfig.model_validate({"subscription_stage": "registration"})
        assert config.subscription_stage is SubscriptionEnforcementStage.registration

    def test_a_stage_outside_the_enum_is_refused(self):
        with pytest.raises(ValidationError):
            RegistrationNodeConfig.model_validate({"subscription_stage": "sign_up"})

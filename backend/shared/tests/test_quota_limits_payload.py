from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from shared.schemas.quota import QuotaLimitsPayload, QuotaLimitsWrite, QuotaPlanLimitRead, QuotaPlanWrite


def test_a_zero_request_rate_cannot_be_written() -> None:
    """0 rpm would refuse every call; "no limit here" is ``None``, never 0."""
    with pytest.raises(ValidationError):
        QuotaLimitsWrite(requests_per_minute=0)
    with pytest.raises(ValidationError):
        QuotaPlanWrite(slug="free", title="Free", limits=[{"scope": "key", "requests_per_minute": 0}])

    assert QuotaLimitsWrite(requests_per_minute=1).requests_per_minute == 1
    assert QuotaLimitsWrite().requests_per_minute is None
    # The other dimensions keep 0 as a real value (e.g. "no heavy calls").
    assert QuotaLimitsWrite(heavy_per_day=0).heavy_per_day == 0


def test_a_zero_stored_before_the_rule_still_reads_back() -> None:
    """Reads parse stored rows; tightening the write path must not break them."""
    row = SimpleNamespace(
        scope="key",
        requests_per_minute=0,
        heavy_per_day=None,
        concurrent_heavy=None,
        max_upload_bytes=None,
        max_items_per_request=None,
    )

    assert QuotaPlanLimitRead.model_validate(row, from_attributes=True).requests_per_minute == 0
    assert QuotaLimitsPayload(requests_per_minute=0).requests_per_minute == 0

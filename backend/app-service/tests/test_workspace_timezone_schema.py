"""Unit tests for workspace timezone schema validation (no DB required)."""

import pytest
from pydantic import ValidationError

from src import schemas


def test_update_accepts_valid_iana_zone():
    model = schemas.WorkspaceUpdate(timezone="Europe/Moscow")
    assert model.timezone == "Europe/Moscow"
    assert model.model_dump(exclude_unset=True) == {"timezone": "Europe/Moscow"}


@pytest.mark.parametrize("bad", ["", "   ", "MSK", "Europe/Mordor", "UTC+3"])
def test_update_rejects_unknown_or_blank_zone(bad):
    # The column is NOT NULL — a blank/unknown zone must be rejected, never
    # silently written as NULL.
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(timezone=bad)


def test_update_omits_unset_timezone():
    # exclude_unset is what _svc_update passes to the CRUD engine — nothing set
    # means the column is untouched.
    assert schemas.WorkspaceUpdate().model_dump(exclude_unset=True) == {}


def test_read_defaults_to_moscow():
    assert schemas.WorkspaceRead.model_fields["timezone"].default == "Europe/Moscow"

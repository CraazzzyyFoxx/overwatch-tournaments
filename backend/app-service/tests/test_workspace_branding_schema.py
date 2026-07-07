"""Unit tests for workspace branding schema validation (no DB required)."""

import pytest
from pydantic import ValidationError

from src import schemas


def test_update_accepts_valid_hex_and_toggle():
    model = schemas.WorkspaceUpdate(
        branding_enabled=True,
        brand_primary="#14b8a6",
        brand_secondary="#8B5CF6",
        brand_background="#0b1220",
        brand_surface="#111a2b",
    )
    assert model.brand_primary == "#14b8a6"
    assert model.brand_secondary == "#8B5CF6"
    assert model.branding_enabled is True


@pytest.mark.parametrize(
    "bad",
    ["14b8a6", "#14b8a", "#xyzxyz", "teal", "#14b8a6ff", "rgb(0,0,0)"],
)
def test_update_rejects_malformed_hex(bad):
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(brand_primary=bad)


def test_update_omits_unset_branding():
    model = schemas.WorkspaceUpdate()
    assert model.brand_primary is None
    # exclude_unset is what _svc_update passes to the CRUD engine — nothing set
    # means nothing is written.
    assert model.model_dump(exclude_unset=True) == {}


def test_update_allows_explicit_none_to_clear():
    model = schemas.WorkspaceUpdate(brand_primary=None)
    assert model.model_dump(exclude_unset=True) == {"brand_primary": None}


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_update_blank_hex_becomes_none(blank):
    # A blank colour means "keep the default" — it must clear the token to None
    # rather than fail the #RRGGBB pattern.
    model = schemas.WorkspaceUpdate(brand_primary=blank, brand_surface=blank)
    assert model.brand_primary is None
    assert model.brand_surface is None
    assert model.model_dump(exclude_unset=True) == {
        "brand_primary": None,
        "brand_surface": None,
    }


def test_update_strips_whitespace_around_hex():
    model = schemas.WorkspaceUpdate(brand_primary="  #14b8a6  ")
    assert model.brand_primary == "#14b8a6"


_CORE_PALETTE = (
    "brand_accent",
    "brand_foreground",
    "brand_muted",
    "brand_border",
    "brand_ring",
    "brand_destructive",
)


def test_update_accepts_core_palette_overrides():
    model = schemas.WorkspaceUpdate(
        brand_accent="#22d3ee",
        brand_foreground="#f1f5f9",
        brand_muted="#1e293b",
        brand_border="#334155",
        brand_ring="#22d3ee",
        brand_destructive="#ef4444",
    )
    assert model.brand_accent == "#22d3ee"
    assert model.brand_destructive == "#ef4444"


@pytest.mark.parametrize("field", _CORE_PALETTE)
def test_update_blank_core_palette_becomes_none(field):
    model = schemas.WorkspaceUpdate(**{field: "   "})
    assert getattr(model, field) is None


@pytest.mark.parametrize("field", _CORE_PALETTE)
def test_update_rejects_malformed_core_palette(field):
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(**{field: "not-a-hex"})


def test_read_exposes_core_palette_fields():
    fields = schemas.WorkspaceRead.model_fields
    for name in _CORE_PALETTE:
        assert name in fields


def test_read_exposes_branding_fields():
    fields = schemas.WorkspaceRead.model_fields
    for name in (
        "branding_enabled",
        "brand_primary",
        "brand_secondary",
        "brand_background",
        "brand_surface",
    ):
        assert name in fields


def test_update_accepts_valid_subdomain():
    model = schemas.WorkspaceUpdate(subdomain="Team-A")
    assert model.subdomain == "team-a"  # normalized


@pytest.mark.parametrize("bad", ["team_a", "www", "-x", "a" * 64])
def test_update_rejects_bad_subdomain(bad):
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(subdomain=bad)


def test_read_exposes_domain_seo_fields():
    fields = schemas.WorkspaceRead.model_fields
    for name in ("subdomain", "seo_title", "seo_description"):
        assert name in fields

"""Schemas for configurable registration forms in the balancer admin."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FieldValidationConfig(BaseModel):
    regex: str | None = None
    error_message: str | None = None

    @field_validator("regex")
    @classmethod
    def validate_regex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        pattern = value.strip()
        if not pattern:
            return None
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc.msg}") from exc
        return pattern

    @field_validator("error_message")
    @classmethod
    def normalize_error_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class CustomFieldDef(BaseModel):
    key: str
    label: str
    type: Literal["text", "number", "select", "checkbox", "url"] = "text"
    required: bool = False
    placeholder: str | None = None
    options: list[str] | None = None
    validation: FieldValidationConfig | None = None


class BuiltInFieldConfig(BaseModel):
    enabled: bool = True
    required: bool = False
    subroles: dict[str, list[str]] | None = None
    validation: FieldValidationConfig | None = None


class SubroleOption(BaseModel):
    slug: str
    label: str


class RegistrationFormUpsert(BaseModel):
    is_open: bool = False
    auto_approve: bool = False
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    built_in_fields: dict[str, BuiltInFieldConfig] = Field(default_factory=dict)
    custom_fields: list[CustomFieldDef] = Field(default_factory=list)


class RegistrationFormRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    is_open: bool
    auto_approve: bool = False
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    built_in_fields: dict[str, BuiltInFieldConfig] = Field(default_factory=dict, validation_alias="built_in_fields_json")
    custom_fields: list[CustomFieldDef] = Field(default_factory=list, validation_alias="custom_fields_json")
    # Workspace sub-role catalog keyed by registration role code (tank/dps/support).
    # Single source of truth for the form builder's Subroles tab.
    subrole_catalog: dict[str, list[SubroleOption]] = Field(default_factory=dict)

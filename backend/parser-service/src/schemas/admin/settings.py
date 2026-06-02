from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ("SettingRead", "SettingUpsert")


class SettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: dict
    description: str | None
    updated_at: datetime | None
    updated_by: int | None


class SettingUpsert(BaseModel):
    value: dict
    description: str | None = None

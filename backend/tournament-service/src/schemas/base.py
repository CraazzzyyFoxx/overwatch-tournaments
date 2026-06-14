from pydantic import BaseModel

__all__ = ("BaseRead", "LookupItem", "Score")


class BaseRead(BaseModel):
    id: int


class LookupItem(BaseModel):
    id: int
    name: str


class Score(BaseModel):
    home: int
    away: int

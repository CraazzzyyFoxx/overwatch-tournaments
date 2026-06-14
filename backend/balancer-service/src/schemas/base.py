from pydantic import BaseModel

__all__ = ("BaseRead",)


class BaseRead(BaseModel):
    id: int

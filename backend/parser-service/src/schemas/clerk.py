from pydantic import BaseModel

__all__ = ("ClerkUser",)


class ClerkUser(BaseModel):
    user_id: str
    permissions: list[str]
    organization: str | None
    role: str | None

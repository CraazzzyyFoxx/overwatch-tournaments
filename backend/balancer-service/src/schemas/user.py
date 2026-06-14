from pydantic import BaseModel

__all__ = ("UserCSV",)


class UserCSV(BaseModel):
    battle_tag: str
    discord: str | None
    twitch: str | None
    smurfs: list[str]

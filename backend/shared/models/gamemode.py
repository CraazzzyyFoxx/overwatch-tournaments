from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.map import Map

__all__ = ("Gamemode",)


class Gamemode(db.TimeStampIntegerMixin):
    __tablename__ = "gamemode"
    __table_args__ = ({"schema": "overwatch"},)

    slug: Mapped[str] = mapped_column(String(), unique=True)
    name: Mapped[str] = mapped_column(String(), unique=True)
    image_path: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)

    maps: Mapped[list["Map"]] = relationship()

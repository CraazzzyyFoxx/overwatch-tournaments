from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.gamemode import Gamemode

__all__ = ("Map",)


class Map(db.TimeStampIntegerMixin):
    __tablename__ = "map"
    __table_args__ = ({"schema": "overwatch"},)

    gamemode_id: Mapped[int] = mapped_column(ForeignKey(Gamemode.id))
    name: Mapped[str] = mapped_column(String(), unique=True)
    image_path: Mapped[str] = mapped_column(String())

    gamemode: Mapped[Gamemode] = relationship(back_populates="maps")

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.auth_user import AuthUser
    from shared.models.division_grid import DivisionGridVersion

__all__ = (
    "Workspace",
    "WorkspaceMember",
)


class Workspace(db.TimeStampIntegerMixin):
    __tablename__ = "workspace"

    slug: Mapped[str] = mapped_column(String(), unique=True, index=True)
    name: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), server_default="true")
    default_division_grid_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace", passive_deletes=True
    )
    default_division_grid_version: Mapped["DivisionGridVersion | None"] = relationship(
        foreign_keys=[default_division_grid_version_id],
        lazy="selectin",
    )


class WorkspaceMember(db.TimeStampIntegerMixin):
    __tablename__ = "workspace_member"

    __table_args__ = (UniqueConstraint("workspace_id", "auth_user_id"),)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    auth_user_id: Mapped[int] = mapped_column(
        ForeignKey("auth.user.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(), server_default="member")

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    auth_user: Mapped["AuthUser"] = relationship()

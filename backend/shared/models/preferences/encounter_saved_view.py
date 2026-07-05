from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.identity.auth_user import AuthUser
from shared.models.tenancy.workspace import Workspace

__all__ = ("EncounterSavedView",)


class EncounterSavedView(db.TimeStampIntegerMixin):
    __tablename__ = "encounter_saved_view"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "auth_user_id",
            "name",
            name="uq_encounter_saved_view_workspace_user_name",
        ),
        Index("ix_encounter_saved_view_workspace_user", "workspace_id", "auth_user_id"),
        {"schema": "tournament"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey(Workspace.id, ondelete="CASCADE"), index=True)
    auth_user_id: Mapped[int] = mapped_column(ForeignKey(AuthUser.id, ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")

    workspace: Mapped[Workspace] = relationship()
    auth_user: Mapped[AuthUser] = relationship()

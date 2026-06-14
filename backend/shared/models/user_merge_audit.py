from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.auth_user import AuthUser

__all__ = ("UserMergeAudit",)


class UserMergeAudit(db.TimeStampIntegerMixin):
    __tablename__ = "user_merge_audit"
    __table_args__ = ({"schema": "players"},)

    source_user_id: Mapped[int] = mapped_column(index=True)
    target_user_id: Mapped[int] = mapped_column(index=True)
    operator_auth_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    field_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    moved_identity_ids_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    deduped_identity_ids_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    affected_counts_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    preview_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    operator: Mapped["AuthUser | None"] = relationship()

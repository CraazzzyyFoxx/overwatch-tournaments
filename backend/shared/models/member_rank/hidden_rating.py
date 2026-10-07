from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("MemberHiddenRating",)


class MemberHiddenRating(db.TimeStampIntegerMixin):
    """The mix ranker's hidden ``(mu, sigma)`` of one member in one role.

    Derived data: it is a fold over the workspace's ``casual.match`` history
    (``MixRankerService.rebuild``), kept incrementally by every recorded match
    and rebuilt whenever that history or the workspace's hidden scale changes.
    Per workspace member, never per platform player: a host of another
    workspace must not be able to move it.
    """

    __tablename__ = "member_hidden_rating"
    __table_args__ = (
        UniqueConstraint("workspace_member_id", "role", name="uq_member_hidden_rating_member_role"),
        {"schema": "balancer"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    workspace_member_id: Mapped[int] = mapped_column(ForeignKey("workspace_member.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    mu: Mapped[float] = mapped_column(Float(), nullable=False)
    sigma: Mapped[float] = mapped_column(Float(), nullable=False)

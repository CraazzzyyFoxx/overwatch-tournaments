from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("TournamentPreviewAccess",)


class TournamentPreviewAccess(db.TimeStampIntegerMixin):
    """Per-tournament preview allowlist.

    Logged-in auth users who may view a *hidden* tournament (and all its nested
    data) even without workspace-admin rights. Keyed on ``auth_user`` — not on a
    tournament participant — because preview invitees are chosen before teams or
    players exist. Follows the cross-schema FK pattern used for tournament rows
    referencing ``auth.user`` elsewhere.
    """

    __tablename__ = "tournament_preview_access"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "auth_user_id", name="uq_tournament_preview_access_tournament_user"
        ),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True
    )
    auth_user_id: Mapped[int] = mapped_column(
        ForeignKey("auth.user.id", ondelete="CASCADE"), index=True
    )

from typing import Literal, get_args

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("TOURNAMENT_LINK_KINDS", "TournamentLink", "TournamentLinkKind")

#: The write-schema ``Literal`` and the column check-set share this alias.
#: The column itself stays free text so a new kind is a code change, not a migration.
TournamentLinkKind = Literal["discord", "stream", "vod", "bracket", "rules", "other"]
TOURNAMENT_LINK_KINDS: frozenset[str] = frozenset(get_args(TournamentLinkKind))


class TournamentLink(db.TimeStampIntegerMixin):
    """One typed external link attached to a tournament (Discord, stream, VOD, ...).

    Typed rows instead of a free-form blob on ``Tournament``: an organizer needs
    several links of the same kind (two casters' streams, one VOD per day), and
    each one carries its own label and ordering. ``is_active`` is a soft delete —
    an unlinked-but-remembered URL survives a mistaken removal.
    """

    __tablename__ = "tournament_link"
    __table_args__ = (
        UniqueConstraint("tournament_id", "kind", "url", name="uq_tournament_link_tournament_kind_url"),
        Index("ix_tournament_link_tournament_active", "tournament_id", "is_active"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # One of ``TOURNAMENT_LINK_KINDS``, stored as text (not a PG enum) to stay
    # flexible: adding a kind must not require a migration.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Human-facing caption. NULL means "render the kind's default label".
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)

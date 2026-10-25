from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("StreamSession",)


class StreamSession(db.TimeStampIntegerMixin):
    """One Twitch broadcast of a participant's POV, as one tournament's poll tick saw it.

    Owned by stream-service: the poll tick records a row per live POV channel
    (never an official cast) and later resolves the broadcast's VOD. A streamer
    in two polled tournaments gets one row per tournament for the same
    ``stream_id``. Consent is NOT frozen here: the reads re-check it against the
    current registration and veto every time, so a row is a fact about Twitch,
    not a licence to publish it.
    """

    __tablename__ = "session"
    __table_args__ = (
        UniqueConstraint("tournament_id", "stream_id", name="uq_stream_session_tournament_stream"),
        Index("ix_stream_session_tournament_started", "tournament_id", "started_at"),
        {"schema": "stream"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"))
    #: The streamer (``player_id`` in stream-service terms).
    user_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    #: Twitch login at observation time, casefolded.
    channel: Mapped[str] = mapped_column(String(64))
    #: Helix ``user_id`` of the channel: what ``GET /videos?user_id=`` takes.
    broadcaster_id: Mapped[str] = mapped_column(String(32))
    #: Helix stream ``id``; a VOD is matched to its session by ``video.stream_id``.
    stream_id: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    #: The last tick that saw the stream live: the end of the broadcast once it is over.
    last_seen_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    #: Helix video id, without Twitch's ``v`` prefix. NULL until resolved.
    vod_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Last resolution attempt, then last liveness check of the resolved VOD.
    vod_checked_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    #: The VOD vanished (expired or deleted); the row is hidden everywhere from then on.
    vod_gone_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

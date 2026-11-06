from sqlalchemy import ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.models.tournament.flow import FlowNode
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament

__all__ = ("ParticipantResult",)


class ParticipantResult(db.Base):
    """One row per member per finished tournament: the member's final team, final placement and the field size.

    Written only by ``shared.services.participant_result.write_participant_results``. ``placement`` NULL means the
    final team has no positive place; ``source_node_id`` is the leaderboard node the row copies (NULL for rule 2),
    cleared with it.
    """

    __tablename__ = "participant_result"
    __table_args__ = (
        Index("ix_participant_result_workspace_member_id", "workspace_member_id"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), primary_key=True)
    workspace_member_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="CASCADE"), primary_key=True
    )
    final_team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="SET NULL"), nullable=True)
    placement: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    field_size: Mapped[int] = mapped_column(Integer())
    source_node_id: Mapped[int | None] = mapped_column(ForeignKey(FlowNode.id, ondelete="SET NULL"), nullable=True)

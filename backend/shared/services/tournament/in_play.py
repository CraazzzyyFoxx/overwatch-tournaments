"""The "matches are being played" predicate over ``Tournament``: live, with a stage node that is live."""

import sqlalchemy as sa

from shared import models
from shared.core.enums import FlowNodeKind, FlowNodeStatus, TournamentStatus

__all__ = ("TOURNAMENT_IN_PLAY",)

# What a visitor reads as "live" is a ball in play, not a registration filling up: a registration or formation node
# never counts, only a stage.
TOURNAMENT_IN_PLAY: sa.ColumnElement[bool] = sa.and_(
    models.Tournament.status == TournamentStatus.LIVE,
    sa.exists().where(
        models.FlowNode.tournament_id == models.Tournament.id,
        models.FlowNode.kind == FlowNodeKind.STAGE,
        models.FlowNode.status == FlowNodeStatus.LIVE,
    ),
)

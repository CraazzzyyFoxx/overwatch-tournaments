"""Typed-RPC subjects of the rank domain: ``rpc.stats.rank.*``, for every game that collects ranks.

``?discipline=`` names the game (default Overwatch, the first collector); each subject dispatches to that module's
``DisciplineSpec.collection_handlers`` entry, which validates its payload and authorizes the caller. Reads are public
(AuthNone); the admin operations need the caller's identity. A game whose module serves no such handler is a 404.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core.errors import BaseAPIException
from shared.disciplines import DISCIPLINES
from shared.disciplines.spec import CollectionHandler
from src.core import db

from . import _common as c

_SF = db.async_session_maker

#: The game a request without ``?discipline=`` means: the collector these routes served before they took a game.
_DEFAULT_DISCIPLINE = "overwatch"

# Subject -> collection handler key. Literal on purpose: the gateway route parity guard reads subjects from source.
_SUBJECTS = {
    "rpc.stats.rank.user_history": "rank.user_history",
    "rpc.stats.rank.game_account_history": "rank.game_account_history",
    "rpc.stats.rank.user_current": "rank.user_current",
    "rpc.stats.rank.user_career": "rank.user_career",
    "rpc.stats.rank.fetch_log": "rank.fetch_log",
    "rpc.stats.rank.stats": "rank.stats",
    "rpc.stats.rank.user_collection": "rank.user_collection",
    "rpc.stats.rank.career_signals": "rank.career_signals",
    "rpc.stats.rank.collect": "rank.collect",
    "rpc.stats.rank.reenable_disabled": "rank.reenable_disabled",
}

# Public (AuthNone) reads never look at the caller; everything else needs a valid identity.
_PUBLIC = frozenset({"rank.user_history", "rank.game_account_history", "rank.user_current", "rank.user_career"})


def _handler(data: dict, name: str) -> CollectionHandler:
    spec = DISCIPLINES.get(c.q1(data, "discipline") or _DEFAULT_DISCIPLINE)
    handler = spec.collection_handlers.get(name) if spec is not None else None
    if handler is None:
        raise BaseAPIException(status_code=404, detail="rank_collection_unsupported")
    return handler


def register(broker: Any, logger: Any) -> None:
    def bind(subject: str, name: str) -> None:
        async def _handle(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                handler = _handler(data, name)
                user = None if name in _PUBLIC else c.actor(data)
                return await handler(session, user, data)

            return await c.envelope(logger, name, op, session_factory=_SF)

        # FastStream names a handler after its function: one distinct name per subject.
        _handle.__name__ = f"_{name.replace('.', '_')}"
        broker.subscriber(subject)(_handle)

    for subject, name in _SUBJECTS.items():
        bind(subject, name)

"""Contract tests for the single publication primitive.

These pin the four invariants the module docstring claims, because each one was
a bug in the rail it replaces: publication before the caller's commit, a
per-call-site choice of transport, invalidations that overwrote instead of
merging, and staged rows silently dropped on a clean session.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from shared.models.platform.realtime import WorkspaceEvent
from shared.services.realtime import DomainEvent, Resource, Scope, emit
from shared.services.realtime.emit import INVALIDATION_EVENT_TYPE


# These tests exercise the session listeners, not Postgres, so they run on
# in-memory SQLite — which has no JSONB. The column type is production's
# business; here it only has to hold a dict.
@compiles(JSONB, "sqlite")
def _render_jsonb_as_json(_type: JSONB, _compiler: object, **_kw: object) -> str:
    return "JSON"


@pytest.fixture()
def session() -> Session:
    # StaticPool + an ATTACH on connect: the model lives in the `realtime`
    # schema, which SQLite expresses as an attached database, and an in-memory
    # one only survives if every checkout is the same connection.
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", poolclass=sa.pool.StaticPool)
    sa.event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _record: dbapi_connection.execute("ATTACH DATABASE ':memory:' AS realtime"),
    )
    identifier = WorkspaceEvent.__table__.c.id
    original_type = identifier.type
    # SQLite only autoincrements INTEGER PRIMARY KEY, never BIGINT. Swapped for
    # DDL only, same reason as the default below.
    identifier.type = sa.Integer()
    occurred_at = WorkspaceEvent.__table__.c.occurred_at
    # The production default is Postgres' `now()`, which SQLite cannot parse.
    # Swapped only for DDL so the tests still run against the REAL mapped
    # model — a hand-rolled copy of the table would stop catching a column
    # rename, which is half of what these tests are for.
    original_default = occurred_at.server_default
    occurred_at.server_default = sa.DefaultClause(sa.text("CURRENT_TIMESTAMP"))
    try:
        WorkspaceEvent.metadata.create_all(engine, tables=[WorkspaceEvent.__table__])
    finally:
        identifier.type = original_type
        occurred_at.server_default = original_default
    maker = sessionmaker(engine)
    with maker() as opened:
        yield opened


def _rows(session: Session) -> list[WorkspaceEvent]:
    return list(session.scalars(sa.select(WorkspaceEvent).order_by(WorkspaceEvent.id)))


def test_invalidations_for_one_scope_merge_into_one_event(session: Session) -> None:
    # Union, not last-write-wins: two services touching the same tournament in
    # one transaction each name what THEY staled, and the subscriber must see
    # both. The predecessor merged by "strongest reason", which could only
    # approximate this.
    asyncio.run(emit(session, scope=Scope.tournament(42), invalidates=[Resource.TOURNAMENT_TEAMS]))
    asyncio.run(emit(session, scope=Scope.tournament(42), invalidates=[Resource.TOURNAMENT_STANDINGS]))
    session.commit()

    rows = _rows(session)
    assert len(rows) == 1
    assert rows[0].topic == "tournament:42:invalidation"
    assert rows[0].event_type == INVALIDATION_EVENT_TYPE
    assert rows[0].payload["resources"] == ["tournament.standings", "tournament.teams"]


def test_clean_session_still_persists(session: Session) -> None:
    # The regression that hid in the predecessor: Session._flush early-returns
    # when nothing is dirty, so a commit whose business write landed elsewhere
    # (or that has no ORM write at all) fired no before_flush and dropped the
    # event without a trace.
    asyncio.run(emit(session, scope=Scope.workspace(7), invalidates=[Resource.WORKSPACE_LOGS]))
    session.commit()

    assert [row.topic for row in _rows(session)] == ["workspace:7:invalidation"]


def test_rollback_publishes_nothing(session: Session) -> None:
    # The write and the event are staged together, then the transaction fails:
    # the event must die with it, or subscribers learn about a row that does
    # not exist. The session is deliberately made dirty first — a rollback with
    # nothing to roll back dispatches no SQLAlchemy event at all (verified), so
    # a test without a write would be asserting against a code path that cannot
    # run in production, where emit always sits beside a write.
    session.add(WorkspaceEvent(topic="unrelated", event_type="x", schema_version=1, payload={}))
    session.flush()
    asyncio.run(emit(session, scope=Scope.tournament(42), invalidates=[Resource.TOURNAMENT_TEAMS]))
    session.rollback()
    session.commit()

    assert _rows(session) == []


def test_domain_event_and_invalidation_are_separate_rows(session: Session) -> None:
    asyncio.run(
        emit(
            session,
            scope=Scope.tournament(42),
            invalidates=[Resource.TOURNAMENT_TEAMS],
            data=DomainEvent(
                domain="draft", event_type="draft.pick_made", payload={"pick_id": 3}, resource="draft.board"
            ),
        )
    )
    session.commit()

    topics = sorted(row.topic for row in _rows(session))
    assert topics == ["tournament:42:draft", "tournament:42:invalidation"]


def test_non_durable_domain_event_persists_no_row(session: Session) -> None:
    # Presence and job progress carry no replay value: a reconnecting client
    # re-derives them from its own snapshot, and persisting them would only
    # inflate the replay window everyone else pays for.
    asyncio.run(
        emit(
            session,
            scope=Scope.tournament(42),
            data=DomainEvent(domain="balancer", event_type="balancer_job.progress", durable=False),
        )
    )
    session.commit()

    assert _rows(session) == []


def test_resource_must_match_its_scope(session: Session) -> None:
    # A workspace resource on a tournament topic would be delivered to the
    # tournament's audience, which is a different (public) set of people.
    with pytest.raises(ValueError, match="belongs to scope"):
        asyncio.run(emit(session, scope=Scope.tournament(42), invalidates=[Resource.WORKSPACE_LOGS]))


def test_entity_ids_ride_along_deduplicated(session: Session) -> None:
    asyncio.run(
        emit(
            session,
            scope=Scope.tournament(42),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
            entity_ids={"registration_ids": [77, 77]},
        )
    )
    asyncio.run(
        emit(
            session,
            scope=Scope.tournament(42),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
            entity_ids={"registration_ids": [78]},
        )
    )
    session.commit()

    assert _rows(session)[0].payload["entity_ids"] == {"registration_ids": [77, 78]}


def test_encounter_scope_has_no_invalidation_topic() -> None:
    with pytest.raises(ValueError, match="no invalidation topic"):
        _ = Scope.encounter(9).invalidation_topic


def test_emit_needs_something_to_say(session: Session) -> None:
    with pytest.raises(ValueError):
        asyncio.run(emit(session, scope=Scope.tournament(42)))

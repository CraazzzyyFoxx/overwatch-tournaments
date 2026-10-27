import contextlib
import uuid
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from asyncpg.exceptions import InternalClientError
from sqlalchemy import BigInteger, ColumnCollection, DateTime, Uuid, event, func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared.core import errors

# Explicit public surface so ``from .db import *`` (in ``shared/core/__init__.py``)
# exports only these names and never leaks re-imported SQLAlchemy/stdlib helpers.
__all__ = [
    "Base",
    "TimeStampIntegerMixin",
    "TimeStampUUIDMixin",
    "DatabaseEngines",
    "ResilientAsyncSession",
    "create_database",
    "create_database_from_settings",
]


class Base(DeclarativeBase):
    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}

    @classmethod
    def get_column(cls, column_name: str) -> ColumnCollection:
        columns = {c.name: c for c in cls.__table__.columns}
        if column_name in columns:
            return columns[column_name]
        # Mapped SQL expressions (``column_property``, e.g. Team.avg_sr computed
        # from the roster) are sortable too — they aren't in ``__table__.columns``.
        column_attrs = cls.__mapper__.column_attrs
        if column_name in column_attrs.keys():
            return column_attrs[column_name].expression
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="invalid_column", msg="Invalid column")],
        )

    @classmethod
    def depth_get_column(cls, column_name: list[str]) -> ColumnCollection:
        if len(column_name) > 2:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="invalid_column", msg="Invalid column")],
            )

        if len(column_name) == 1:
            return cls.get_column(column_name[0])

        try:
            field = cls.__getattribute__(cls, column_name[0])
            entity = field.entity
            if column_name[1] not in {c.name for c in entity.columns}:
                raise errors.ApiHTTPException(
                    status_code=400,
                    detail=[errors.ApiExc(code="invalid_column", msg="Invalid column")],
                )
            return {c.name: c for c in entity.columns}[column_name[1]]
        except (IndexError, KeyError):
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="invalid_column", msg="Invalid column")],
            )


class TimeStampIntegerMixin(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, sort_order=-1000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), sort_order=-999, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=-998, onupdate=func.now()
    )


class TimeStampUUIDMixin(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(Uuid(), primary_key=True, server_default=func.gen_random_uuid(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), sort_order=-999, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=-998, onupdate=func.now()
    )


# Substrings PostgreSQL drivers use when the socket is already gone. Matched on
# the driver exception, because SQLAlchemy does not set ``connection_invalidated``
# when the failure happens *during* teardown -- the point where it would tell us
# nothing we can act on anyway.
_GONE_CONNECTION_MARKERS = (
    "connection is closed",
    "connection was closed",
    "connection already closed",
    "connection is already closed",
)


def _connection_already_gone(exc: DBAPIError) -> bool:
    if exc.connection_invalidated:
        return True
    message = str(exc.orig if exc.orig is not None else exc).lower()
    return any(marker in message for marker in _GONE_CONNECTION_MARKERS)


class ResilientAsyncSession(AsyncSession):
    """``AsyncSession`` whose teardown cannot mask the error that killed it.

    ``statement_timeout`` (and a pooler or server dropping a connection
    mid-transaction) leaves the asyncpg connection closed. The session's own
    exit path then emits a ``ROLLBACK`` on that dead socket and raises
    ``InterfaceError: cannot call Transaction.rollback(): the underlying
    connection is closed`` -- from ``__aexit__``, so it *replaces* the real
    exception with a generic one and reports the caller's frame as the culprit.

    A cancelled statement can also leave asyncpg's protocol out of step with the
    server: the ``ROLLBACK`` then raises a raw ``InternalClientError: cannot
    switch to state 15; another operation (2) is in progress`` (no SQLAlchemy
    wrapper), and the half-closed session leaves its connection for the garbage
    collector. That connection is as unusable as a closed one.

    Nothing is recoverable at that point: the transaction died with the
    connection, so there is no work left to roll back. Discard the session
    state instead and let the original failure (or success) stand.
    """

    async def close(self) -> None:
        try:
            await super().close()
        except (DBAPIError, InternalClientError) as exc:
            if isinstance(exc, DBAPIError) and not _connection_already_gone(exc):
                raise
            # Drop identity map + the half-torn-down transaction without
            # touching the socket again: invalidation terminates the connection
            # instead of pooling it.
            with contextlib.suppress(Exception):
                await self.invalidate()


@dataclass(frozen=True)
class DatabaseEngines:
    """Container for database engine and session factory instances."""

    async_engine: AsyncEngine
    async_session_maker: async_sessionmaker[AsyncSession]

    async def get_async_session(self) -> AsyncGenerator[AsyncSession]:
        async with self.async_session_maker() as session:
            yield session


def _unique_prepared_statement_name() -> str:
    """Generate a unique asyncpg prepared statement name.

    Without pgBouncer's prepared-statement tracking (pgBouncer < 1.21 or
    ``max_prepared_statements = 0``) one backend is shared across clients, so
    prepared statements must not reuse names; a unique name per statement avoids
    "prepared statement already exists" errors. With tracking, pgBouncer maps
    client names to its own and the unique name is merely harmless.
    """
    return f"__asyncpg_{uuid.uuid4()}__"


def _register_session_settings(engine: AsyncEngine, settings: Mapping[str, str]) -> None:
    """Apply ``settings`` per-transaction, as ``SET LOCAL`` would.

    Behind pgBouncer transaction pooling they cannot be delivered as asyncpg
    startup parameters (pgBouncer ignores or rejects them), so they are set at
    the start of every transaction, scoped to that transaction only. One
    ``set_config(..., true)`` call per setting, in a single round trip.
    """
    calls = ", ".join(f"set_config('{name}', '{value}', true)" for name, value in settings.items())

    @event.listens_for(engine.sync_engine, "begin")
    def _set_session_settings(conn: Any) -> None:
        conn.exec_driver_sql(f"SELECT {calls}")


def create_database(
    async_url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
    pool_pre_ping: bool = True,
    pool_use_lifo: bool = True,
    connect_timeout: float = 10.0,
    statement_timeout: int = 30000,
    pgbouncer: bool = False,
    pgbouncer_prepared_statements: bool = True,
    session_settings: Mapping[str, str] | None = None,
) -> DatabaseEngines:
    """Factory for creating database engine + session maker pairs.

    Args:
        async_url: Async database URL (e.g. postgresql+asyncpg://...).
        pool_size: Connection pool size.
        max_overflow: Max overflow connections beyond pool_size.
        pool_timeout: Seconds to wait for a pooled connection before timing out.
        pool_recycle: Seconds after which pooled connections are recycled.
        pool_pre_ping: Test pooled connections before handing them out.
        pool_use_lifo: Prefer recently-used connections to reduce stale idle sockets.
        connect_timeout: Seconds to wait while opening a new asyncpg connection.
        statement_timeout: Query timeout in milliseconds (0 to disable).
        session_settings: Extra Postgres settings for every session of this
            engine (e.g. planner knobs); applied the same way as
            ``statement_timeout``.
        pgbouncer: Configure for connecting through pgBouncer in transaction
            pooling mode. Uses unique prepared-statement names and applies
            ``statement_timeout`` per-transaction (as ``SET LOCAL``) instead of
            as a startup parameter.
            The client-side pool is still kept: pgBouncer caps *server* backends,
            while a connection-per-request client (NullPool) burns a pgBouncer
            client slot and a full connect round-trip per message, and leaves
            SQLAlchemy no stale connection to pre-ping — so a pooler-dropped
            connection surfaces as an error instead of a transparent reconnect.
            Size the pool so replicas x (pool_size + max_overflow) stays under
            pgBouncer's ``max_client_conn``.
        pgbouncer_prepared_statements: With ``pgbouncer``, keep SQLAlchemy's
            per-connection prepared-statement cache, so a repeated statement is
            one round trip instead of prepare + execute + close. Needs pgBouncer
            >= 1.21 with ``max_prepared_statements > 0`` (1.24+ defaults to 200),
            which re-prepares a client's statements on whichever backend serves
            its transaction. ``False`` disables the cache
            (``prepared_statement_cache_size=0``) for an older pooler or one
            with ``max_prepared_statements = 0``. Ignored without ``pgbouncer``.

    Returns:
        A DatabaseEngines instance with engine and session maker attributes.
    """
    connect_args: dict[str, Any] = {}
    if connect_timeout > 0:
        connect_args["timeout"] = connect_timeout

    engine_kwargs: dict[str, Any] = {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "pool_recycle": pool_recycle,
        "pool_pre_ping": pool_pre_ping,
        "pool_use_lifo": pool_use_lifo,
    }
    settings = dict(session_settings or {})
    if statement_timeout > 0:
        settings["statement_timeout"] = str(statement_timeout)
    if pgbouncer:
        connect_args["prepared_statement_name_func"] = _unique_prepared_statement_name
        if not pgbouncer_prepared_statements:
            connect_args["prepared_statement_cache_size"] = 0
    elif settings:
        connect_args["server_settings"] = settings

    async_engine = create_async_engine(
        url=async_url,
        connect_args=connect_args,
        **engine_kwargs,
    )

    if pgbouncer and settings:
        _register_session_settings(async_engine, settings)

    async_session = async_sessionmaker(async_engine, class_=ResilientAsyncSession, expire_on_commit=False)

    return DatabaseEngines(
        async_engine=async_engine,
        async_session_maker=async_session,
    )


class _HasDbSettings(Protocol):
    """Structural type for ``BaseServiceSettings``-shaped config objects.

    Every service's ``Settings``/``AppConfig`` extends ``BaseServiceSettings``,
    which declares these fields — matched structurally instead of importing
    ``shared.core.config`` here, to avoid a config <-> db import cycle.
    """

    db_url_asyncpg: str
    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int
    db_pool_recycle: int
    db_pool_pre_ping: bool
    db_pool_use_lifo: bool
    db_connect_timeout: float
    db_statement_timeout: int
    db_pgbouncer: bool
    db_pgbouncer_prepared_statements: bool


def create_database_from_settings(
    settings: _HasDbSettings, *, session_settings: Mapping[str, str] | None = None
) -> DatabaseEngines:
    """``create_database`` reading its pool knobs off a service's settings."""
    return create_database(
        async_url=settings.db_url_asyncpg,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_use_lifo=settings.db_pool_use_lifo,
        connect_timeout=settings.db_connect_timeout,
        statement_timeout=settings.db_statement_timeout,
        pgbouncer=settings.db_pgbouncer,
        pgbouncer_prepared_statements=settings.db_pgbouncer_prepared_statements,
        session_settings=session_settings,
    )

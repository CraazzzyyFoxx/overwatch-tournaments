import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ColumnCollection, DateTime, Uuid, event, func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from shared.core import errors


class Base(DeclarativeBase):
    entity_name: str = "unknown"

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}

    @classmethod
    def get_column(cls, column_name: str) -> ColumnCollection:
        if column_name not in {c.name for c in cls.__table__.columns}:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="invalid_column", msg="Invalid column")],
            )
        return {c.name: c for c in cls.__table__.columns}[column_name]

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), sort_order=-999, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=-998, onupdate=func.now()
    )


class TimeStampUUIDMixin(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(
        Uuid(), primary_key=True, server_default=func.gen_random_uuid(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), sort_order=-999, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=-998, onupdate=func.now()
    )


@dataclass(frozen=True)
class DatabaseEngines:
    """Container for database engine and session factory instances."""

    async_engine: AsyncEngine
    async_session_maker: async_sessionmaker[AsyncSession]

    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.async_session_maker() as session:
            yield session


def _unique_prepared_statement_name() -> str:
    """Generate a unique asyncpg prepared statement name.

    Under pgBouncer transaction pooling a single backend connection is shared
    across clients, so prepared statements must not reuse names; a unique name
    per statement avoids "prepared statement already exists / does not exist"
    errors.
    """
    return f"__asyncpg_{uuid.uuid4()}__"


def _register_statement_timeout(engine: AsyncEngine, statement_timeout: int) -> None:
    """Apply ``statement_timeout`` per-transaction via ``SET LOCAL``.

    Behind pgBouncer transaction pooling the timeout cannot be delivered as an
    asyncpg startup parameter (pgBouncer ignores or rejects it), so it is set at
    the start of every transaction, where ``SET LOCAL`` scopes it to that
    transaction only.
    """
    timeout_ms = int(statement_timeout)

    @event.listens_for(engine.sync_engine, "begin")
    def _set_statement_timeout(conn: Any) -> None:
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")


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
        pgbouncer: Configure for connecting through pgBouncer in transaction
            pooling mode. Disables asyncpg prepared-statement caching, uses
            unique prepared-statement names, hands pooling over to pgBouncer
            (NullPool), and applies ``statement_timeout`` per-transaction via
            ``SET LOCAL`` instead of as a startup parameter. The client-side
            pool tuning options are ignored in this mode.

    Returns:
        A DatabaseEngines instance with engine and session maker attributes.
    """
    connect_args: dict[str, Any] = {}
    if connect_timeout > 0:
        connect_args["timeout"] = connect_timeout

    engine_kwargs: dict[str, Any] = {}
    if pgbouncer:
        # pgBouncer owns the connection pool; SQLAlchemy keeps none of its own.
        engine_kwargs["poolclass"] = NullPool
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = _unique_prepared_statement_name
    else:
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow
        engine_kwargs["pool_timeout"] = pool_timeout
        engine_kwargs["pool_recycle"] = pool_recycle
        engine_kwargs["pool_pre_ping"] = pool_pre_ping
        engine_kwargs["pool_use_lifo"] = pool_use_lifo
        if statement_timeout > 0:
            connect_args["server_settings"] = {"statement_timeout": str(statement_timeout)}

    async_engine = create_async_engine(
        url=async_url,
        connect_args=connect_args,
        **engine_kwargs,
    )

    if pgbouncer and statement_timeout > 0:
        _register_statement_timeout(async_engine, statement_timeout)

    async_session = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    return DatabaseEngines(
        async_engine=async_engine,
        async_session_maker=async_session,
    )

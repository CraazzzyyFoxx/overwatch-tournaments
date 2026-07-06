from shared.core.db import Base, create_database
from src.core.config import settings

__all__ = (
    "Base",
    "async_engine",
    "async_session_maker",
)

_db = create_database(
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
)

async_engine = _db.async_engine
async_session_maker = _db.async_session_maker

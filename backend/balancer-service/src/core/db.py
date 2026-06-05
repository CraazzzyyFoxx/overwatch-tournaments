from shared.core.db import Base, TimeStampIntegerMixin, TimeStampUUIDMixin, create_database
from src.core import config

__all__ = (
    "Base",
    "TimeStampIntegerMixin",
    "TimeStampUUIDMixin",
    "async_engine",
    "async_session_maker",
    "get_async_session",
)

_db = create_database(
    async_url=config.config.db_url_asyncpg,
    pool_size=config.config.db_pool_size,
    max_overflow=config.config.db_max_overflow,
    pool_timeout=config.config.db_pool_timeout,
    pool_recycle=config.config.db_pool_recycle,
    pool_pre_ping=config.config.db_pool_pre_ping,
    pool_use_lifo=config.config.db_pool_use_lifo,
    connect_timeout=config.config.db_connect_timeout,
    statement_timeout=config.config.db_statement_timeout,
)

async_engine = _db.async_engine
async_session_maker = _db.async_session_maker
get_async_session = _db.get_async_session

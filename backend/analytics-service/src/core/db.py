from shared.core.db import Base, DateTime, TimeStampIntegerMixin, TimeStampUUIDMixin, create_database

from src.core import config

__all__ = (
    "Base",
    "DateTime",
    "TimeStampIntegerMixin",
    "TimeStampUUIDMixin",
    "async_engine",
    "async_session_maker",
    "get_async_session",
)

_db = create_database(
    async_url=config.settings.db_url_asyncpg,
    pool_size=config.settings.db_pool_size,
    max_overflow=config.settings.db_max_overflow,
    pool_timeout=config.settings.db_pool_timeout,
    pool_recycle=config.settings.db_pool_recycle,
    pool_pre_ping=config.settings.db_pool_pre_ping,
    pool_use_lifo=config.settings.db_pool_use_lifo,
    statement_timeout=config.settings.db_statement_timeout,
)

async_engine = _db.async_engine
async_session_maker = _db.async_session_maker
get_async_session = _db.get_async_session

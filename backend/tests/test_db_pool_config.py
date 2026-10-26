from shared.core import db as db_module


def test_create_database_passes_pool_tuning_options(monkeypatch):
    captured: dict[str, object] = {}

    async_engine = object()
    async_session_factory = object()

    def fake_create_async_engine(*, url, **kwargs):
        captured["async_url"] = url
        captured["async_kwargs"] = kwargs
        return async_engine

    def fake_async_sessionmaker(*args, **kwargs):
        captured["async_sessionmaker_args"] = args
        captured["async_sessionmaker_kwargs"] = kwargs
        return async_session_factory

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_module, "async_sessionmaker", fake_async_sessionmaker)

    db = db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        pool_size=15,
        max_overflow=25,
        pool_timeout=7,
        pool_recycle=180,
        pool_pre_ping=True,
        pool_use_lifo=True,
        connect_timeout=3.5,
        statement_timeout=1234,
    )

    assert captured["async_url"] == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    assert captured["async_kwargs"] == {
        "pool_size": 15,
        "max_overflow": 25,
        "pool_timeout": 7,
        "pool_recycle": 180,
        "pool_pre_ping": True,
        "pool_use_lifo": True,
        "connect_args": {"timeout": 3.5, "server_settings": {"statement_timeout": "1234"}},
    }
    assert captured["async_sessionmaker_args"] == (async_engine,)
    assert captured["async_sessionmaker_kwargs"] == {
        "class_": db_module.ResilientAsyncSession,
        "expire_on_commit": False,
    }
    # The session class is the whole point of ``ResilientAsyncSession``: a plain
    # ``AsyncSession`` re-raises from ``__aexit__`` when a statement_timeout has
    # already killed the connection, replacing the real failure with a generic
    # InterfaceError. It must stay a drop-in AsyncSession for every caller.
    assert issubclass(db_module.ResilientAsyncSession, db_module.AsyncSession)
    assert db.async_engine is async_engine
    assert db.async_session_maker is async_session_factory
    assert not hasattr(db, "sync_engine")
    assert not hasattr(db, "sync_session_maker")


def test_create_database_omits_statement_timeout_when_disabled(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_async_engine(*, url, **kwargs):
        captured["async_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_module, "async_sessionmaker", lambda *args, **kwargs: object())

    database = db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        statement_timeout=0,
    )

    assert captured["async_kwargs"] == {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
        "pool_use_lifo": True,
        "connect_args": {"timeout": 10.0},
    }
    assert not hasattr(database, "sync_engine")
    assert not hasattr(database, "sync_session_maker")


def test_create_database_omits_connect_timeout_when_disabled(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_async_engine(*, url, **kwargs):
        captured["async_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_module, "async_sessionmaker", lambda *args, **kwargs: object())

    db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        connect_timeout=0,
        statement_timeout=0,
    )

    assert captured["async_kwargs"]["connect_args"] == {}


class _RecordingEvent:
    """Stands in for ``sqlalchemy.event``: records each listener instead of attaching it."""

    def __init__(self) -> None:
        self.listeners: list[tuple[object, str, object]] = []

    def listens_for(self, target, identifier):
        def decorator(fn):
            self.listeners.append((target, identifier, fn))
            return fn

        return decorator


class _FakeAsyncEngine:
    def __init__(self) -> None:
        self.sync_engine = object()


def _pgbouncer_database(monkeypatch, **kwargs):
    """``create_database`` behind pgBouncer on a fake engine: ``(engine kwargs, engine, recorded events)``."""
    captured: dict[str, object] = {}
    engine = _FakeAsyncEngine()
    events = _RecordingEvent()

    def fake_create_async_engine(*, url, **engine_kwargs):
        captured.update(engine_kwargs)
        return engine

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_module, "async_sessionmaker", lambda *args, **kw: object())
    monkeypatch.setattr(db_module, "event", events)
    db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@pgbouncer:6432/testdb", pgbouncer=True, **kwargs
    )
    return captured, engine, events


def test_create_database_pgbouncer_mode_keeps_prepared_statement_cache(monkeypatch):
    kwargs, engine, events = _pgbouncer_database(monkeypatch, statement_timeout=5000)

    # pgBouncer caps server backends; the client-side pool stays bounded and
    # pre-pinged so connections are reused instead of one connect per message.
    assert "poolclass" not in kwargs
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 20
    assert kwargs["pool_pre_ping"] is True

    connect_args = kwargs["connect_args"]
    # pgBouncer >= 1.21 (max_prepared_statements > 0) re-prepares statements on
    # whichever backend serves the transaction, so the driver keeps its cache:
    # a repeated statement is one round trip, not prepare + execute + close.
    assert "prepared_statement_cache_size" not in connect_args
    assert connect_args["prepared_statement_name_func"] is db_module._unique_prepared_statement_name
    # statement_timeout must NOT ride along as an asyncpg startup parameter,
    # since pgBouncer transaction pooling ignores/rejects it.
    assert "server_settings" not in connect_args
    assert connect_args["timeout"] == 10.0

    # statement_timeout is instead applied per-transaction.
    assert [(target, identifier) for target, identifier, _ in events.listeners] == [(engine.sync_engine, "begin")]


def test_create_database_pgbouncer_without_prepared_statements_disables_cache(monkeypatch):
    kwargs, _, _ = _pgbouncer_database(monkeypatch, pgbouncer_prepared_statements=False)

    connect_args = kwargs["connect_args"]
    assert connect_args["prepared_statement_cache_size"] == 0
    assert connect_args["prepared_statement_name_func"] is db_module._unique_prepared_statement_name
    assert "server_settings" not in connect_args


def test_create_database_prepared_statements_flag_ignored_without_pgbouncer(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_async_engine(*, url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_module, "async_sessionmaker", lambda *args, **kw: object())

    db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        statement_timeout=0,
        pgbouncer_prepared_statements=False,
    )

    # A direct connection keeps the driver defaults (cache on, asyncpg's own names).
    assert captured["connect_args"] == {"timeout": 10.0}


def test_create_database_pgbouncer_skips_timeout_registration_when_disabled(monkeypatch):
    _, _, events = _pgbouncer_database(monkeypatch, statement_timeout=0)

    assert events.listeners == []


def test_unique_prepared_statement_name_is_unique():
    first = db_module._unique_prepared_statement_name()
    second = db_module._unique_prepared_statement_name()

    assert first != second
    assert first.startswith("__asyncpg_")
    assert first.endswith("__")


def test_create_database_pgbouncer_applies_session_settings_on_begin(monkeypatch):
    _, _, events = _pgbouncer_database(monkeypatch, statement_timeout=7500, session_settings={"jit": "off"})
    [(_, _, on_begin)] = events.listeners

    executed: list[str] = []

    class FakeConn:
        def exec_driver_sql(self, sql):
            executed.append(sql)

    on_begin(FakeConn())

    # One round trip per transaction; ``set_config(..., true)`` is ``SET LOCAL``: it ends with the transaction.
    assert executed == ["SELECT set_config('jit', 'off', true), set_config('statement_timeout', '7500', true)"]

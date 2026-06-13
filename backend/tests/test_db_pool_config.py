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
        "class_": db_module.AsyncSession,
        "expire_on_commit": False,
    }
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


def test_create_database_pgbouncer_mode_disables_prepared_statements(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_async_engine(*, url, **kwargs):
        captured["async_url"] = url
        captured["async_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_module, "async_sessionmaker", lambda *args, **kwargs: object())

    registered: dict[str, object] = {}
    monkeypatch.setattr(
        db_module,
        "_register_statement_timeout",
        lambda engine, timeout: registered.update(engine=engine, timeout=timeout),
    )

    db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@pgbouncer:6432/testdb",
        statement_timeout=5000,
        pgbouncer=True,
    )

    kwargs = captured["async_kwargs"]
    # pgBouncer owns the pool; SQLAlchemy must not keep its own.
    assert kwargs["poolclass"] is db_module.NullPool
    # QueuePool-only tuning is invalid for NullPool and must be omitted.
    for key in (
        "pool_size",
        "max_overflow",
        "pool_timeout",
        "pool_use_lifo",
        "pool_recycle",
        "pool_pre_ping",
    ):
        assert key not in kwargs

    connect_args = kwargs["connect_args"]
    assert connect_args["prepared_statement_cache_size"] == 0
    assert callable(connect_args["prepared_statement_name_func"])
    # statement_timeout must NOT ride along as an asyncpg startup parameter,
    # since pgBouncer transaction pooling ignores/rejects it.
    assert "server_settings" not in connect_args
    assert connect_args["timeout"] == 10.0

    # statement_timeout is instead applied per-transaction.
    assert registered["timeout"] == 5000
    assert "engine" in registered


def test_create_database_pgbouncer_skips_timeout_registration_when_disabled(monkeypatch):
    monkeypatch.setattr(
        db_module, "create_async_engine", lambda *, url, **kwargs: object()
    )
    monkeypatch.setattr(db_module, "async_sessionmaker", lambda *args, **kwargs: object())

    registered: dict[str, object] = {}
    monkeypatch.setattr(
        db_module,
        "_register_statement_timeout",
        lambda engine, timeout: registered.update(called=True),
    )

    db_module.create_database(
        async_url="postgresql+asyncpg://user:pass@pgbouncer:6432/testdb",
        statement_timeout=0,
        pgbouncer=True,
    )

    assert registered == {}


def test_unique_prepared_statement_name_is_unique():
    first = db_module._unique_prepared_statement_name()
    second = db_module._unique_prepared_statement_name()

    assert first != second
    assert first.startswith("__asyncpg_")
    assert first.endswith("__")


def test_register_statement_timeout_sets_local_on_begin(monkeypatch):
    handlers: dict[str, object] = {}

    class FakeEvent:
        @staticmethod
        def listens_for(target, identifier):
            def decorator(fn):
                handlers["target"] = target
                handlers["identifier"] = identifier
                handlers["fn"] = fn
                return fn

            return decorator

    monkeypatch.setattr(db_module, "event", FakeEvent)

    sync_engine = object()

    class FakeAsyncEngine:
        pass

    engine = FakeAsyncEngine()
    engine.sync_engine = sync_engine

    db_module._register_statement_timeout(engine, 7500)

    assert handlers["target"] is sync_engine
    assert handlers["identifier"] == "begin"

    executed: list[str] = []

    class FakeConn:
        def exec_driver_sql(self, sql):
            executed.append(sql)

    handlers["fn"](FakeConn())

    assert executed == ["SET LOCAL statement_timeout = 7500"]

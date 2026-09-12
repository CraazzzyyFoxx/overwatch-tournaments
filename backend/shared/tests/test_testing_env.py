"""Loader and provisioner for host-run pytest DB wiring."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.testing.db import ensure_test_postgres
from shared.testing.env import TEST_ENV_PATH, apply_test_env_defaults


def _reset_provision(monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.testing.db as dbmod

    monkeypatch.setattr(dbmod, "_ensured", False)
    monkeypatch.setattr(dbmod, "_skip_reason", None)


def test_test_env_file_is_committed() -> None:
    assert TEST_ENV_PATH.is_file()
    text = TEST_ENV_PATH.read_text(encoding="utf-8")
    assert "POSTGRES_HOST=127.0.0.1" in text
    assert "POSTGRES_PORT=55432" in text
    assert "POSTGRES_DB=anak_test" in text
    assert "DEBUG=" not in text


def test_test_env_fills_when_no_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("shared.testing.env.local_env_paths", lambda: [])
    apply_test_env_defaults()
    assert os.environ["POSTGRES_HOST"] == "127.0.0.1"
    assert os.environ["POSTGRES_PORT"] == "55432"
    assert os.environ["POSTGRES_DB"] == "anak_test"


def test_exported_postgres_host_wins_over_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "exported.example")
    monkeypatch.setattr("shared.testing.env.local_env_paths", lambda: [])
    apply_test_env_defaults()
    assert os.environ["POSTGRES_HOST"] == "exported.example"


def test_local_env_wins_over_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_HOST=from-local-env\n", encoding="utf-8")
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.setattr("shared.testing.env.local_env_paths", lambda: [envfile])
    apply_test_env_defaults()
    assert os.environ["POSTGRES_HOST"] == "from-local-env"


def test_protected_db_skips_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_provision(monkeypatch)
    monkeypatch.setenv("POSTGRES_DB", "anak_v5")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("must not open a socket for a production DSN")

    monkeypatch.setattr("shared.testing.db._probe", boom)
    monkeypatch.setattr("shared.testing.db._docker_compose_up", boom)
    with pytest.raises(pytest.skip.Exception, match="production"):
        ensure_test_postgres()


def test_unreachable_dummy_skips_when_docker_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_provision(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "55432")
    monkeypatch.setenv("POSTGRES_DB", "anak_test")
    monkeypatch.setenv("TEST_POSTGRES_DOCKER", "0")
    monkeypatch.setattr("shared.testing.db._probe", lambda: None)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("must not start docker when TEST_POSTGRES_DOCKER=0")

    monkeypatch.setattr("shared.testing.db._docker_compose_up", boom)
    with pytest.raises(pytest.skip.Exception, match="unreachable"):
        ensure_test_postgres()


def test_create_test_async_engine_uses_nullpool_and_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.pool import NullPool

    from shared.testing.db import create_test_async_engine

    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "55432")
    monkeypatch.setenv("POSTGRES_DB", "anak_test")
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "postgres")
    monkeypatch.setattr("shared.testing.db.ensure_test_postgres", lambda: None)
    engine = create_test_async_engine()
    try:
        assert type(engine.pool) is NullPool
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.sync_engine.dispose()

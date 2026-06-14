from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from main import app
from src.core.config import settings


def _create_test_engine():
    connect_args: dict[str, str] = {}
    if settings.db_statement_timeout > 0:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout}"

    return create_engine(
        settings.db_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    test_engine = _create_test_engine()
    test_session_maker = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
    with test_session_maker() as session:
        yield session
    test_engine.dispose()


@pytest.fixture(scope="package")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c

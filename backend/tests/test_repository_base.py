from __future__ import annotations

import asyncio
from typing import Any

from shared import models
from shared.core import enums
from shared.core.pagination import PaginationSortSearchParams
from shared.repository import BaseRepository


class _ScalarResult:
    def __init__(self, rows: list[Any], scalar: Any = None) -> None:
        self._rows = rows
        self._scalar = scalar

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


class _Result:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def unique(self) -> _Result:
        return self

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows, self._scalar)

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _Session:
    def __init__(self, results: list[_Result] | None = None) -> None:
        self.results = results or []
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.added_many: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return self.results.pop(0)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def add_all(self, instances: list[Any]) -> None:
        self.added_many.extend(instances)

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        self.flushed += 1


def _hero(name: str = "Ana") -> models.Hero:
    return models.Hero(slug=name.lower(), name=name, image_path="", type=enums.HeroClass.support)


def test_get_returns_first_unique_scalar() -> None:
    hero = _hero()
    session = _Session([_Result([hero])])
    repo = BaseRepository(models.Hero)

    assert asyncio.run(repo.get(session, 1)) is hero
    assert len(session.statements) == 1


def test_list_applies_query_and_total_queries() -> None:
    hero = _hero()
    session = _Session([_Result([hero]), _Result(scalar=1)])
    repo = BaseRepository(models.Hero)
    params = PaginationSortSearchParams(query="ana", fields=["name"], sort="name")

    rows, total = asyncio.run(
        repo.list(session, params, filters=[models.Hero.type == enums.HeroClass.support])
    )

    assert rows == [hero]
    assert total == 1
    assert len(session.statements) == 2


def test_write_methods_flush_without_committing() -> None:
    hero = _hero()
    session = _Session()
    repo = BaseRepository(models.Hero)

    assert asyncio.run(repo.create(session, hero)) is hero
    assert session.added == [hero]
    assert session.flushed == 1

    asyncio.run(repo.update_fields(session, hero, {"name": "Ana Amari"}))
    assert hero.name == "Ana Amari"
    assert session.flushed == 2

    asyncio.run(repo.delete(session, hero))
    assert session.deleted == [hero]
    assert session.flushed == 3
    assert not hasattr(session, "commit")

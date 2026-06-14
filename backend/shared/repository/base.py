from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.core.db import Base
from shared.core.pagination import PaginationSortParams, PaginationSortSearchParams


class BaseRepository[ModelType: Base]:
    """Generic async repository for common CRUD operations.

    Repositories are transaction-neutral: write methods mutate the session and
    flush, while callers decide when to commit or roll back.
    """

    def __init__(self, model: type[ModelType]) -> None:
        self.model = model

    def select(self) -> sa.Select[tuple[ModelType]]:
        return sa.select(self.model)

    def _apply_options(
        self,
        query: sa.Select[tuple[Any]],
        options: Sequence[_AbstractLoad] | None,
    ) -> sa.Select[tuple[Any]]:
        if options:
            query = query.options(*options)
        return query

    def _apply_filters(
        self,
        query: sa.Select[tuple[Any]],
        filters: Sequence[sa.ColumnElement[bool]] | None,
    ) -> sa.Select[tuple[Any]]:
        if filters:
            query = query.where(*filters)
        return query

    async def get(
        self,
        session: AsyncSession,
        id: int | str,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> ModelType | None:
        query = self._apply_options(self.select().where(self.model.id == id), options)
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def get_by(
        self,
        session: AsyncSession,
        *,
        options: Sequence[_AbstractLoad] | None = None,
        **filters: Any,
    ) -> ModelType | None:
        query = self._apply_options(self.select().filter_by(**filters), options)
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def list(
        self,
        session: AsyncSession,
        params: PaginationSortParams | PaginationSortSearchParams | None = None,
        *,
        options: Sequence[_AbstractLoad] | None = None,
        filters: Sequence[sa.ColumnElement[bool]] | None = None,
        order_by: Sequence[sa.ColumnElement[Any]] | None = None,
    ) -> tuple[Sequence[ModelType], int]:
        query = self._apply_options(self.select(), options)
        total_query = sa.select(sa.func.count(self.model.id))

        query = self._apply_filters(query, filters)
        total_query = self._apply_filters(total_query, filters)

        if isinstance(params, PaginationSortSearchParams):
            query = params.apply_search(query, self.model)
            total_query = params.apply_search(total_query, self.model)

        if order_by:
            query = query.order_by(*order_by)

        if params is not None:
            query = params.apply_pagination_sort(query, self.model)

        result = await session.execute(query)
        total_result = await session.execute(total_query)
        return result.unique().scalars().all(), total_result.scalar_one()

    async def get_all(
        self,
        session: AsyncSession,
        params: PaginationSortParams | PaginationSortSearchParams,
        *,
        options: Sequence[_AbstractLoad] | None = None,
        filters: Sequence[sa.ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[ModelType], int]:
        return await self.list(session, params, options=options, filters=filters)

    async def bulk_get(
        self,
        session: AsyncSession,
        ids: Sequence[int | str],
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[ModelType]:
        if not ids:
            return []
        query = self._apply_options(self.select().where(self.model.id.in_(ids)), options)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_bulk(
        self,
        session: AsyncSession,
        ids: Sequence[int | str],
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[ModelType]:
        return await self.bulk_get(session, ids, options=options)

    async def count(
        self,
        session: AsyncSession,
        *,
        filters: Sequence[sa.ColumnElement[bool]] | None = None,
    ) -> int:
        query = self._apply_filters(sa.select(sa.func.count(self.model.id)), filters)
        result = await session.execute(query)
        return result.scalar_one()

    async def exists(
        self,
        session: AsyncSession,
        *,
        filters: Sequence[sa.ColumnElement[bool]] | None = None,
        **filter_by: Any,
    ) -> bool:
        query = sa.select(sa.literal(True)).select_from(self.model).filter_by(**filter_by).limit(1)
        query = self._apply_filters(query, filters)
        result = await session.execute(query)
        return result.scalar_one_or_none() is True

    async def create(self, session: AsyncSession, instance: ModelType) -> ModelType:
        session.add(instance)
        await session.flush()
        return instance

    async def create_many(
        self,
        session: AsyncSession,
        instances: Sequence[ModelType],
    ) -> Sequence[ModelType]:
        session.add_all(list(instances))
        await session.flush()
        return instances

    async def update_fields(
        self,
        session: AsyncSession,
        instance: ModelType,
        data: dict[str, Any],
    ) -> ModelType:
        for field, value in data.items():
            setattr(instance, field, value)
        await session.flush()
        return instance

    async def update(
        self,
        session: AsyncSession,
        instance: ModelType,
        data: dict[str, Any],
    ) -> ModelType:
        return await self.update_fields(session, instance, data)

    async def delete(self, session: AsyncSession, instance: ModelType) -> None:
        await session.delete(instance)
        await session.flush()

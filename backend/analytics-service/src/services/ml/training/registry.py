"""Model artifact registry — CRUD over ``analytics.ml_model_artifact``.

Each ``MLModelArtifact`` row carries the storage URI of a serialised model on
disk plus metadata (training cutoff, metrics, feature importance). The
inference runner queries this table with ``is_active=True`` to discover the
boosters to load.

The corresponding ``AnalyticsAlgorithm`` row is created/found here too. Some
v2 rows are internal augmentation pipelines; the read API decides which
algorithm rows are user-selectable.
"""

from __future__ import annotations

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

__all__ = (
    "ensure_algorithm",
    "register_artifact",
    "load_active_artifact",
    "load_active_artifacts",
    "deactivate_other_artifacts",
)


async def ensure_algorithm(session: AsyncSession, name: str) -> models.AnalyticsAlgorithm:
    """Upsert an ``AnalyticsAlgorithm`` row by ``name``."""
    existing = await session.scalar(sa.select(models.AnalyticsAlgorithm).where(models.AnalyticsAlgorithm.name == name))
    if existing is not None:
        return existing
    row = models.AnalyticsAlgorithm(name=name)
    session.add(row)
    await session.flush()
    return row


async def register_artifact(
    session: AsyncSession,
    *,
    algorithm_id: int,
    model_kind: str,
    role: str | None,
    version: str,
    storage_uri: str,
    feature_version: str,
    training_cutoff_tournament_id: int | None,
    metrics: dict[str, typing.Any] | None,
    feature_importance: dict[str, typing.Any] | None,
    activate: bool = True,
) -> models.MLModelArtifact:
    """Insert a new artifact row (or update if the same key already exists).

    When ``activate=True``, any other artifact rows for the same
    ``(algorithm_id, model_kind, role)`` are flipped to ``is_active=False``
    so only the freshly-registered row is loaded by inference.
    """
    existing = await session.scalar(
        sa.select(models.MLModelArtifact).where(
            models.MLModelArtifact.algorithm_id == algorithm_id,
            models.MLModelArtifact.model_kind == model_kind,
            models.MLModelArtifact.role == role,
            models.MLModelArtifact.version == version,
        )
    )
    if existing is None:
        artifact = models.MLModelArtifact(
            algorithm_id=algorithm_id,
            model_kind=model_kind,
            role=role,
            version=version,
            storage_uri=storage_uri,
            feature_version=feature_version,
            training_cutoff_tournament_id=training_cutoff_tournament_id,
            metrics=metrics,
            feature_importance=feature_importance,
            is_active=activate,
        )
        session.add(artifact)
    else:
        existing.storage_uri = storage_uri
        existing.feature_version = feature_version
        existing.training_cutoff_tournament_id = training_cutoff_tournament_id
        existing.metrics = metrics
        existing.feature_importance = feature_importance
        existing.is_active = activate
        artifact = existing

    if activate:
        await deactivate_other_artifacts(
            session,
            algorithm_id=algorithm_id,
            model_kind=model_kind,
            role=role,
            keep_version=version,
        )

    await session.flush()
    return artifact


async def deactivate_other_artifacts(
    session: AsyncSession,
    *,
    algorithm_id: int,
    model_kind: str,
    role: str | None,
    keep_version: str,
) -> None:
    """Flip ``is_active=False`` on every artifact sharing key but not version."""
    await session.execute(
        sa.update(models.MLModelArtifact)
        .where(
            models.MLModelArtifact.algorithm_id == algorithm_id,
            models.MLModelArtifact.model_kind == model_kind,
            models.MLModelArtifact.role == role,
            models.MLModelArtifact.version != keep_version,
        )
        .values(is_active=False)
    )


async def load_active_artifact(
    session: AsyncSession,
    *,
    algorithm_id: int,
    model_kind: str,
    role: str | None,
) -> models.MLModelArtifact | None:
    """Return the active artifact row matching the key, if any."""
    return await session.scalar(
        sa.select(models.MLModelArtifact).where(
            models.MLModelArtifact.algorithm_id == algorithm_id,
            models.MLModelArtifact.model_kind == model_kind,
            models.MLModelArtifact.role == role,
            models.MLModelArtifact.is_active.is_(True),
        )
    )


async def load_active_artifacts(
    session: AsyncSession,
    *,
    model_kind: str,
) -> typing.Sequence[models.MLModelArtifact]:
    """Return all active artifacts of a given ``model_kind``."""
    result = await session.scalars(
        sa.select(models.MLModelArtifact).where(
            models.MLModelArtifact.model_kind == model_kind,
            models.MLModelArtifact.is_active.is_(True),
        )
    )
    return result.all()

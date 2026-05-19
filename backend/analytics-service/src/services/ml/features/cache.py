"""File-backed runtime cache for expensive ML feature frames."""

from __future__ import annotations

import collections.abc
import hashlib
import json
import logging
import os
import time
import typing
import uuid
from pathlib import Path

import pandas as pd

from src.core.config import settings
from src.services.ml import FEATURE_VERSION

BuildFrame = collections.abc.Callable[[], collections.abc.Awaitable[pd.DataFrame]]

logger = logging.getLogger(__name__)

_memory_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def clear_memory_cache() -> None:
    """Clear only the in-process cache layer; disk files stay intact."""
    _memory_cache.clear()


def scope_cache_params(
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> dict[str, typing.Any]:
    return {
        "workspace_id": int(workspace_id) if workspace_id is not None else None,
        "workspace_ids": tuple(sorted(int(w) for w in workspace_ids or ())),
    }


async def get_or_build_dataframe(
    name: str,
    params: collections.abc.Mapping[str, typing.Any],
    build: BuildFrame,
) -> pd.DataFrame:
    """Return a cached DataFrame, building and persisting it on cache miss."""
    if not settings.analytics_feature_cache_enabled:
        return await build()

    key = _cache_key(name, params)
    cached = _memory_cache.get(key)
    if cached is not None and _is_fresh_ts(cached[0]):
        return cached[1].copy(deep=True)

    path = _cache_path(key)
    if path.exists() and _is_fresh_path(path):
        try:
            df = pd.read_pickle(path)
        except Exception:
            logger.warning("Failed to read ML feature cache file: %s", path, exc_info=True)
            _unlink_quietly(path)
        else:
            _memory_cache[key] = (time.time(), df.copy(deep=True))
            return df.copy(deep=True)

    df = await build()
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Feature cache builder {name!r} returned {type(df)!r}")

    stored = df.copy(deep=True)
    _memory_cache[key] = (time.time(), stored)
    _write_cache_file(path, stored)
    return stored.copy(deep=True)


def _cache_key(name: str, params: collections.abc.Mapping[str, typing.Any]) -> str:
    payload = {
        "feature_version": FEATURE_VERSION,
        "namespace": settings.analytics_feature_cache_namespace,
        "name": name,
        "params": _jsonable(params),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return Path(settings.analytics_feature_cache_dir) / f"{key}.pkl"


def _is_fresh_ts(created_at: float) -> bool:
    ttl = int(settings.analytics_feature_cache_ttl_seconds)
    return ttl <= 0 or (time.time() - created_at) <= ttl


def _is_fresh_path(path: Path) -> bool:
    ttl = int(settings.analytics_feature_cache_ttl_seconds)
    if ttl <= 0:
        return True
    return (time.time() - path.stat().st_mtime) <= ttl


def _write_cache_file(path: Path, df: pd.DataFrame) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        df.to_pickle(tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        logger.warning("Failed to write ML feature cache file: %s", path, exc_info=True)
        if "tmp_path" in locals():
            _unlink_quietly(tmp_path)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Failed to unlink cache path: %s", path, exc_info=True)


def _jsonable(value: typing.Any) -> typing.Any:
    if isinstance(value, collections.abc.Mapping):
        return {str(k): _jsonable(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (set, frozenset)):
        return [_jsonable(v) for v in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)

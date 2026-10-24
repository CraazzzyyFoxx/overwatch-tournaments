"""Artifact serialisation helpers for v2 models.

The concrete model classes, the ``MLModel`` protocol and ``align_features`` belong to the discipline's analytics module
(``shared.domain.analytics`` for the neutral contract). This module only stores and loads the whole object via
:mod:`joblib` (preferred over :mod:`pickle` for numpy array compactness).

Models are persisted as ``<algorithm_id>/<version>/<file>.joblib`` under the
``ANALYTICS_MODELS_DIR`` config setting, or under the directory of an active
:func:`models_dir_override`.
"""

from __future__ import annotations

import contextlib
import logging
import os
import pickle
import tempfile
import typing
from contextvars import ContextVar
from pathlib import Path

import joblib

from src.core import config

__all__ = (
    "artifact_path",
    "save_artifact",
    "load_artifact",
    "load_artifact_or_none",
    "models_dir_override",
)

logger = logging.getLogger(__name__)

#: Module path of the concrete model classes in the pre-conversion layout: a pickle naming it was never converted
#: (``scripts/convert_discipline_artifacts.py``).
_OLD_MODEL_MODULES = "src.services.ml.models"

_models_dir: ContextVar[str | None] = ContextVar("analytics_models_dir_override", default=None)


@contextlib.contextmanager
def models_dir_override(path: str) -> typing.Iterator[None]:
    """Within this context, :func:`artifact_path` resolves under ``path`` instead of ``ANALYTICS_MODELS_DIR``.

    The backtest's fold artifacts go to a throwaway directory this way, never over a production file.
    """
    token = _models_dir.set(path)
    try:
        yield
    finally:
        _models_dir.reset(token)


def artifact_path(algorithm_id: int, version: str, filename: str, *, root: str | None = None) -> Path:
    """Build the filesystem path for an artifact file.

    ``<root>/<algorithm_id>/<version>/<filename>``; ``root`` defaults to the active
    :func:`models_dir_override`, else ``ANALYTICS_MODELS_DIR``.
    The directory is created on demand by :func:`save_artifact`.
    """
    base = Path(root or _models_dir.get() or config.settings.analytics_models_dir)
    return base / str(algorithm_id) / version / filename


def save_artifact(obj: typing.Any, path: Path) -> str:
    """Atomically write ``obj`` to ``path`` via tmp+rename.

    Returns the storage URI to store in ``MLModelArtifact.storage_uri``
    (``file://`` scheme). Parent directories are created as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        os.close(fd)
        joblib.dump(obj, tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return f"file://{path.as_posix()}"


def load_artifact(storage_uri: str) -> typing.Any:
    """Load an object saved via :func:`save_artifact`."""
    if storage_uri.startswith("file://"):
        return joblib.load(storage_uri.removeprefix("file://"))
    raise NotImplementedError(f"Unsupported storage scheme: {storage_uri}")


def load_artifact_or_none(storage_uri: str) -> typing.Any | None:
    """:func:`load_artifact`, or ``None`` when the artifact is unusable and the caller has a neutral fallback.

    Unusable: the file is missing, the pickle is damaged, or it names a class path of the pre-conversion layout
    (``ModuleNotFoundError`` for ``src.services.ml.models...``: logged at ERROR, the registry row was not converted).
    Any other failure - notably a missing estimator library - is not an artifact problem and propagates.
    """
    try:
        return load_artifact(storage_uri)
    except FileNotFoundError:
        return None
    except (ModuleNotFoundError, pickle.UnpicklingError) as exc:
        if isinstance(exc, ModuleNotFoundError) and not (exc.name or "").startswith(_OLD_MODEL_MODULES):
            raise
        logger.error(
            "Artifact %s is unusable (unconverted or damaged); using the neutral fallback", storage_uri, exc_info=True
        )
        return None

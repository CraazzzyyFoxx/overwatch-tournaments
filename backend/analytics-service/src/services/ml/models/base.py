"""Common Protocol and serialisation helpers for v2 models.

Every concrete model class is a thin wrapper around a scikit-learn / LightGBM /
XGBoost booster + the feature column order it was trained with. The wrapper
takes care of:

- aligning incoming feature DataFrames to ``feature_order`` (extra columns
  dropped, missing columns added as NaN),
- delegating prediction to the underlying booster,
- saving / loading via :mod:`joblib` (preferred over :mod:`pickle` for numpy
  array compactness).

Models are persisted as ``<algorithm_id>/<version>/<file>.joblib`` under the
``ANALYTICS_MODELS_DIR`` config setting.
"""

from __future__ import annotations

import os
import tempfile
import typing
from pathlib import Path

import joblib
import pandas as pd

from src.core import config

__all__ = (
    "MLModel",
    "align_features",
    "artifact_path",
    "save_artifact",
    "load_artifact",
)


@typing.runtime_checkable
class MLModel(typing.Protocol):
    """Common surface every v2 model exposes.

    ``feature_order`` is the list of column names the underlying booster was
    fitted on; consumers should always pass DataFrames through
    :func:`align_features` before calling :meth:`predict`.
    """

    feature_order: list[str]

    def predict(self, df: pd.DataFrame) -> pd.Series: ...


def align_features(df: pd.DataFrame, feature_order: typing.Sequence[str]) -> pd.DataFrame:
    """Reorder/fill ``df`` to match ``feature_order`` exactly.

    Missing columns are inserted as ``NaN`` (LightGBM and XGBoost handle this
    natively); extra columns are silently dropped. Index is preserved so the
    caller can re-align predictions to original rows.
    """
    out = pd.DataFrame(index=df.index)
    for col in feature_order:
        if col in df.columns:
            out[col] = df[col]
        else:
            out[col] = float("nan")
    return out


def artifact_path(
    algorithm_id: int, version: str, filename: str, *, root: str | None = None
) -> Path:
    """Build the filesystem path for an artifact file.

    ``<ANALYTICS_MODELS_DIR>/<algorithm_id>/<version>/<filename>``.
    The directory is created on demand by :func:`save_artifact`.
    """
    base = Path(root or config.settings.analytics_models_dir)
    return base / str(algorithm_id) / version / filename


def save_artifact(obj: typing.Any, path: Path) -> str:
    """Atomically write ``obj`` to ``path`` via tmp+rename.

    Returns the storage URI to store in ``MLModelArtifact.storage_uri``
    (``file://`` scheme). Parent directories are created as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
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
    """Load an object previously saved via :func:`save_artifact`."""
    if storage_uri.startswith("file://"):
        return joblib.load(storage_uri.removeprefix("file://"))
    # Future: s3://, gs:// — implement when the storage backend changes.
    raise NotImplementedError(f"Unsupported storage scheme: {storage_uri}")

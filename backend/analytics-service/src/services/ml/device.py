"""Training-device helpers for ML models.

The service should train faster on GPU-capable machines, but it must remain
portable on ordinary CPU-only developer boxes and production workers. These
helpers centralise the mapping from ``ML_TRAIN_DEVICE`` to library-specific
parameters and expose ordered fallback candidates.
"""

from __future__ import annotations

import typing

from src.core.config import settings

MLTrainDevice = typing.Literal["cpu", "cuda", "gpu"]

__all__ = (
    "MLTrainDevice",
    "lightgbm_devices",
    "lightgbm_params",
    "xgboost_devices",
    "xgboost_params",
)


def _configured_device() -> str:
    return str(getattr(settings, "ml_train_device", "auto") or "auto").lower()


def _fallback_enabled() -> bool:
    return bool(getattr(settings, "ml_gpu_fallback", True))


def lightgbm_devices() -> tuple[MLTrainDevice, ...]:
    """Return LightGBM device candidates in the order they should be tried."""
    configured = _configured_device()
    fallback = _fallback_enabled()
    if configured == "cpu":
        return ("cpu",)
    if configured == "cuda":
        return ("cuda", "cpu") if fallback else ("cuda",)
    if configured == "gpu":
        return ("gpu", "cpu") if fallback else ("gpu",)
    # ``auto``: CUDA is fastest when available, OpenCL GPU is broader, CPU is
    # guaranteed. The fallback path handles CPU-only LightGBM wheels.
    return ("cuda", "gpu", "cpu") if fallback else ("cuda",)


def lightgbm_params(device: MLTrainDevice) -> dict[str, typing.Any]:
    """Return LightGBM constructor params for a device candidate."""
    if device == "cpu":
        return {"device_type": "cpu"}
    return {
        "device_type": device,
        # LightGBM recommends smaller max_bin for GPU speed.
        "max_bin": 63,
    }


def xgboost_devices() -> tuple[MLTrainDevice, ...]:
    """Return XGBoost device candidates in the order they should be tried."""
    configured = _configured_device()
    fallback = _fallback_enabled()
    if configured == "cpu":
        return ("cpu",)
    # XGBoost's modern GPU backend is CUDA. Treat ``gpu`` as a user-friendly
    # alias so one env var works across LightGBM and XGBoost.
    return ("cuda", "cpu") if fallback else ("cuda",)


def xgboost_params(device: MLTrainDevice) -> dict[str, typing.Any]:
    """Return XGBoost constructor params for a device candidate."""
    if device == "cpu":
        return {"tree_method": "hist", "device": "cpu"}
    return {"tree_method": "hist", "device": "cuda"}

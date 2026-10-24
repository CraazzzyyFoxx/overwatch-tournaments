"""Operator tool: explicit two-image conversion of the four Overwatch analytics model classes.

The model classes moved from ``src.services.ml.models.*`` to ``shared.disciplines.overwatch.analytics.models.*``. The
runtime keeps no old-path alias, so every serialized artifact is converted in a maintenance window across two images.
This is not a startup migration and it never retrains or fits anything.

    # OLD retained image (read-only model volume): old class paths importable. Run from the old service root.
    convert_discipline_artifacts.py export --inventory INVENTORY.json --model-root OLD_MODEL_ROOT --output BUNDLE_DIR \
        --old-image IMAGE_ID
    # NEW image, same pinned numerical libraries. Run from the new service root.
    convert_discipline_artifacts.py stage --bundle BUNDLE_DIR --output NEW_MODEL_ROOT --new-image IMAGE_ID
    # NEW image, workers/training/cache writers stopped. Changes ONLY ``storage_uri``, one transaction.
    convert_discipline_artifacts.py apply --receipt BUNDLE_DIR/receipt.json [--database-url URL]
    convert_discipline_artifacts.py rollback --receipt BUNDLE_DIR/receipt.json [--database-url URL]

Top-level imports are stdlib only so the same file can be mounted into the old image. ``export`` imports only the four
allowlisted legacy globals (after path/length/SHA256 validation, through an allowlisting unpickler); ``stage`` imports
only the registry-selected new exports. Unsupported scheme/class/state/frame/version blocks the whole batch.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import typing
from datetime import UTC, datetime
from pathlib import Path

FORMAT = 1
DISCIPLINE = "overwatch"

_OLD = "src.services.ml.models."
_NEW = "shared.disciplines.overwatch.analytics.models."
OLD_CONSTANT = f"{_OLD}performance_v2._ConstantClassifier"
NEW_CONSTANT = f"{_NEW}performance_v2._ConstantClassifier"

# old global -> explicit supported state layout. ``required``/``optional`` are the instance attributes the class has
# ever persisted; an absent optional (older artifact) stays absent. ``nested`` slots may hold the old constant
# classifier. ``frames`` are the verification inputs the export must be given.
CLASSES: dict[str, dict[str, typing.Any]] = {
    f"{_OLD}performance_v2.PerformanceModelV2": {
        "new": f"{_NEW}performance_v2.PerformanceModelV2",
        "kind": "performance",
        "required": ("role", "booster", "booster_q10", "booster_q90", "feature_order"),
        "optional": ("coarse_booster", "coarse_feature_order", "baseline", "shift_range"),
        "nested": ("baseline",),
        "globals": (OLD_CONSTANT,),
    },
    f"{_OLD}standings_v2.WinProbabilityModel": {
        "new": f"{_NEW}standings_v2.WinProbabilityModel",
        "kind": "standings",
        "required": ("booster", "baseline"),
        "optional": ("feature_order",),
        "nested": (),
        "globals": (),
    },
    f"{_OLD}shift_v2.ShiftModelV2": {
        "new": f"{_NEW}shift_v2.ShiftModelV2",
        "kind": "shift",
        "required": (),
        "optional": (
            "w_team",
            "w_os",
            "indiv_scale_top",
            "indiv_scale_bottom",
            "indiv_clamp_top",
            "indiv_clamp_bottom",
            "dominance_gain",
            "dominance_cap",
            "placement_floor",
            "shift_range",
            "clamp_top_grid_ref",
            "feature_order",
        ),
        "nested": (),
        "globals": (),
    },
}
FRAME_NAMES = ("frame", "main", "coarse", "baseline", "matrix")
LIBRARIES = ("numpy", "pandas", "sklearn", "scipy", "lightgbm", "xgboost", "joblib")
# Audited exact (module, name) allowlist: what the supported estimator graphs, DataFrames/ndarrays (incl. the
# object-dtype payloads joblib pickles) and verification frames reference. Nothing is allowed by package prefix; a
# real artifact that needs another global blocks until a reviewer adds it here.
_ALLOWED_GLOBALS = frozenset(
    {
        ("builtins", "slice"),
        ("collections", "OrderedDict"),
        ("collections", "defaultdict"),
        ("joblib.numpy_pickle", "NumpyArrayWrapper"),
        ("lightgbm.basic", "Booster"),
        ("lightgbm.sklearn", "LGBMRegressor"),
        ("numpy", "dtype"),
        ("numpy", "ndarray"),
        ("numpy._core.multiarray", "_reconstruct"),
        ("numpy._core.multiarray", "scalar"),
        ("pandas._libs.internals", "_unpickle_block"),
        ("pandas.core.frame", "DataFrame"),
        ("pandas.core.indexes.base", "Index"),
        ("pandas.core.indexes.base", "_new_Index"),
        ("pandas.core.indexes.range", "RangeIndex"),
        ("pandas.core.internals.managers", "BlockManager"),
        ("sklearn.calibration", "CalibratedClassifierCV"),
        ("sklearn.calibration", "_CalibratedClassifier"),
        ("sklearn.impute._base", "SimpleImputer"),
        ("sklearn.isotonic", "IsotonicRegression"),
        ("sklearn.linear_model._logistic", "LogisticRegression"),
        ("sklearn.pipeline", "Pipeline"),
        ("sklearn.preprocessing._data", "StandardScaler"),
        ("xgboost.core", "Booster"),
        ("xgboost.sklearn", "XGBClassifier"),
    }
)
_REGISTRY_FIELDS = (
    "id",
    "algorithm_id",
    "algorithm_name",
    "model_kind",
    "role_id",
    "dimension_id",
    "version",
    "feature_version",
    "training_cutoff_tournament_id",
    "is_active",
    "metrics",
    "feature_importance",
)
_INVENTORY_FIELDS = frozenset(
    {*_REGISTRY_FIELDS, "discipline", "storage_uri", "sha256", "length", "expected_class", "frames"}
)


class ConversionError(Exception):
    """A blocking condition: nothing was skipped and nothing was changed beyond what the message states."""


# ---------------------------------------------------------------------------
# Bytes, paths, receipts
# ---------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: typing.Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _write_immutable(path: Path, data: bytes) -> bool:
    """Write once; identical existing bytes are reused, different bytes are a conflict. True when written."""
    if path.exists():
        if _sha(path.read_bytes()) != _sha(data):
            raise ConversionError(f"conflicting existing output (never overwritten): {path}")
        return False
    _atomic_replace(path, data)
    return True


def _uri_path(uri: str, label: str) -> Path:
    if not isinstance(uri, str) or not uri.startswith("file://"):
        raise ConversionError(f"{label}: unsupported storage scheme {uri!r} (only local file:// is supported)")
    path = Path(uri.removeprefix("file://"))
    if not path.is_absolute():
        raise ConversionError(f"{label}: file URI must be absolute: {uri!r}")
    return path


def _read_verified(uri: str, root: Path | None, sha256: str, length: int, label: str) -> bytes:
    """Read an allowlisted local file and prove its digest before anyone parses it."""
    path = _uri_path(uri, label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise ConversionError(f"{label}: file is missing: {path}") from None
    if root is not None:
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ConversionError(f"{label}: {path} is outside the approved model root {root}") from None
    if not resolved.is_file():
        raise ConversionError(f"{label}: not a regular file: {path}")
    data = resolved.read_bytes()
    if len(data) != length or _sha(data) != sha256:
        raise ConversionError(
            f"{label}: {path} length/SHA256 differ from the inventory (len={len(data)} sha={_sha(data)})"
        )
    return data


def _read_json(path: Path, label: str) -> dict[str, typing.Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConversionError(f"{label}: cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConversionError(f"{label}: {path} is not a JSON object")
    return value


def _libraries() -> dict[str, str]:
    versions = {"python": ".".join(map(str, sys.version_info[:3]))}
    for name in LIBRARIES:
        versions[name] = str(importlib.import_module(name).__version__)
    return versions


# ---------------------------------------------------------------------------
# Allowlisting unpickler (joblib's own NumpyUnpickler; only its class lookup is narrowed)
# ---------------------------------------------------------------------------


def _load(data: bytes, allowed: typing.Collection[str], seen: set[str] | None = None) -> typing.Any:
    """``joblib.load`` of verified bytes where only the exact (module, name) globals in ``_ALLOWED_GLOBALS`` plus the
    artifact's own ``allowed`` application globals resolve.

    The same resolver guards every nested pickle: joblib reads object-dtype ndarray payloads with a plain
    ``pickle.load``, so that module reference is replaced by a proxy whose ``load`` uses the restricted unpickler.
    Dotted names are rejected outright (``find_class`` would otherwise walk attributes such as ``os.system``).
    """
    import pickle
    from unittest import mock

    import joblib
    from joblib import numpy_pickle
    from joblib.numpy_pickle import NumpyUnpickler

    exact = {tuple(full.rsplit(".", 1)) for full in allowed}

    def check(module: str, name: str) -> None:
        if "." in name or ((module, name) not in exact and (module, name) not in _ALLOWED_GLOBALS):
            raise ConversionError(f"pickle references a non-allowlisted global: {module}.{name}")
        if seen is not None and (module, name) in exact:
            seen.add(f"{module}.{name}")

    def numpy_find_class(self: typing.Any, module: str, name: str) -> typing.Any:
        check(module, name)
        return pickle._Unpickler.find_class(self, module, name)  # joblib's pure-Python base

    class Restricted(pickle.Unpickler):
        def find_class(self, module: str, name: str) -> typing.Any:
            check(module, name)
            return super().find_class(module, name)

    class RestrictedPickle:
        def __getattr__(self, attribute: str) -> typing.Any:
            return getattr(pickle, attribute)

        @staticmethod
        def load(file: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            return Restricted(file, *args, **kwargs).load()

    with (
        mock.patch.object(NumpyUnpickler, "find_class", numpy_find_class),
        mock.patch.object(numpy_pickle, "pickle", RestrictedPickle()),
    ):
        return joblib.load(io.BytesIO(data))


def _load_plain(data: bytes, label: str) -> typing.Any:
    try:
        return _load(data, ())
    except ConversionError as exc:
        raise ConversionError(f"{label}: {exc}") from exc


def _dump(value: typing.Any) -> bytes:
    import joblib

    buffer = io.BytesIO()
    joblib.dump(value, buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Verification outputs (bit-exact digests of real predictions)
# ---------------------------------------------------------------------------


def _array_digest(arrays: list[typing.Any], meta: dict[str, typing.Any]) -> tuple[str, str | None]:
    import numpy as np

    hasher, mask_hasher, has_mask = hashlib.sha256(), hashlib.sha256(), False
    hasher.update(json.dumps(meta, sort_keys=True).encode())
    for array in arrays:
        array = np.ascontiguousarray(array)
        hasher.update(f"{array.dtype.str}{array.shape}".encode())
        if array.dtype.kind in "fiub":
            hasher.update(array.tobytes())
        elif array.dtype.kind == "O":  # string/mixed input columns (e.g. role): exact text, no float semantics
            hasher.update(json.dumps([repr(item) for item in array.tolist()]).encode())
        else:
            raise ConversionError(f"verification value has unsupported dtype {array.dtype}")
        if array.dtype.kind == "f":
            has_mask = True
            mask_hasher.update(np.isnan(array).tobytes())
    return hasher.hexdigest(), (mask_hasher.hexdigest() if has_mask else None)


def _record(value: typing.Any) -> dict[str, typing.Any]:
    """Canonical digest of a DataFrame/Series/ndarray: values bit-for-bit, column names, index, NaN mask."""
    import numpy as np
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        meta = {
            "type": "frame",
            "columns": [str(c) for c in value.columns],
            "index": [str(i) for i in value.index.tolist()],
        }
        arrays = [value[column].to_numpy() for column in value.columns]
    elif isinstance(value, pd.Series):
        meta = {"type": "series", "name": str(value.name), "index": [str(i) for i in value.index.tolist()]}
        arrays = [value.to_numpy()]
    else:
        array = np.asarray(value)
        meta, arrays = {"type": "array", "shape": list(array.shape)}, [array]
    digest, mask = _array_digest(arrays, meta)
    return {"digest": digest, "nan_mask_digest": mask, "shape": [len(arrays[0]) if arrays else 0, len(arrays)]}


def _required_frames(kind: str, obj: typing.Any) -> tuple[str, ...]:
    if kind == "performance":
        names = ["frame", "main", "baseline"] if getattr(obj, "baseline", None) is not None else ["frame", "main"]
        if getattr(obj, "coarse_booster", None) is not None:
            names.append("coarse")
        return tuple(names)
    if kind == "standings":
        return ("frame", "matrix")
    return ("frame",)


def _outputs(kind: str, obj: typing.Any, frames: dict[str, typing.Any]) -> dict[str, dict[str, typing.Any]]:
    """Run every prediction surface of the wrapper and its estimators on the supplied frames."""
    out: dict[str, typing.Any] = {}
    if kind == "performance":
        # Confidence and coarse bands changed on purpose after the move; the quantile boosters are compared below.
        out["predict_match"] = obj.predict_match(frames["frame"])[["y_hat"]]
        out["predict"] = obj.predict(frames["frame"])
        out["booster"] = obj.booster.predict(frames["main"])
        out["booster_q10"] = obj.booster_q10.predict(frames["main"])
        out["booster_q90"] = obj.booster_q90.predict(frames["main"])
        if getattr(obj, "coarse_booster", None) is not None:
            out["coarse_booster"] = obj.coarse_booster.predict(frames["coarse"])
        if getattr(obj, "baseline", None) is not None:
            out["baseline"] = obj.baseline.predict_proba(frames["baseline"])
    elif kind == "standings":
        out["predict_proba"] = obj.predict_proba(frames["frame"])
        out["predict"] = obj.predict(frames["frame"])
        out["booster"] = obj.booster.predict_proba(frames["matrix"])
        out["baseline"] = obj.baseline.predict_proba(frames["matrix"])
    # Shift v2 holds only blend constants, proven by the state digest; its blend code changed on purpose after the move.
    return {name: _record(value) for name, value in out.items()}


# ---------------------------------------------------------------------------
# State bundles
# ---------------------------------------------------------------------------


def _state_digest(state: dict[str, typing.Any]) -> dict[str, str]:
    import joblib

    return {key: joblib.hash(value) for key, value in sorted(state.items())}


def _marker(old_global: str, state: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {"class": old_global, "state": state}


def _is_marker(value: typing.Any) -> bool:
    return isinstance(value, dict) and set(value) == {"class", "state"} and value["class"] == OLD_CONSTANT


def _export_state(obj: typing.Any, spec: dict[str, typing.Any], label: str) -> dict[str, typing.Any]:
    state = dict(vars(obj))
    unknown = sorted(set(state) - {*spec["required"], *spec["optional"]})
    missing = sorted(set(spec["required"]) - set(state))
    if unknown or missing:
        raise ConversionError(f"{label}: unsupported state layout (unknown={unknown}, missing required={missing})")
    for slot in spec["nested"]:
        value = state.get(slot)
        if value is not None and f"{type(value).__module__}.{type(value).__qualname__}" == OLD_CONSTANT:
            if set(vars(value)) != {"prior"}:
                raise ConversionError(f"{label}: unsupported _ConstantClassifier state {sorted(vars(value))}")
            state[slot] = _marker(OLD_CONSTANT, dict(vars(value)))
    return state


def _new_class(new_global: str) -> type:
    """Resolve a mapped class through the Overwatch analytics package itself (no alias)."""
    from shared.disciplines.overwatch import analytics

    cls = getattr(analytics, new_global.rsplit(".", 1)[1], None)
    if cls is None or f"{cls.__module__}.{cls.__qualname__}" != new_global:
        raise ConversionError(f"the new image does not declare {new_global}")
    return cls


def _build(bundle: dict[str, typing.Any], label: str) -> typing.Any:
    """``object.__new__`` plus the approved state: no ``__init__``, no ``fit``, no defaults filled in."""
    spec = CLASSES.get(bundle.get("class"))
    if bundle.get("format") != FORMAT or spec is None or not isinstance(bundle.get("state"), dict):
        raise ConversionError(f"{label}: unsupported state bundle")
    state = dict(bundle["state"])
    for slot in spec["nested"]:
        value = state.get(slot)
        if _is_marker(value):
            if set(value["state"]) != {"prior"}:
                raise ConversionError(f"{label}: unsupported _ConstantClassifier state")
            constant = object.__new__(_new_class(NEW_CONSTANT))
            constant.__dict__.update(value["state"])
            state[slot] = constant
        elif isinstance(value, dict):
            raise ConversionError(f"{label}: unsupported nested state in {slot!r}")
    obj = object.__new__(_new_class(spec["new"]))
    obj.__dict__.update(state)
    return obj


def _state_of_new(obj: typing.Any, spec: dict[str, typing.Any]) -> dict[str, typing.Any]:
    state = dict(vars(obj))
    for slot in spec["nested"]:
        value = state.get(slot)
        if value is not None and f"{type(value).__module__}.{type(value).__qualname__}" == NEW_CONSTANT:
            state[slot] = _marker(OLD_CONSTANT, dict(vars(value)))
    return state


@contextlib.contextmanager
def _fit_forbidden() -> typing.Iterator[None]:
    """Conversion only reads: any estimator ``fit`` is a hard failure."""
    from unittest import mock

    import lightgbm
    import xgboost
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    def no_fit(*_a: typing.Any, **_k: typing.Any) -> typing.NoReturn:
        raise ConversionError("fit is forbidden during artifact conversion")

    with contextlib.ExitStack() as stack:
        for target in (
            lightgbm.LGBMRegressor,
            xgboost.XGBClassifier,
            CalibratedClassifierCV,
            LogisticRegression,
            Pipeline,
        ):
            stack.enter_context(mock.patch.object(target, "fit", no_fit))
        yield


# ---------------------------------------------------------------------------
# export (old image)
# ---------------------------------------------------------------------------


def _validate_inventory(raw: dict[str, typing.Any]) -> list[dict[str, typing.Any]]:
    if raw.get("format") != FORMAT or set(raw) != {"format", "artifacts"} or not isinstance(raw["artifacts"], list):
        raise ConversionError(f"inventory: unsupported format (expected {{'format': {FORMAT}, 'artifacts': [...]}})")
    entries, seen = [], set()
    for entry in raw["artifacts"]:
        label = f"artifact {entry.get('id') if isinstance(entry, dict) else entry!r}"
        if not isinstance(entry, dict) or set(entry) != _INVENTORY_FIELDS:
            missing = sorted(_INVENTORY_FIELDS - set(entry)) if isinstance(entry, dict) else "all"
            extra = sorted(set(entry) - _INVENTORY_FIELDS) if isinstance(entry, dict) else []
            raise ConversionError(f"{label}: inventory fields differ (missing={missing}, unknown={extra})")
        if not isinstance(entry["id"], int) or entry["id"] in seen:
            raise ConversionError(f"{label}: id must be a unique integer")
        seen.add(entry["id"])
        spec = CLASSES.get(entry["expected_class"])
        if spec is None:
            raise ConversionError(f"{label}: unsupported class {entry['expected_class']!r}")
        if entry["discipline"] != DISCIPLINE or entry["model_kind"] != spec["kind"]:
            raise ConversionError(f"{label}: discipline/model_kind do not match {entry['expected_class']}")
        if not isinstance(entry["frames"], dict) or not set(entry["frames"]) <= set(FRAME_NAMES):
            raise ConversionError(f"{label}: unknown verification frame names {sorted(entry['frames'])}")
        for name, ref in entry["frames"].items():
            if not isinstance(ref, dict) or set(ref) != {"storage_uri", "sha256", "length"}:
                raise ConversionError(f"{label}: frame {name!r} needs storage_uri, sha256, length")
        entries.append(entry)
    return sorted(entries, key=lambda e: e["id"])


def _preflight(entry: dict[str, typing.Any], root: Path) -> tuple[bytes, dict[str, bytes]]:
    label = f"artifact {entry['id']} ({entry['storage_uri']})"
    data = _read_verified(entry["storage_uri"], root, entry["sha256"], entry["length"], label)
    frames = {
        name: _read_verified(ref["storage_uri"], root, ref["sha256"], ref["length"], f"{label} frame {name!r}")
        for name, ref in sorted(entry["frames"].items())
    }
    return data, frames


def _export_one(
    entry: dict[str, typing.Any], data: bytes, frame_bytes: dict[str, bytes]
) -> tuple[dict[str, typing.Any], dict[str, bytes]]:
    label = f"artifact {entry['id']} ({entry['storage_uri']})"
    spec = CLASSES[entry["expected_class"]]
    seen: set[str] = set()
    try:
        obj = _load(data, (entry["expected_class"], *spec["globals"]), seen)
    except ConversionError as exc:
        raise ConversionError(f"{label}: {exc}") from exc
    actual = f"{type(obj).__module__}.{type(obj).__qualname__}"
    if actual != entry["expected_class"]:
        raise ConversionError(f"{label}: holds {actual}, inventory expects {entry['expected_class']}")
    state = _export_state(obj, spec, label)

    frames: dict[str, typing.Any] = {}
    files: dict[str, bytes] = {}
    frame_receipt: dict[str, typing.Any] = {}
    for name, ref in sorted(entry["frames"].items()):
        raw = frame_bytes[name]
        frames[name] = _load_plain(raw, f"{label} frame {name!r}")
        relative = f"frames/{ref['sha256']}.joblib"
        files[relative] = raw
        frame_receipt[name] = {
            "path": relative,
            "sha256": ref["sha256"],
            "length": ref["length"],
            **_record(frames[name]),
        }
    required = _required_frames(spec["kind"], obj)
    if set(frames) != set(required):
        raise ConversionError(f"{label}: verification frames {sorted(frames)} differ from required {sorted(required)}")

    bundle_bytes = _dump({"format": FORMAT, "class": entry["expected_class"], "state": state})
    reloaded = _load_plain(bundle_bytes, f"{label} state bundle")
    if set(reloaded["state"]) != set(state):
        raise ConversionError(f"{label}: state bundle does not round-trip")
    outputs = _outputs(spec["kind"], obj, frames)
    bundle_path = f"artifacts/{entry['id']}.state.joblib"
    files[bundle_path] = bundle_bytes
    modules = {name.rsplit(".", 1)[0] for name in seen | {entry["expected_class"]}}
    artifact = {
        "registry": {field: entry[field] for field in _REGISTRY_FIELDS},
        "old": {
            "storage_uri": entry["storage_uri"],
            "sha256": entry["sha256"],
            "length": entry["length"],
            "class": entry["expected_class"],
        },
        "old_modules": {m: getattr(sys.modules.get(m), "__file__", None) for m in sorted(modules)},
        "bundle": {
            "path": bundle_path,
            "sha256": _sha(bundle_bytes),
            "length": len(bundle_bytes),
            "state_digest": _state_digest(reloaded["state"]),
        },
        "frames": frame_receipt,
        "outputs": outputs,
        "new": None,
    }
    return artifact, files


def export(inventory: Path, model_root: Path, output: Path, old_image: str) -> dict[str, typing.Any]:
    inventory_bytes = inventory.read_bytes()
    try:
        raw = json.loads(inventory_bytes)
    except ValueError as exc:
        raise ConversionError(f"inventory: invalid JSON: {exc}") from exc
    entries = _validate_inventory(raw if isinstance(raw, dict) else {})
    root = model_root.resolve(strict=True)
    # Pass 1: every artifact and frame path, root, length and SHA256 is proven and its bytes retained BEFORE anything is
    # deserialized, so a bad later entry can never follow the execution of an earlier pickle.
    preflight = [_preflight(entry, root) for entry in entries]
    # Pass 2: the whole batch is converted in memory before the first output byte is written.
    converted = [_export_one(entry, *loaded) for entry, loaded in zip(entries, preflight, strict=True)]
    artifacts = [artifact for artifact, _ in converted]
    receipt = {
        "format": FORMAT,
        "status": "exported",
        "old_image": old_image,
        "new_image": None,
        "libraries": _libraries(),
        "inventory_sha256": _sha(inventory_bytes),
        "artifacts": artifacts,
    }
    receipt_path = output / "receipt.json"
    if receipt_path.exists():
        existing = _read_json(receipt_path, "existing receipt")
        # Later stages add `new`, `new_image`, `status` and the applied/rolled_back records; nothing else may differ.
        same = {k: existing.get(k) for k in receipt} | {"status": "exported", "new_image": None}
        same["artifacts"] = [{**a, "new": None} for a in existing.get("artifacts", [])]
        if same != receipt:
            raise ConversionError(f"conflicting existing receipt (never overwritten): {receipt_path}")
    for _, files in converted:
        for relative, blob in files.items():
            _write_immutable(output / relative, blob)
    if not receipt_path.exists():
        _atomic_replace(receipt_path, _json_bytes(receipt))
    return receipt


# ---------------------------------------------------------------------------
# stage (new image)
# ---------------------------------------------------------------------------


def _load_receipt(path: Path, statuses: tuple[str, ...]) -> dict[str, typing.Any]:
    receipt = _read_json(path, "receipt")
    if receipt.get("format") != FORMAT or not isinstance(receipt.get("artifacts"), list):
        raise ConversionError(f"receipt: unsupported format in {path}")
    if receipt.get("status") not in statuses:
        raise ConversionError(f"receipt status is {receipt.get('status')!r}; this command needs one of {statuses}")
    ids = [a["registry"]["id"] for a in receipt["artifacts"]]
    if ids != sorted(set(ids)):
        raise ConversionError("receipt: artifacts must be unique and in id order")
    return receipt


def _check_libraries(receipt: dict[str, typing.Any]) -> None:
    current = _libraries()
    if receipt["libraries"] != current:
        raise ConversionError(f"numerical dependency versions differ: receipt={receipt['libraries']} current={current}")


def _read_bundle_file(base: Path, ref: dict[str, typing.Any], label: str) -> bytes:
    path = base / ref["path"]
    if not path.is_file():
        raise ConversionError(f"{label}: bundle file is missing or truncated away: {path}")
    data = path.read_bytes()
    if len(data) != ref["length"] or _sha(data) != ref["sha256"]:
        raise ConversionError(f"{label}: bundle file {path} length/SHA256 differ from the receipt")
    return data


def _approved(base: Path, artifact: dict[str, typing.Any]) -> tuple[dict[str, typing.Any], dict[str, typing.Any]]:
    label = f"artifact {artifact['registry']['id']}"
    bundle = _load_plain(_read_bundle_file(base, artifact["bundle"], label), f"{label} state bundle")
    if (
        bundle.get("class") != artifact["old"]["class"]
        or _state_digest(bundle["state"]) != artifact["bundle"]["state_digest"]
    ):
        raise ConversionError(f"{label}: state bundle does not match the receipt")
    frames = {}
    for name, ref in artifact["frames"].items():
        frames[name] = _load_plain(_read_bundle_file(base, ref, f"{label} frame {name!r}"), f"{label} frame {name!r}")
    return bundle, frames


def _verify_target(path: Path, artifact: dict[str, typing.Any], base: Path) -> dict[str, typing.Any]:
    """Reopen a staged file with the ordinary ``joblib.load`` and compare state and every recorded prediction."""
    import joblib

    label = f"artifact {artifact['registry']['id']}"
    bundle, frames = _approved(base, artifact)
    spec = CLASSES[bundle["class"]]
    data = path.read_bytes()
    with _fit_forbidden():
        try:
            loaded = joblib.load(path)
        except Exception as exc:  # noqa: BLE001 -- any unreadable converted file is a blocking condition
            raise ConversionError(f"{label}: {path} cannot be loaded by the ordinary loader: {exc!r}") from exc
        expected = _new_class(spec["new"])
        if type(loaded) is not expected:
            raise ConversionError(f"{label}: {path} holds {type(loaded).__module__}.{type(loaded).__qualname__}")
        state = _state_of_new(loaded, spec)
        if set(state) != set(bundle["state"]) or _state_digest(state) != _state_digest(bundle["state"]):
            raise ConversionError(f"{label}: restored state differs from the approved state ({path})")
        outputs = _outputs(spec["kind"], loaded, frames)
    comparisons = {
        name: {"old": artifact["outputs"].get(name), "new": record, "equal": artifact["outputs"].get(name) == record}
        for name, record in outputs.items()
    }
    if set(outputs) != set(artifact["outputs"]) or not all(c["equal"] for c in comparisons.values()):
        bad = sorted(n for n, c in comparisons.items() if not c["equal"]) or sorted(
            set(outputs) ^ set(artifact["outputs"])
        )
        raise ConversionError(f"{label}: predictions differ from the original artifact: {bad}")
    return {"sha256": _sha(data), "length": len(data), "comparisons": {n: c["equal"] for n, c in comparisons.items()}}


def stage(bundle: Path, output: Path, new_image: str) -> dict[str, typing.Any]:
    from src.services.ml.models.base import save_artifact

    receipt_path = bundle / "receipt.json"
    receipt = _load_receipt(receipt_path, ("exported", "staged"))
    if receipt["new_image"] not in (None, new_image):
        raise ConversionError(f"receipt was staged by image {receipt['new_image']!r}, not {new_image!r}")
    _check_libraries(receipt)
    for old_global in CLASSES:
        if importlib.util.find_spec(old_global.rsplit(".", 1)[0]) is not None:
            raise ConversionError(f"{old_global.rsplit('.', 1)[0]} is importable: stage must run in the new image only")
    root = output.resolve()
    staged: list[str] = []
    try:
        for artifact in receipt["artifacts"]:
            target = root / "discipline06" / str(artifact["registry"]["id"]) / f"{artifact['old']['sha256']}.joblib"
            uri = f"file://{target.as_posix()}"
            recorded = artifact["new"]
            if recorded is not None and recorded["uri"] != uri:
                raise ConversionError(
                    f"artifact {artifact['registry']['id']}: already staged at {recorded['uri']}, not {uri}"
                )
            created = False
            if not target.exists():
                bundle_state, _ = _approved(bundle, artifact)
                if uri != save_artifact(_build(bundle_state, f"artifact {artifact['registry']['id']}"), target):
                    raise ConversionError("save_artifact returned an unexpected URI")
                created = True
            try:
                result = _verify_target(target, artifact, bundle)
            except BaseException:
                if created:
                    target.unlink()
                raise
            if recorded is not None and (recorded["sha256"], recorded["length"]) != (
                result["sha256"],
                result["length"],
            ):
                raise ConversionError(f"artifact {artifact['registry']['id']}: staged file differs from the receipt")
            artifact["new"] = {"uri": uri, **result}
            staged.append(str(target))
    except BaseException as exc:
        _atomic_replace(
            bundle / "stage-failure.json",
            _json_bytes(
                {
                    "error": str(exc),
                    "staged_files_existing": sorted(str(p) for p in root.glob("discipline06/*/*.joblib")),
                }
            ),
        )
        raise
    receipt.update(status="staged", new_image=new_image)
    _atomic_replace(receipt_path, _json_bytes(receipt))
    (bundle / "stage-failure.json").unlink(missing_ok=True)
    return receipt


# ---------------------------------------------------------------------------
# apply / rollback (new image, database)
# ---------------------------------------------------------------------------

_SELECT = (
    "SELECT a.id, a.algorithm_id, g.name AS algorithm_name, a.model_kind, a.role_id, a.dimension_id, a.version, "
    "a.feature_version, a.training_cutoff_tournament_id, a.is_active, a.metrics, a.feature_importance, a.storage_uri "
    "FROM analytics.ml_model_artifact a JOIN analytics.algorithms g ON g.id = a.algorithm_id "
    "WHERE a.id = ANY(:ids) ORDER BY a.id FOR UPDATE OF a"
)


_UNCONVERTED = (
    "SELECT id FROM analytics.ml_model_artifact WHERE model_kind = ANY(:kinds) AND id <> ALL(:ids) "
    "AND storage_uri NOT LIKE '%/discipline06/%' ORDER BY id"
)


def _engine(database_url: str | None) -> typing.Any:
    import sqlalchemy as sa

    if database_url is None:
        from src.core.config import settings

        database_url = settings.db_url
    return sa.create_engine(database_url)


def _check_old_files(receipt: dict[str, typing.Any]) -> None:
    for artifact in receipt["artifacts"]:
        old = artifact["old"]
        _read_verified(
            old["storage_uri"], None, old["sha256"], old["length"], f"artifact {artifact['registry']['id']} original"
        )


def _switch(receipt_path: Path, database_url: str | None, *, target: str) -> dict[str, typing.Any]:
    """Move every manifest row's ``storage_uri`` old<->new in one transaction; nothing else is written."""
    import sqlalchemy as sa

    forward = target == "new"
    receipt = _load_receipt(receipt_path, ("staged", "applied", "rolled_back"))
    if any(a["new"] is None for a in receipt["artifacts"]):
        raise ConversionError("receipt is not fully staged")
    base = receipt_path.parent
    if forward:
        _check_libraries(receipt)
    for artifact in receipt["artifacts"]:
        new, label = artifact["new"], f"artifact {artifact['registry']['id']} converted"
        _read_verified(new["uri"], None, new["sha256"], new["length"], label)
        if forward:
            _verify_target(_uri_path(new["uri"], "staged").resolve(strict=True), artifact, base)
    _check_old_files(receipt)  # originals stay intact and are what a rollback restores
    uris = {a["registry"]["id"]: (a["old"]["storage_uri"], a["new"]["uri"]) for a in receipt["artifacts"]}
    ids = sorted(uris)
    source, destination = (0, 1) if forward else (1, 0)
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            rows = {r["id"]: r for r in conn.execute(sa.text(_SELECT), {"ids": ids}).mappings()}
            if sorted(rows) != ids:
                raise ConversionError(f"registry rows missing: {sorted(set(ids) - set(rows))}")
            for artifact in receipt["artifacts"]:
                row, snapshot = rows[artifact["registry"]["id"]], artifact["registry"]
                changed = sorted(f for f in snapshot if row[f] != snapshot[f])
                if changed:
                    raise ConversionError(f"artifact {snapshot['id']}: registry changed since export: {changed}")
            if forward:  # an inventory that left a row out would strand an old-path pickle the runtime cannot load
                kinds = sorted({spec["kind"] for spec in CLASSES.values()})
                stranded = [r[0] for r in conn.execute(sa.text(_UNCONVERTED), {"kinds": kinds, "ids": ids})]
                if stranded:
                    raise ConversionError(
                        f"registry artifacts {stranded} are outside the receipt and still point at a non-converted URI"
                    )
            current = {i: rows[i]["storage_uri"] for i in ids}
            if all(current[i] == uris[i][destination] for i in ids):
                changed_rows = 0
            elif all(current[i] == uris[i][source] for i in ids):
                for i in ids:
                    updated = conn.execute(
                        sa.text(
                            "UPDATE analytics.ml_model_artifact SET storage_uri = :dst WHERE id = :id AND storage_uri = :src"
                        ),
                        {"id": i, "src": uris[i][source], "dst": uris[i][destination]},
                    )
                    if updated.rowcount != 1:
                        raise ConversionError(f"artifact {i}: storage_uri changed concurrently")
                changed_rows = len(ids)
            else:
                raise ConversionError(
                    f"mixed or unknown storage_uri state (blocking): { {i: current[i] for i in ids} }"
                )
    finally:
        engine.dispose()
    receipt.pop("applied", None)
    receipt.pop("rolled_back", None)
    receipt["status"] = "applied" if forward else "rolled_back"
    receipt["applied" if forward else "rolled_back"] = {
        "at": datetime.now(UTC).isoformat(),
        "rows_changed": changed_rows,
    }
    _atomic_replace(receipt_path, _json_bytes(receipt))
    return receipt


def apply(receipt: Path, database_url: str | None) -> dict[str, typing.Any]:
    return _switch(receipt, database_url, target="new")


def rollback(receipt: Path, database_url: str | None) -> dict[str, typing.Any]:
    return _switch(receipt, database_url, target="old")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="old image: verify inventoried artifacts and write the state bundle + receipt")
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--old-image", required=True, help="exact old image identifier (digest) the operator ran this in")
    p = sub.add_parser("stage", help="new image: rebuild, write immutable converted files and verify them")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--new-image", required=True, help="exact new image identifier (digest)")
    for name, text in (
        ("apply", "switch storage_uri to the staged files"),
        ("rollback", "restore the original storage_uri set"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--receipt", type=Path, required=True)
        p.add_argument(
            "--database-url", default=os.environ.get("DATABASE_URL"), help="SQLAlchemy URL (default: service settings)"
        )
    args = parser.parse_args(argv)
    sys.path.insert(0, os.getcwd())  # the service root of whichever image this runs in
    try:
        if args.command == "export":
            result = export(args.inventory, args.model_root, args.output, args.old_image)
        elif args.command == "stage":
            result = stage(args.bundle, args.output, args.new_image)
        elif args.command == "apply":
            result = apply(args.receipt, args.database_url)
        else:
            result = rollback(args.receipt, args.database_url)
    except ConversionError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "artifacts": [a["registry"]["id"] for a in result["artifacts"]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Two-image conversion of the four Overwatch model classes, proven against the T4 pre-move pickles.

``fixtures/ml_pre_move/*.old.joblib`` are whole-object pickles of the removed ``src.services.ml.models.*`` class paths
(provenance and SHA256 in ``fixtures/ml_pre_move/manifest.json``). The runtime has no alias for those paths, so:

* ``export`` runs in a separate Python process whose ``src``/``shared`` come from ``git archive 962d7df26`` (the frozen
  pre-move source, the stand-in for the retained old image);
* ``stage`` runs in a separate process under the current code, and the staged files are reopened with the ordinary
  ``joblib.load`` (old modules absent) and compared bit-for-bit with the frozen prediction receipts;
* ``apply``/``rollback`` run against a real PostgreSQL clone at head.

No test fits or retrains anything; fixture estimators are the real LightGBM/XGBoost/scikit-learn objects.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import typing
from collections.abc import Iterator
from pathlib import Path

import joblib
import numpy as np
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from shared import models
from shared.disciplines.overwatch import analytics as ow_analytics
from shared.testing.stats_parity import legacy_database
from src.services.ml.models.base import load_artifact
from tests.test_ml_prediction_parity import (
    GOLDEN,
    ROLES,
    STATE,
    _assert_equal,
    _fit_forbidden,
    _fitted_performance,
    _fixture_state,
    _ow,
    _shift_outputs,
    _standings_outputs,
    _to_json,
    evaluation_frame,
)

SERVICE_ROOT = Path(__file__).resolve().parents[1]
TOOL = SERVICE_ROOT / "scripts" / "convert_discipline_artifacts.py"
OLD_REVISION = "962d7df26"
MANIFEST = json.loads((STATE / "manifest.json").read_text(encoding="utf-8"))
OLD_IMAGE = f"git-archive:{OLD_REVISION}"
NEW_IMAGE = "current-worktree"


def _load_tool() -> typing.Any:
    spec = importlib.util.spec_from_file_location("convert_discipline_artifacts", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

# id, fixture, model kind, role, active, version, registry metrics. 9008 shares 9005's old file (duplicate shared URI);
# 9006-9008 are inactive history.
ROWS = (
    (9001, "performance_tank", "performance", "tank", True, "2.0.0"),
    (9002, "performance_damage", "performance", "damage", True, "2.0.0"),
    (9003, "performance_support", "performance", "support", True, "2.0.0"),
    (9004, "standings", "standings", None, True, "2.2.0"),
    (9005, "shift_default", "shift", None, True, "2.0.0"),
    (9006, "shift_tuned", "shift", None, False, "1.9.0"),
    (9007, "shift_old_missing", "shift", None, False, "1.8.0"),
    (9008, "shift_default", "shift", None, False, "1.7.0"),
)
KIND_CLASS = {"performance": "PerformanceModelV2", "standings": "WinProbabilityModel", "shift": "ShiftModelV2"}
OLD_GLOBAL = {
    "performance": "src.services.ml.models.performance_v2.PerformanceModelV2",
    "standings": "src.services.ml.models.standings_v2.WinProbabilityModel",
    "shift": "src.services.ml.models.shift_v2.ShiftModelV2",
}
ALGORITHM = {"performance": "Performance ML v2", "standings": "Standings MC v2", "shift": "OpenSkill + ML"}


# ---------------------------------------------------------------------------
# Old-image stand-in and process helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def old_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The frozen pre-move ``src`` + ``shared``, extracted from git; its service root."""
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=SERVICE_ROOT, capture_output=True, text=True, check=False
    )
    if top.returncode:
        pytest.skip("git checkout unavailable: cannot extract the frozen pre-move source")
    archive = subprocess.run(
        ["git", "archive", OLD_REVISION, "--", "backend/shared", "backend/analytics-service/src"],
        cwd=top.stdout.strip(),
        capture_output=True,
        check=False,
    )
    assert archive.returncode == 0, f"pre-move revision {OLD_REVISION} is not in this checkout: {archive.stderr!r}"
    root = tmp_path_factory.mktemp("old_image")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(root, filter="data")
    return root / "backend" / "analytics-service"


def _run(*args: str, cwd: Path, pythonpath: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    return subprocess.run(
        [sys.executable, str(TOOL), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=600, check=False
    )


def run_old(old_tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(*args, cwd=old_tree, pythonpath=os.pathsep.join([str(old_tree), str(old_tree.parent)]))


def run_new(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(*args, cwd=SERVICE_ROOT)


def run_old_code(old_tree: Path, code: str, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join([str(old_tree), str(old_tree.parent)])
    done = subprocess.run(
        [sys.executable, "-c", code, *args], cwd=old_tree, env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


# ---------------------------------------------------------------------------
# Inventory over the T4 pre-move pickles
# ---------------------------------------------------------------------------


def _uri(path: Path) -> str:
    return f"file://{path.resolve().as_posix()}"


def _frames() -> dict[str, dict[str, typing.Any]]:
    """Real aligned verification inputs: raw wrapper frame (NaN, zero/NaN playtime), main/coarse/baseline matrices."""
    frame = evaluation_frame()
    out: dict[str, dict[str, typing.Any]] = {}
    for role in ROLES:
        state = _fixture_state(f"performance_{role}")
        out[f"performance_{role}"] = {
            "frame": frame,
            "main": _ow.align_features(frame, state["feature_order"]),
            "coarse": _ow.align_features(frame, state["coarse_feature_order"]),
            "baseline": frame[["team_avg_mu", "opp_avg_mu", "mu_gap"]].fillna(0.0).to_numpy(),
        }
    standings = frame.assign(home_team_id=range(12), away_team_id=range(1, 13))
    out["standings"] = {
        "frame": standings,
        "matrix": _ow.feature_matrix(standings, _fixture_state("standings")["feature_order"]),
    }
    shift = frame.assign(current_div=np.arange(12) % 7 + 1, grid_n_div=20)
    for name in ("shift_default", "shift_tuned", "shift_old_missing"):
        out[name] = {"frame": shift}
    return out


@dataclasses.dataclass
class Workspace:
    root: Path
    model_root: Path
    inventory: dict[str, typing.Any]
    inventory_path: Path
    template_url: str


def _entry(workspace_root: Path, row: tuple, roles: dict[str, int], algorithms: dict[str, int], dimension: int) -> dict:
    artifact_id, name, kind, role, active, version = row
    old = workspace_root / "models" / f"{name}.joblib"
    data = old.read_bytes()
    frames = {}
    for frame_name, frame in _frames()[name].items():
        path = workspace_root / "models" / "frames" / f"{name}.{frame_name}.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(frame, path)
        raw = path.read_bytes()
        frames[frame_name] = {"storage_uri": _uri(path), "sha256": tool._sha(raw), "length": len(raw)}
    return {
        "id": artifact_id,
        "algorithm_id": algorithms[kind],
        "algorithm_name": ALGORITHM[kind],
        "model_kind": kind,
        "role_id": roles[role] if role else None,
        "dimension_id": dimension if role else None,
        "version": version,
        "feature_version": "2",
        "training_cutoff_tournament_id": None,
        "is_active": active,
        "metrics": {"mae": 0.25, "rows": artifact_id},
        "feature_importance": {"kd": 0.5},
        "discipline": "overwatch",
        "storage_uri": _uri(old),
        "sha256": tool._sha(data),
        "length": len(data),
        "expected_class": OLD_GLOBAL[kind],
        "frames": frames,
    }


@pytest.fixture(scope="module")
def workspace(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, stats_parity_template
) -> Workspace:
    # The persistent template is read-only: the registry rows below go into this module's own derived template.
    stack = contextlib.ExitStack()
    request.addfinalizer(stack.close)
    url = stack.enter_context(legacy_database(template_url=stats_parity_template[0]))
    root = tmp_path_factory.mktemp("conversion")
    (root / "models").mkdir()
    for _, name, *_ in ROWS:
        source = STATE / f"{name}.old.joblib"
        assert tool._sha(source.read_bytes()) == MANIFEST["files_sha256"][f"{name}.old.joblib"], name
        shutil.copyfile(source, root / "models" / f"{name}.joblib")
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT r.code, r.id, r.dimension_id FROM catalog.role r JOIN catalog.role_dimension d "
                    "ON d.id = r.dimension_id WHERE d.discipline = 'overwatch' AND d.rated "
                    "AND r.workspace_id IS NULL AND r.code IN ('tank','damage','support')"
                )
            ).all()
            roles = {code: role_id for code, role_id, _dimension in rows}
            (dimension,) = {d for *_x, d in rows}
            assert set(roles) == set(ROLES)
            algorithms = {}
            for kind, name in ALGORITHM.items():
                algorithms[kind] = conn.scalar(
                    sa.text(
                        "INSERT INTO analytics.algorithms(id, name, produces_shifts) VALUES "
                        "((SELECT COALESCE(MAX(id), 0) + 1 FROM analytics.algorithms), :n, :p) "
                        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                    ),
                    {"n": name, "p": kind == "shift"},
                )
    finally:
        engine.dispose()
    inventory = {
        "format": 1,
        "artifacts": [_entry(root, row, roles, algorithms, dimension) for row in ROWS],
    }
    path = root / "inventory.json"
    path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return Workspace(root, root / "models", inventory, path, url)


@pytest.fixture(scope="module")
def exported(workspace: Workspace, old_tree: Path) -> Path:
    """The state bundle, exported by the frozen pre-move source in its own process."""
    bundle = workspace.root / "bundle"
    done = run_old(
        old_tree,
        "export",
        "--inventory",
        str(workspace.inventory_path),
        "--model-root",
        str(workspace.model_root),
        "--output",
        str(bundle),
        "--old-image",
        OLD_IMAGE,
    )
    assert done.returncode == 0, done.stderr
    return bundle


@pytest.fixture(scope="module")
def staged(workspace: Workspace, exported: Path) -> tuple[Path, Path]:
    """Bundle + converted model root staged by the current code in its own process."""
    bundle = workspace.root / "staged_bundle"
    shutil.copytree(exported, bundle)
    new_root = workspace.root / "new_models"
    done = run_new("stage", "--bundle", str(bundle), "--output", str(new_root), "--new-image", NEW_IMAGE)
    assert done.returncode == 0, done.stderr
    return bundle, new_root


def _receipt(bundle: Path) -> dict[str, typing.Any]:
    return json.loads((bundle / "receipt.json").read_text(encoding="utf-8"))


def _copy_bundle(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def _stage_in_process(workspace: Workspace, exported: Path, tmp_path: Path) -> tuple[Path, Path]:
    bundle = _copy_bundle(exported, tmp_path / "bundle")
    new_root = tmp_path / "new"
    tool.stage(bundle, new_root, NEW_IMAGE)
    return bundle, new_root


# ---------------------------------------------------------------------------
# Export under the old code, stage under the new code, frozen receipts
# ---------------------------------------------------------------------------


def test_tool_has_stdlib_only_top_level_imports() -> None:
    """The same file is mounted into the retained old image: importing it loads no numerical or application code."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import convert_discipline_artifacts; "
        "heavy = [m for m in sys.modules if m.split('.')[0] in "
        "{'numpy','pandas','sklearn','scipy','lightgbm','xgboost','joblib','src','shared','sqlalchemy'}]; "
        "assert not heavy, heavy"
    )
    done = subprocess.run([sys.executable, "-c", code, str(TOOL.parent)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_supported_layouts_match_the_current_classes() -> None:
    for old_global, spec in tool.CLASSES.items():
        cls = tool._new_class(spec["new"])
        assert {f.name for f in dataclasses.fields(cls)} == {*spec["required"], *spec["optional"]}, old_global
        assert cls is getattr(ow_analytics, spec["new"].rsplit(".", 1)[1])
    assert tool._new_class(tool.NEW_CONSTANT) is ow_analytics._ConstantClassifier
    assert set(tool.CLASSES) == {OLD_GLOBAL[k] for k in OLD_GLOBAL}


def test_old_paths_do_not_load_in_the_new_runtime() -> None:
    """No alias: the legacy module paths cannot be imported and the frozen pickles refuse to load."""
    assert importlib.util.find_spec("src.services.ml.models.performance_v2") is None
    with pytest.raises(ModuleNotFoundError):
        joblib.load(STATE / "performance_tank.old.joblib")


def test_export_ran_in_the_old_code_and_preserves_every_registry_field(
    workspace: Workspace, exported: Path, old_tree: Path
) -> None:
    receipt = _receipt(exported)
    assert receipt["status"] == "exported" and receipt["old_image"] == OLD_IMAGE and receipt["new_image"] is None
    assert receipt["libraries"] == tool._libraries()
    assert receipt["inventory_sha256"] == tool._sha(workspace.inventory_path.read_bytes())
    assert [a["registry"]["id"] for a in receipt["artifacts"]] == [r[0] for r in ROWS]
    by_id = {e["id"]: e for e in workspace.inventory["artifacts"]}
    for artifact in receipt["artifacts"]:
        entry = by_id[artifact["registry"]["id"]]
        assert artifact["registry"] == {f: entry[f] for f in tool._REGISTRY_FIELDS}
        assert artifact["old"]["sha256"] == entry["sha256"] and artifact["new"] is None
        # The legacy classes were really imported from the frozen archive, not from the current tree.
        files = [Path(p).resolve() for p in artifact["old_modules"].values()]
        assert files and all(p.is_relative_to(old_tree.resolve()) for p in files), files
        # No application global anywhere in the bundle: the allowlist-only loader (library globals only) opens it.
        bundle = tool._load_plain((exported / "artifacts" / f"{entry['id']}.state.joblib").read_bytes(), "bundle")
        assert bundle["class"] == artifact["old"]["class"]
    # The state bundles use the explicit {"class", "state"} form, with the nested constant classifier explicit.
    damage = tool._load_plain((exported / "artifacts/9002.state.joblib").read_bytes(), "bundle")
    assert damage["class"] == OLD_GLOBAL["performance"]
    assert damage["state"]["baseline"] == {
        "class": tool.OLD_CONSTANT,
        "state": {"prior": damage["state"]["baseline"]["state"]["prior"]},
    }
    old_missing = tool._load_plain((exported / "artifacts/9007.state.joblib").read_bytes(), "bundle")
    assert "indiv_scale_top" not in old_missing["state"] and "clamp_top_grid_ref" not in old_missing["state"]
    assert set(old_missing["state"]) == {"w_team", "w_os", "shift_range", "feature_order"}


def test_stage_writes_immutable_new_paths_and_leaves_originals_untouched(
    workspace: Workspace, exported: Path, staged: tuple[Path, Path]
) -> None:
    bundle, new_root = staged
    receipt = _receipt(bundle)
    assert receipt["status"] == "staged" and receipt["new_image"] == NEW_IMAGE
    for artifact in receipt["artifacts"]:
        aid, old = artifact["registry"]["id"], artifact["old"]
        expected = new_root.resolve() / "discipline06" / str(aid) / f"{old['sha256']}.joblib"
        new = artifact["new"]
        assert new["uri"] == _uri(expected) and expected.is_file()
        assert new["sha256"] == tool._sha(expected.read_bytes()) and new["sha256"] != old["sha256"]
        assert all(new["comparisons"].values()) and set(new["comparisons"]) == set(artifact["outputs"])
        original = Path(old["storage_uri"].removeprefix("file://"))
        assert tool._sha(original.read_bytes()) == old["sha256"]  # byte-for-byte what was inventoried
    # Two registry rows over one shared old file get independent immutable staged files.
    assert (
        _receipt(bundle)["artifacts"][4]["old"]["storage_uri"] == _receipt(bundle)["artifacts"][7]["old"]["storage_uri"]
    )
    assert len({a["new"]["uri"] for a in receipt["artifacts"]}) == len(ROWS)


def _models_from_registry_uris(receipt: dict[str, typing.Any]) -> dict[str, typing.Any]:
    names = {row[0]: row[1] for row in ROWS}
    return {names[a["registry"]["id"]]: load_artifact(a["new"]["uri"]) for a in receipt["artifacts"]}


def test_staged_predictions_are_bit_identical_to_the_frozen_receipts(staged: tuple[Path, Path]) -> None:
    """The ordinary runtime loader opens every staged file; each frozen D96 prediction is reproduced exactly."""
    bundle, _ = staged
    models_by_name = _models_from_registry_uris(_receipt(bundle))
    assert "src.services.ml.models.performance_v2" not in sys.modules
    moved = {
        "performance_tank": ow_analytics.PerformanceModelV2,
        "performance_damage": ow_analytics.PerformanceModelV2,
        "performance_support": ow_analytics.PerformanceModelV2,
        "standings": ow_analytics.WinProbabilityModel,
        "shift_default": ow_analytics.ShiftModelV2,
        "shift_tuned": ow_analytics.ShiftModelV2,
        "shift_old_missing": ow_analytics.ShiftModelV2,
    }
    assert {n: type(m) for n, m in models_by_name.items()} == moved
    assert type(models_by_name["performance_damage"].baseline) is ow_analytics._ConstantClassifier
    assert not hasattr(models_by_name["shift_old_missing"], "__dict__") or "indiv_scale_top" not in vars(
        models_by_name["shift_old_missing"]
    )
    frame = evaluation_frame()
    with _fit_forbidden():
        actual = _to_json(
            {
                "fitted_performance": _fitted_performance(models_by_name, frame),
                "baselines": {
                    role: models_by_name[f"performance_{role}"]
                    .baseline.predict_proba(frame[["team_avg_mu", "opp_avg_mu", "mu_gap"]].fillna(0.0).to_numpy())
                    .tolist()
                    for role in ROLES
                },
                "standings_fitted": _standings_outputs(
                    models_by_name, frame.assign(home_team_id=range(12), away_team_id=range(1, 13))
                ),
                "shift": _shift_outputs(models_by_name, frame.assign(current_div=np.arange(12) % 7 + 1, grid_n_div=20)),
            }
        )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["synthetic"]
    _assert_equal(actual, {k: expected[k] for k in actual}, ("synthetic",))


def test_exports_are_idempotent_and_conflicts_never_overwrite(
    workspace: Workspace, exported: Path, old_tree: Path
) -> None:
    before = {p: p.read_bytes() for p in exported.rglob("*") if p.is_file()}
    args = (
        "--inventory",
        str(workspace.inventory_path),
        "--model-root",
        str(workspace.model_root),
        "--output",
        str(exported),
        "--old-image",
        OLD_IMAGE,
    )
    assert run_old(old_tree, "export", *args).returncode == 0
    assert {p: p.read_bytes() for p in exported.rglob("*") if p.is_file()} == before
    # A different old-image identity for the same output directory is a conflict, not a rewrite.
    conflict = run_old(old_tree, "export", *args[:-1], "some-other-image")
    assert conflict.returncode == 2 and "conflicting existing receipt" in conflict.stderr
    assert {p: p.read_bytes() for p in exported.rglob("*") if p.is_file()} == before


def test_stage_is_idempotent_and_reuses_verified_outputs(workspace: Workspace, exported: Path, tmp_path: Path) -> None:
    bundle, new_root = _stage_in_process(workspace, exported, tmp_path)
    receipt_bytes = (bundle / "receipt.json").read_bytes()
    files = sorted(new_root.rglob("*.joblib"))
    stamps = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in files}
    tool.stage(bundle, new_root, NEW_IMAGE)
    assert (bundle / "receipt.json").read_bytes() == receipt_bytes
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in files} == stamps
    with pytest.raises(tool.ConversionError, match="staged by image"):
        tool.stage(bundle, new_root, "another-image")
    with pytest.raises(tool.ConversionError, match="already staged at"):
        tool.stage(bundle, tmp_path / "elsewhere", NEW_IMAGE)


def test_failure_on_the_second_staged_artifact_leaves_a_retryable_state(
    workspace: Workspace, exported: Path, tmp_path: Path
) -> None:
    bundle = _copy_bundle(exported, tmp_path / "bundle")
    new_root = tmp_path / "new"
    good = (bundle / "artifacts/9002.state.joblib").read_bytes()
    (bundle / "artifacts/9002.state.joblib").write_bytes(good[: len(good) // 2])  # truncated bundle member
    with pytest.raises(tool.ConversionError, match="artifact 9002.*length/SHA256"):
        tool.stage(bundle, new_root, NEW_IMAGE)
    first = new_root.resolve() / "discipline06" / "9001"
    assert [p.name for p in first.iterdir()] == [f"{_receipt(bundle)['artifacts'][0]['old']['sha256']}.joblib"]
    assert not (new_root / "discipline06" / "9002").exists()
    failure = json.loads((bundle / "stage-failure.json").read_text(encoding="utf-8"))
    assert [Path(p).parent.name for p in failure["staged_files_existing"]] == ["9001"]
    assert _receipt(bundle)["status"] == "exported" and all(a["new"] is None for a in _receipt(bundle)["artifacts"])
    staged_file = next(first.iterdir())
    stamp = staged_file.stat().st_mtime_ns
    (bundle / "artifacts/9002.state.joblib").write_bytes(good)
    tool.stage(bundle, new_root, NEW_IMAGE)  # retry reuses the verified first output and completes the rest
    assert staged_file.stat().st_mtime_ns == stamp and not (bundle / "stage-failure.json").exists()
    assert _receipt(bundle)["status"] == "staged"


def test_stage_blocks_on_library_version_mismatch_and_conflicting_staged_output(
    workspace: Workspace, exported: Path, tmp_path: Path
) -> None:
    bundle = _copy_bundle(exported, tmp_path / "bundle")
    receipt = _receipt(bundle)
    receipt["libraries"]["lightgbm"] = "0.0.1"
    (bundle / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(tool.ConversionError, match="numerical dependency versions differ"):
        tool.stage(bundle, tmp_path / "new", NEW_IMAGE)
    assert not (tmp_path / "new").exists()
    receipt["libraries"]["lightgbm"] = tool._libraries()["lightgbm"]
    (bundle / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    old_sha = receipt["artifacts"][0]["old"]["sha256"]
    squatter = tmp_path / "new" / "discipline06" / "9001" / f"{old_sha}.joblib"
    squatter.parent.mkdir(parents=True)
    squatter.write_bytes(b"not a model")
    with pytest.raises(tool.ConversionError, match="artifact 9001"):
        tool.stage(bundle, tmp_path / "new", NEW_IMAGE)
    assert squatter.read_bytes() == b"not a model"  # a conflicting output is never overwritten or removed


def test_stage_refuses_to_run_where_the_old_modules_are_importable(
    workspace: Workspace, exported: Path, old_tree: Path
) -> None:
    done = run_old(
        old_tree, "stage", "--bundle", str(exported), "--output", str(workspace.root / "never"), "--new-image", "x"
    )
    assert done.returncode == 2 and "importable" in done.stderr
    assert not (workspace.root / "never").exists()


# ---------------------------------------------------------------------------
# Export fails closed
# ---------------------------------------------------------------------------


def _single(workspace: Workspace, tmp_path: Path, **changes: typing.Any) -> tuple[Path, Path]:
    entry = {**next(e for e in workspace.inventory["artifacts"] if e["id"] == 9005), **changes}
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"format": 1, "artifacts": [entry]}), encoding="utf-8")
    return inventory, tmp_path / "bundle"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"storage_uri": "s3://bucket/model.joblib"}, "unsupported storage scheme"),
        ({"storage_uri": "file://relative/model.joblib"}, "must be absolute"),
        ({"sha256": "0" * 64}, "differ from the inventory"),
        ({"length": 1}, "differ from the inventory"),
        ({"expected_class": "src.services.ml.models.performance_v2.PerformanceTrainingResult"}, "unsupported class"),
        (
            {"expected_class": "src.services.ml.models.shift_v2.ShiftModelV2", "model_kind": "performance"},
            "do not match",
        ),
        ({"discipline": "lol"}, "do not match"),
        ({"surprise": 1}, "inventory fields differ"),
        ({"frames": {"nonsense": {}}}, "unknown verification frame names"),
    ],
)
def test_export_fails_closed_before_any_legacy_import(
    workspace: Workspace, tmp_path: Path, changes: dict, message: str
) -> None:
    inventory, output = _single(workspace, tmp_path, **changes)
    with pytest.raises(tool.ConversionError, match=message):
        tool.export(inventory, workspace.model_root, output, OLD_IMAGE)
    assert not output.exists()


def test_export_blocks_missing_files_paths_outside_the_root_and_a_wrong_class(
    workspace: Workspace, tmp_path: Path
) -> None:
    missing = workspace.model_root / "gone.joblib"
    inventory, output = _single(workspace, tmp_path, storage_uri=_uri(missing))
    with pytest.raises(tool.ConversionError, match="file is missing"):
        tool.export(inventory, workspace.model_root, output, OLD_IMAGE)
    outside = tmp_path / "outside.joblib"
    shutil.copyfile(workspace.model_root / "shift_default.joblib", outside)
    entry = next(e for e in workspace.inventory["artifacts"] if e["id"] == 9005)
    inventory, output = _single(workspace, tmp_path, storage_uri=_uri(outside))
    with pytest.raises(tool.ConversionError, match="outside the approved model root"):
        tool.export(inventory, workspace.model_root, output, OLD_IMAGE)
    assert entry["sha256"] == tool._sha(outside.read_bytes())
    # Duplicate ids block the batch.
    both = tmp_path / "dup.json"
    both.write_text(json.dumps({"format": 1, "artifacts": [entry, entry]}), encoding="utf-8")
    with pytest.raises(tool.ConversionError, match="unique integer"):
        tool.export(both, workspace.model_root, tmp_path / "dup", OLD_IMAGE)
    stale = tmp_path / "format.json"
    stale.write_text(json.dumps({"format": 2, "artifacts": []}), encoding="utf-8")
    with pytest.raises(tool.ConversionError, match="unsupported format"):
        tool.export(stale, workspace.model_root, tmp_path / "format", OLD_IMAGE)


class _UnknownApplicationClass:
    """Stands in for a historical custom class the tool has no explicit conversion case for."""


def test_unknown_custom_global_blocks_with_artifact_id_and_global(workspace: Workspace, tmp_path: Path) -> None:
    path = workspace.model_root / "unknown.joblib"
    joblib.dump(_UnknownApplicationClass(), path)
    raw = path.read_bytes()
    entry = {
        **next(e for e in workspace.inventory["artifacts"] if e["id"] == 9005),
        "id": 9500,
        "storage_uri": _uri(path),
        "sha256": tool._sha(raw),
        "length": len(raw),
    }
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"format": 1, "artifacts": [entry]}), encoding="utf-8")
    with pytest.raises(
        tool.ConversionError, match=r"artifact 9500 .*non-allowlisted global: .*_UnknownApplicationClass"
    ):
        tool.export(inventory, workspace.model_root, tmp_path / "bundle", OLD_IMAGE)
    assert not (tmp_path / "bundle").exists()


def test_old_image_rejects_unexpected_state_and_unsupported_graph_members(
    workspace: Workspace, old_tree: Path, tmp_path: Path
) -> None:
    """Doctored historical pickles are built in the old image; each blocks the whole batch with its artifact id."""
    code = """
import sys, joblib
from src.services.ml.models.performance_v2 import PerformanceTrainingResult
src, out = sys.argv[1], sys.argv[2]
extra = joblib.load(src + '/performance_tank.joblib'); extra.surprise = 1
joblib.dump(extra, out + '/extra_attribute.joblib')
misplaced = joblib.load(src + '/performance_damage.joblib'); misplaced.booster_q10 = misplaced.baseline
joblib.dump(misplaced, out + '/misplaced_constant.joblib')
tank = joblib.load(src + '/performance_tank.joblib')
joblib.dump(PerformanceTrainingResult(role='tank', model=tank, metrics={}, feature_importance={}), out + '/training_result.joblib')
"""
    doctored = workspace.root / "doctored"  # inside the approved model root
    doctored.mkdir(exist_ok=True)
    run_old_code(old_tree, code, str(workspace.model_root), str(doctored))
    base = next(e for e in workspace.inventory["artifacts"] if e["id"] == 9001)
    cases = {
        "extra_attribute": "unsupported state layout.*surprise",
        "misplaced_constant": "state bundle: pickle references a non-allowlisted global: src.services.ml.models.performance_v2._ConstantClassifier",
        "training_result": "non-allowlisted global: src.services.ml.models.performance_v2.PerformanceTrainingResult",
    }
    for number, (name, message) in enumerate(cases.items()):
        raw = (doctored / f"{name}.joblib").read_bytes()
        if name == "misplaced_constant":
            frames = next(e for e in workspace.inventory["artifacts"] if e["id"] == 9002)["frames"]
        else:
            frames = base["frames"]
        entry = {
            **base,
            "id": 9600 + number,
            "storage_uri": _uri(doctored / f"{name}.joblib"),
            "sha256": tool._sha(raw),
            "length": len(raw),
            "frames": frames,
        }
        inventory = tmp_path / f"{name}.json"
        # Only the doctored file needs the model root to contain it.
        inventory.write_text(json.dumps({"format": 1, "artifacts": [entry]}), encoding="utf-8")
        done = run_old(
            old_tree, "export", "--inventory", str(inventory), "--model-root", str(workspace.root),
            "--output", str(tmp_path / f"out_{name}"), "--old-image", OLD_IMAGE,
        )  # fmt: skip
        assert done.returncode == 2, (name, done.stderr)
        assert f"artifact {9600 + number}" in done.stderr and re.search(message, done.stderr), done.stderr
        assert not (tmp_path / f"out_{name}").exists()
    # A real, supported artifact whose required verification frames are not all supplied blocks too.
    shift = next(e for e in workspace.inventory["artifacts"] if e["id"] == 9005)
    inventory = tmp_path / "no_frames.json"
    inventory.write_text(json.dumps({"format": 1, "artifacts": [{**shift, "frames": {}}]}), encoding="utf-8")
    done = run_old(
        old_tree, "export", "--inventory", str(inventory), "--model-root", str(workspace.root),
        "--output", str(tmp_path / "out_no_frames"), "--old-image", OLD_IMAGE,
    )  # fmt: skip
    assert done.returncode == 2 and "artifact 9005" in done.stderr and "differ from required" in done.stderr
    # A poisoned verification frame blocks too, after the (legitimate) artifact itself is read in the old image.
    poisoned = _object_array_pickle(str(tmp_path / "frame_executed"))
    frame_path = workspace.root / "doctored" / "poisoned_frame.joblib"
    frame_path.write_bytes(poisoned)
    ref = {"storage_uri": _uri(frame_path), "sha256": tool._sha(poisoned), "length": len(poisoned)}
    inventory = tmp_path / "poisoned_frame.json"
    inventory.write_text(
        json.dumps({"format": 1, "artifacts": [{**shift, "frames": {"frame": ref}}]}), encoding="utf-8"
    )
    done = run_old(
        old_tree, "export", "--inventory", str(inventory), "--model-root", str(workspace.root),
        "--output", str(tmp_path / "out_poisoned_frame"), "--old-image", OLD_IMAGE,
    )  # fmt: skip
    assert done.returncode == 2 and "frame 'frame'" in done.stderr and "non-allowlisted global" in done.stderr
    assert not (tmp_path / "frame_executed").exists() and not (tmp_path / "out_poisoned_frame").exists()


class _Mkdir:
    """Executable reduction: unpickling it creates ``path`` (a side effect the tests can observe)."""

    def __init__(self, path: str) -> None:
        self.path = path

    def __reduce__(self) -> tuple:
        return (os.mkdir, (self.path,))


def _dotted_traversal_pickle(path: str) -> bytes:
    """Protocol 4: STACK_GLOBAL('joblib.numpy_pickle', 'os.mkdir') applied to ``path`` by REDUCE."""

    def text(value: str) -> bytes:
        raw = value.encode()
        assert len(raw) < 256
        return b"\x8c" + bytes([len(raw)]) + raw

    return b"\x80\x04" + text("joblib.numpy_pickle") + text("os.mkdir") + b"\x93" + text(path) + b"\x85R."


def _object_array_pickle(path: str) -> bytes:
    buffer = io.BytesIO()
    joblib.dump({"state": np.array([_Mkdir(path)], dtype=object)}, buffer)  # nested pickle inside the ndarray payload
    return buffer.getvalue()


def test_the_poisoned_payloads_really_execute_under_an_unrestricted_loader(tmp_path: Path) -> None:
    """Calibration for the regressions below: both payloads create their marker when loaded the ordinary way."""
    import pickle

    dotted, nested = tmp_path / "dotted", tmp_path / "nested"
    pickle.loads(_dotted_traversal_pickle(str(dotted)))
    joblib.load(io.BytesIO(_object_array_pickle(str(nested))))
    assert dotted.is_dir() and nested.is_dir()


@pytest.mark.parametrize(
    "payload", [_dotted_traversal_pickle, _object_array_pickle], ids=["dotted-name", "object-array"]
)
def test_restricted_loader_rejects_before_any_reduce(tmp_path: Path, payload: typing.Callable[[str], bytes]) -> None:
    marker = tmp_path / "executed"
    data = payload(str(marker))
    with pytest.raises(tool.ConversionError, match="non-allowlisted global"):
        tool._load(data, ("src.services.ml.models.shift_v2.ShiftModelV2",))  # even with an allowed application global
    with pytest.raises(tool.ConversionError, match="frame 'frame': .*non-allowlisted global"):
        tool._load_plain(data, "frame 'frame'")
    assert not marker.exists()


def test_package_prefix_is_not_an_allowlist() -> None:
    for module, name in (
        ("numpy", "load"),
        ("pandas", "read_pickle"),
        ("sklearn.utils", "os.system"),
        ("joblib", "load"),
    ):
        with pytest.raises(tool.ConversionError, match="non-allowlisted global"):
            tool._load(
                b"\x80\x04" + b"".join(b"\x8c" + bytes([len(v)]) + v.encode() for v in (module, name)) + b"\x93.", ()
            )


def test_object_array_payload_is_restricted_for_artifacts_and_bundles(
    workspace: Workspace, exported: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "executed"
    poisoned = _object_array_pickle(str(marker))
    # Artifact surface (checked before any legacy import, so it runs under the new runtime).
    path = workspace.model_root / "object_array.joblib"
    path.write_bytes(poisoned)
    entry = {
        **next(e for e in workspace.inventory["artifacts"] if e["id"] == 9005),
        "id": 9501,
        "storage_uri": _uri(path),
        "sha256": tool._sha(poisoned),
        "length": len(poisoned),
    }
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"format": 1, "artifacts": [entry]}), encoding="utf-8")
    with pytest.raises(tool.ConversionError, match=r"artifact 9501 .*non-allowlisted global"):
        tool.export(inventory, workspace.model_root, tmp_path / "bundle", OLD_IMAGE)
    # State-bundle surface: a bundle whose SHA256 matches the receipt but carries the poisoned payload.
    bundle = _copy_bundle(exported, tmp_path / "poisoned_bundle")
    receipt = _receipt(bundle)
    receipt["artifacts"][0]["bundle"].update(sha256=tool._sha(poisoned), length=len(poisoned))
    (bundle / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (bundle / "artifacts/9001.state.joblib").write_bytes(poisoned)
    with pytest.raises(tool.ConversionError, match=r"artifact 9001 state bundle: .*non-allowlisted global"):
        tool.stage(bundle, tmp_path / "new", NEW_IMAGE)
    assert not marker.exists()


def test_export_preflights_the_whole_inventory_before_deserializing_anything(
    workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*_a: typing.Any, **_k: typing.Any) -> typing.NoReturn:
        raise AssertionError("an artifact was deserialized before the whole inventory was validated")

    monkeypatch.setattr(tool, "_load", never)
    monkeypatch.setattr(tool, "_load_plain", never)
    by_id = {e["id"]: e for e in workspace.inventory["artifacts"]}
    first, second = by_id[9005], by_id[9006]
    outside = tmp_path / "outside.joblib"
    shutil.copyfile(workspace.model_root / "shift_tuned.joblib", outside)
    cases = {
        "missing": ({"storage_uri": _uri(workspace.model_root / "gone.joblib")}, "file is missing"),
        "outside": ({"storage_uri": _uri(outside)}, "outside the approved model root"),
        "artifact_sha": ({"sha256": "0" * 64}, "differ from the inventory"),
        "frame_sha": (
            {"frames": {"frame": {**second["frames"]["frame"], "sha256": "0" * 64}}},
            r"frame 'frame'.*differ from the inventory",
        ),
        "frame_missing": (
            {"frames": {"frame": {**second["frames"]["frame"], "storage_uri": _uri(tmp_path / "nope.joblib")}}},
            r"frame 'frame'.*file is missing",
        ),
    }
    for name, (changes, message) in cases.items():
        inventory = tmp_path / f"{name}.json"
        inventory.write_text(json.dumps({"format": 1, "artifacts": [first, {**second, **changes}]}), encoding="utf-8")
        with pytest.raises(tool.ConversionError, match=message):
            tool.export(inventory, workspace.model_root, tmp_path / f"out_{name}", OLD_IMAGE)
        assert not (tmp_path / f"out_{name}").exists(), name


# ---------------------------------------------------------------------------
# Registry switch (real PostgreSQL)
# ---------------------------------------------------------------------------


def _insert_registry(url: str, inventory: dict[str, typing.Any]) -> None:
    engine = sa.create_engine(url)
    try:
        with Session(engine) as session:
            for e in inventory["artifacts"]:
                session.add(
                    models.MLModelArtifact(
                        **{
                            k: e[k]
                            for k in (
                                "id",
                                "algorithm_id",
                                "model_kind",
                                "dimension_id",
                                "role_id",
                                "version",
                                "feature_version",
                                "training_cutoff_tournament_id",
                                "metrics",
                                "feature_importance",
                                "is_active",
                                "storage_uri",
                            )
                        }
                    )
                )
            session.commit()
    finally:
        engine.dispose()


def _table(url: str) -> dict[int, dict[str, typing.Any]]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT * FROM analytics.ml_model_artifact ORDER BY id")).mappings().all()
            return {r["id"]: dict(r) for r in rows}
    finally:
        engine.dispose()


def _sql(url: str, statement: str, **params: typing.Any) -> None:
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(statement), params)
    finally:
        engine.dispose()


@pytest.fixture
def registry(workspace: Workspace) -> Iterator[str]:
    """A fresh clone of the workspace's derived template holding the inventory's rows, at their original URIs."""
    with legacy_database(template_url=workspace.template_url) as url:
        _insert_registry(url, workspace.inventory)
        yield url


def _uris(url: str) -> dict[int, str]:
    return {i: r["storage_uri"] for i, r in _table(url).items()}


def test_apply_switches_only_storage_uri_and_rollback_restores_the_original_set(
    workspace: Workspace, exported: Path, registry: str, tmp_path: Path
) -> None:
    bundle, new_root = _stage_in_process(workspace, exported, tmp_path)
    receipt_path = bundle / "receipt.json"
    old_files = {
        a["registry"]["id"]: Path(a["old"]["storage_uri"].removeprefix("file://"))
        for a in _receipt(bundle)["artifacts"]
    }
    old_stamps = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in set(old_files.values())}
    before = _table(registry)
    original = {i: r["storage_uri"] for i, r in before.items()}
    new = {a["registry"]["id"]: a["new"]["uri"] for a in _receipt(bundle)["artifacts"]}

    applied = tool.apply(receipt_path, registry)
    assert applied["status"] == "applied" and applied["applied"]["rows_changed"] == len(ROWS)
    after = _table(registry)
    assert {i: r["storage_uri"] for i, r in after.items()} == new
    for i in before:  # nothing but storage_uri changed: identity, version, role, metrics, active flag, no new row
        assert {k: v for k, v in after[i].items() if k != "storage_uri"} == {
            k: v for k, v in before[i].items() if k != "storage_uri"
        }
    assert set(after) == set(before)
    # The runtime's real read path now loads every row, active and historical, through the new classes.
    for row_id, row in after.items():
        loaded = load_artifact(row["storage_uri"])
        assert type(loaded).__module__.startswith("shared.disciplines.overwatch.analytics.models."), row_id

    again = tool.apply(receipt_path, registry)  # repeated apply: all rows already new -> idempotent success
    assert again["applied"]["rows_changed"] == 0 and _uris(registry) == new

    rolled = tool.rollback(receipt_path, registry)
    assert rolled["status"] == "rolled_back" and rolled["rolled_back"]["rows_changed"] == len(ROWS)
    assert _uris(registry) == original and _table(registry) == before
    assert tool.rollback(receipt_path, registry)["rolled_back"]["rows_changed"] == 0
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in old_stamps} == old_stamps  # originals never touched
    assert all(Path(u.removeprefix("file://")).is_file() for u in new.values())  # converted files left in place
    # After a rollback the old image's bytes cannot be read by the new runtime (no alias exists).
    with pytest.raises(ModuleNotFoundError):
        load_artifact(original[9001])
    assert tool.apply(receipt_path, registry)["status"] == "applied" and _uris(registry) == new


def test_apply_blocks_when_the_registry_changed_since_export(
    workspace: Workspace, exported: Path, registry: str, tmp_path: Path
) -> None:
    bundle, _ = _stage_in_process(workspace, exported, tmp_path)
    original = _uris(registry)
    for statement, field in (
        ("UPDATE analytics.ml_model_artifact SET is_active = NOT is_active WHERE id = 9004", "is_active"),
        ("UPDATE analytics.ml_model_artifact SET version = 'x' WHERE id = 9002", "version"),
        ("UPDATE analytics.ml_model_artifact SET metrics = '{\"mae\": 9}' WHERE id = 9001", "metrics"),
        ("UPDATE analytics.ml_model_artifact SET feature_version = '9' WHERE id = 9006", "feature_version"),
    ):
        before = _table(registry)
        _sql(registry, statement)
        changed = _table(registry)
        with pytest.raises(tool.ConversionError, match=rf"registry changed since export: \['{field}'\]"):
            tool.apply(bundle / "receipt.json", registry)
        assert _uris(registry) == original and _table(registry) == changed  # nothing was written
        for row_id, row in before.items():  # restore exactly the original rows
            _sql(
                registry,
                "UPDATE analytics.ml_model_artifact SET is_active=:a, version=:v, metrics=CAST(:m AS json), "
                "feature_version=:f WHERE id=:i",
                a=row["is_active"],
                v=row["version"],
                m=json.dumps(row["metrics"]),
                f=row["feature_version"],
                i=row_id,
            )
    _sql(registry, "DELETE FROM analytics.ml_model_artifact WHERE id = 9008")
    with pytest.raises(tool.ConversionError, match="registry rows missing: \\[9008\\]"):
        tool.apply(bundle / "receipt.json", registry)
    assert _receipt(bundle)["status"] == "staged"


def test_apply_blocks_on_mixed_state_and_rolls_the_whole_transaction_back_on_failure(
    workspace: Workspace, exported: Path, registry: str, tmp_path: Path
) -> None:
    bundle, _ = _stage_in_process(workspace, exported, tmp_path)
    original = _uris(registry)
    new = {a["registry"]["id"]: a["new"]["uri"] for a in _receipt(bundle)["artifacts"]}
    _sql(registry, "UPDATE analytics.ml_model_artifact SET storage_uri = :u WHERE id = 9003", u=new[9003])
    with pytest.raises(tool.ConversionError, match="mixed or unknown storage_uri state"):
        tool.apply(bundle / "receipt.json", registry)
    with pytest.raises(tool.ConversionError, match="mixed or unknown storage_uri state"):
        tool.rollback(bundle / "receipt.json", registry)
    _sql(registry, "UPDATE analytics.ml_model_artifact SET storage_uri = :u WHERE id = 9003", u=original[9003])
    _sql(registry, "UPDATE analytics.ml_model_artifact SET storage_uri = 's3://elsewhere/model' WHERE id = 9004")
    with pytest.raises(tool.ConversionError, match="mixed or unknown storage_uri state"):
        tool.apply(bundle / "receipt.json", registry)
    _sql(registry, "UPDATE analytics.ml_model_artifact SET storage_uri = :u WHERE id = 9004", u=original[9004])

    _sql(
        registry,
        "CREATE FUNCTION analytics.p6t6_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF NEW.id = 9005 THEN RAISE EXCEPTION 'injected failure'; END IF; RETURN NEW; END $$",
    )
    _sql(
        registry,
        "CREATE TRIGGER p6t6_fail BEFORE UPDATE ON analytics.ml_model_artifact "
        "FOR EACH ROW EXECUTE FUNCTION analytics.p6t6_fail()",
    )
    with pytest.raises(sa.exc.DBAPIError, match="injected failure"):
        tool.apply(bundle / "receipt.json", registry)  # rows 9001-9004 were updated first, then 9005 failed
    assert _uris(registry) == original  # no partial commit
    assert _receipt(bundle)["status"] == "staged"  # no applied receipt without a commit
    _sql(registry, "DROP TRIGGER p6t6_fail ON analytics.ml_model_artifact")
    assert tool.apply(bundle / "receipt.json", registry)["status"] == "applied"
    assert _uris(registry) == new


def test_apply_blocks_on_an_unconverted_registry_row_outside_the_receipt(
    workspace: Workspace, exported: Path, registry: str, tmp_path: Path
) -> None:
    bundle, _ = _stage_in_process(workspace, exported, tmp_path)
    original = _uris(registry)
    template = workspace.inventory["artifacts"][0]
    extra = {
        **template,
        "id": 9100,
        "version": "left-out",
        "is_active": False,
        "storage_uri": "file:///old/left-out.joblib",
    }
    _insert_registry(registry, {"artifacts": [extra]})
    with pytest.raises(tool.ConversionError, match=r"registry artifacts \[9100\] are outside the receipt"):
        tool.apply(bundle / "receipt.json", registry)
    assert {i: u for i, u in _uris(registry).items() if i != 9100} == original  # nothing was written
    assert _receipt(bundle)["status"] == "staged"
    _sql(registry, "DELETE FROM analytics.ml_model_artifact WHERE id = 9100")
    assert tool.apply(bundle / "receipt.json", registry)["status"] == "applied"


def test_apply_requires_a_complete_staged_and_verified_receipt(
    workspace: Workspace, exported: Path, registry: str, tmp_path: Path
) -> None:
    bundle, new_root = _stage_in_process(workspace, exported, tmp_path)
    original = _uris(registry)
    receipt = _receipt(bundle)
    unstaged = _copy_bundle(exported, tmp_path / "unstaged")
    with pytest.raises(tool.ConversionError, match="receipt status"):
        tool.apply(unstaged / "receipt.json", registry)
    staged_file = Path(receipt["artifacts"][3]["new"]["uri"].removeprefix("file://"))
    good = staged_file.read_bytes()
    staged_file.write_bytes(good[:-5])
    with pytest.raises(tool.ConversionError, match="artifact 9004 converted"):
        tool.apply(bundle / "receipt.json", registry)
    assert _uris(registry) == original
    staged_file.write_bytes(good)
    original_file = Path(receipt["artifacts"][0]["old"]["storage_uri"].removeprefix("file://"))
    renamed = original_file.with_suffix(".moved")
    original_file.rename(renamed)
    try:
        with pytest.raises(tool.ConversionError, match="artifact 9001 original: file is missing"):
            tool.apply(bundle / "receipt.json", registry)
        assert _uris(registry) == original
    finally:
        renamed.rename(original_file)
    assert tool.apply(bundle / "receipt.json", registry)["status"] == "applied"


def test_rollback_blocks_on_missing_originals_changed_rows_and_damaged_converted_files(
    workspace: Workspace, exported: Path, registry: str, tmp_path: Path
) -> None:
    bundle, _ = _stage_in_process(workspace, exported, tmp_path)
    receipt = _receipt(bundle)
    new = {a["registry"]["id"]: a["new"]["uri"] for a in receipt["artifacts"]}
    tool.apply(bundle / "receipt.json", registry)
    original_file = Path(receipt["artifacts"][2]["old"]["storage_uri"].removeprefix("file://"))
    renamed = original_file.with_suffix(".moved")
    original_file.rename(renamed)
    try:
        with pytest.raises(tool.ConversionError, match="artifact 9003 original: file is missing"):
            tool.rollback(bundle / "receipt.json", registry)
    finally:
        renamed.rename(original_file)
    _sql(registry, "UPDATE analytics.ml_model_artifact SET role_id = NULL, dimension_id = NULL WHERE id = 9001")
    with pytest.raises(tool.ConversionError, match=r"registry changed since export: \['dimension_id', 'role_id'\]"):
        tool.rollback(bundle / "receipt.json", registry)
    _sql(
        registry,
        "UPDATE analytics.ml_model_artifact SET role_id = :r, dimension_id = :d WHERE id = 9001",
        r=receipt["artifacts"][0]["registry"]["role_id"],
        d=receipt["artifacts"][0]["registry"]["dimension_id"],
    )
    converted = Path(new[9006].removeprefix("file://"))
    good = converted.read_bytes()
    converted.write_bytes(good + b"x")
    with pytest.raises(tool.ConversionError, match="artifact 9006 converted"):
        tool.rollback(bundle / "receipt.json", registry)
    converted.write_bytes(good)
    assert _uris(registry) == new
    assert tool.rollback(bundle / "receipt.json", registry)["status"] == "rolled_back"


def test_cli_reports_blocking_conditions_with_a_nonzero_exit(
    workspace: Workspace, exported: Path, tmp_path: Path, capsys
) -> None:
    bundle = _copy_bundle(exported, tmp_path / "bundle")
    code = tool.main(
        ["apply", "--receipt", str(bundle / "receipt.json"), "--database-url", "postgresql+psycopg://unused"]
    )
    assert code == 2 and "BLOCKED: receipt status is 'exported'" in capsys.readouterr().err

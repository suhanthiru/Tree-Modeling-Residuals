"""Twig-radius correction of TreeQSM models with rTwig, run through R.

TreeQSM fits a radius to every cylinder from the points around it. On thin branches there are
few points, mostly noise, and the fitted radii come out too large, so branch volume is
inflated. rTwig (Morales et al., R package) replaces those radii: it fixes the radius at
every branch tip to a measured twig radius for the species and fits a taper model along each
path from tip to stem, keeping fitted radii only where they agree with that model.

v1 found TreeQSM volume about 25 % above harvested volume, varying by species (about 2x for
larch). Experiment v1.1 asks whether rTwig-corrected cylinders are a better estimate and a
better residual feature.

Requirements: R with rTwig (tested with 1.4.0). Rscript is taken from the `rscript` argument,
the TREEWM_RSCRIPT environment variable or PATH; the R package library from `r_libs` or
R_LIBS_USER.

Outputs, under data/processed/rtwig/:
  qsm/<tree>.mat            the TreeQSM model alone (rTwig rejects files with extra variables)
  cylinders/<tree>.csv      corrected cylinders, plus <tree>.csv.meta.csv with the twig radius
  data/processed/features_belgian_rtwig.parquet   QSM features of the corrected models
"""
from __future__ import annotations

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from treewm.paths import PROCESSED
from treewm.qsm.cylinders import qsm_features

R_SCRIPT = Path(__file__).with_name("rtwig.R")
WORK = PROCESSED / "rtwig"

COLUMNS = {
    "start.x": "start_x", "start.y": "start_y", "start.z": "start_z",
    "axis.x": "axis_x", "axis.y": "axis_y", "axis.z": "axis_z",
    "end.x": "end_x", "end.y": "end_y", "end.z": "end_z",
    "UnmodRadius": "raw_radius", "OldRadius": "treeqsm_radius", "BranchOrder": "branch_order",
    "PositionInBranch": "branch_position", "modified": "rtwig_modified",
}


def find_rscript(rscript: str | None = None) -> str:
    for c in (rscript, os.environ.get("TREEWM_RSCRIPT"), shutil.which("Rscript")):
        if c and Path(c).exists():
            return str(c)
    raise FileNotFoundError("Rscript not found: pass --rscript or set TREEWM_RSCRIPT to Rscript(.exe)")


def native_id(tree_id: str) -> str:
    return tree_id.split(":", 1)[1]


def write_qsm_only(src: str | Path, dst: Path) -> Path:
    """Copy of a TreeQSM .mat holding only the `qsm` struct (the Belgian files also hold
    `optmodels` and `vresults`, which rTwig's importer rejects)."""
    if not dst.exists():
        sio.savemat(dst, {"qsm": sio.loadmat(str(src))["qsm"]}, do_compression=True)
    return dst


def read_cylinders(path: str | Path) -> pd.DataFrame:
    """rTwig cylinder CSV -> cylinder table with treewm column names (radius = corrected)."""
    d = pd.read_csv(path).rename(columns=COLUMNS)
    d.insert(0, "id", np.arange(1, len(d) + 1, dtype=np.int32))
    d["added"] = d["added"].astype(bool)
    return d


def _run_batch(rscript: str, jobs: pd.DataFrame, path: Path, env: dict, log) -> list[str]:
    jobs.to_csv(path, index=False)
    p = subprocess.run([rscript, str(R_SCRIPT), str(path)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("RTWIG")]
    for ln in lines:
        log("  " + ln[6:])
    if p.returncode != 0:
        log(f"  Rscript exited with {p.returncode}: {p.stderr.strip()[-500:]}")
    return lines


def _done(out: Path, species: str) -> bool:
    """A tree is done when its cylinders exist and were made unsmoothed for the same species."""
    meta = Path(f"{out}.meta.csv")
    if not (out.exists() and meta.exists()):
        return False
    m = pd.read_csv(meta)
    return {"species_latin", "smooth"} <= set(m.columns) and m.species_latin.iloc[0] == species and not bool(m.smooth.iloc[0])


def run_rtwig(trees: pd.DataFrame, workers: int = 8, rscript: str | None = None, r_libs: str | None = None,
              force: bool = False, log=print) -> pd.DataFrame:
    """Correct every tree's QSM (reusing finished trees unless `force`). Returns the twig-radius table."""
    rs = find_rscript(rscript)
    env = os.environ.copy()
    if r_libs:
        env["R_LIBS_USER"] = r_libs
    for sub in ("qsm", "cylinders", "batches"):
        (WORK / sub).mkdir(parents=True, exist_ok=True)
    rows = []
    for t in trees.itertuples():
        nid = native_id(t.tree_id)
        out = WORK / "cylinders" / f"{nid}.csv"
        if not force and _done(out, t.species_latin):
            continue
        mat = write_qsm_only(t.qsm_path, WORK / "qsm" / f"{nid}.mat")
        rows.append({"tree_id": t.tree_id, "species_latin": t.species_latin, "qsm_mat": mat.as_posix(),
                     "out_csv": out.as_posix(), "size": mat.stat().st_size})
    if rows:
        jobs = pd.DataFrame(rows).sort_values("size", ascending=False)  # big models first, spread over batches
        n = max(1, min(workers, len(jobs)))
        batches = [jobs.iloc[i::n].drop(columns="size") for i in range(n)]
        log(f"rtwig: correcting {len(jobs)} QSMs in {n} R processes")
        with ThreadPoolExecutor(n) as ex:
            list(ex.map(lambda ib: _run_batch(rs, ib[1], WORK / "batches" / f"batch{ib[0]}.csv", env, log),
                        enumerate(batches)))
    metas = [pd.read_csv(f"{WORK / 'cylinders' / native_id(t)}.csv.meta.csv") for t in trees.tree_id
             if Path(f"{WORK / 'cylinders' / native_id(t)}.csv.meta.csv").exists()]
    meta = pd.concat(metas, ignore_index=True) if metas else pd.DataFrame()
    missing = sorted(set(trees.tree_id) - set(meta.get("tree_id", [])))
    if missing:
        raise RuntimeError(f"rTwig failed for {len(missing)} trees: {missing[:5]}")
    return meta


def rtwig_features(tree_id: str, breast_height: float = 1.3) -> dict:
    """QSM features of the corrected model (prefix rtwig_) and of the uncorrected radii in the
    same table (prefix check_, compared with the TreeQSM features in `build`)."""
    cyl = read_cylinders(WORK / "cylinders" / f"{native_id(tree_id)}.csv")
    row = {"tree_id": tree_id}
    row.update({k.replace("qsm_", "rtwig_", 1): v for k, v in qsm_features(cyl, breast_height).items()})
    old = cyl.assign(radius=cyl["treeqsm_radius"])
    row.update({k.replace("qsm_", "check_", 1): v for k, v in qsm_features(old, breast_height).items()})
    v_new = np.pi * cyl["radius"] ** 2 * cyl["length"]
    # share of cylinders whose radius rTwig changed (its own `modified` column is a 0-1 score, not a flag)
    row["rtwig_modified_fraction"] = float((~np.isclose(cyl["radius"], cyl["treeqsm_radius"], rtol=1e-9, atol=0)).mean())
    row["rtwig_log_shrink"] = float(np.log(v_new.sum() / row["check_volume_total_m3"]))
    return row


def build(trees: pd.DataFrame, features: pd.DataFrame, workers: int = 8, rscript: str | None = None,
          r_libs: str | None = None, force: bool = False, log=print) -> pd.DataFrame:
    """Run rTwig on the trees, compute corrected QSM features and save features_belgian_rtwig.parquet.

    `features` is the TreeQSM feature table (features_belgian.parquet, indexed by tree_id); the
    features recomputed from rTwig's table with the uncorrected radii must match it, which checks
    that rTwig changed radii only (no smoothing, same cylinders, same order).
    """
    meta = run_rtwig(trees, workers, rscript, r_libs, force, log)
    df = pd.DataFrame([rtwig_features(t) for t in trees.tree_id]).merge(
            meta[["tree_id", "twig_radius_mm", "twig_source", "rtwig_version", "smooth"]], on="tree_id")
    check = [c for c in df if c.startswith("check_")]
    bad = []
    for c in check:
        a = df[c].to_numpy(float)
        b = features.loc[df.tree_id, c.replace("check_", "qsm_", 1)].to_numpy(float)
        if not np.allclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True):
            bad.append(c.replace("check_", "qsm_", 1))
    if bad:
        raise RuntimeError(f"rTwig's table with uncorrected radii does not reproduce the TreeQSM features: {bad}")
    log(f"rtwig: {len(df)} trees; all {len(check)} QSM features from the uncorrected radii match the TreeQSM features")
    keep = {"check_volume_total_m3", "check_volume_stem_m3"}
    df = df.drop(columns=[c for c in check if c not in keep])
    df.to_parquet(PROCESSED / "features_belgian_rtwig.parquet", index=False)
    return df

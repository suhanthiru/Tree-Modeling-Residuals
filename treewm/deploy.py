"""Train a deployable model bundle and run inference on a new single-tree scan.

The bundle is trained on all Belgian harvest trees in the scan-only scenario (DBH and height
from the point cloud), because that is what a new scan provides. For every target it holds
  * baseline:   DBH-only allometry (the most robust model across sites in the v1 evaluation)
  * correction: the residual model with the lowest leave-one-site-out error, chosen separately
                for cloud-only input (feature sets <= D) and cloud + QSM input (set E).
A correction is marked validated only if it beat the baseline out-of-sample.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from treewm.baselines import allometry as al
from treewm.data.ingest.ceda import CONIFER_GENERA
from treewm.eval.engine import fit_calibrated
from treewm.models.residual import TARGET
from treewm.paths import OUTPUTS, ROOT

BUNDLE = OUTPUTS / "model_bundle_v1.pkl"
BASELINE = "allometry A (DBH)"


def _choose(metrics: pd.DataFrame, target: str, allowed_sets: set[str]) -> tuple[str, dict]:
    m = metrics[(metrics.experiment == "belgian") & (metrics.target == target) & (metrics.scenario == "scan")
                & (metrics.scheme == "leave_one_site_out")]
    cand = m[m.model.str.startswith("residual") & m.feature_set.isin(allowed_sets)]
    best = cand.sort_values("relMAE_pct").iloc[0]
    base = m[m.model == BASELINE].iloc[0]
    return best.model, {"loso_relMAE_pct": float(best.relMAE_pct), "loso_coverage90": float(best.coverage90),
                        "baseline_loso_relMAE_pct": float(base.relMAE_pct),
                        "baseline_loso_coverage90": float(base.coverage90),
                        "validated": bool(best.relMAE_pct < base.relMAE_pct)}


def train(metrics_csv: Path = ROOT / "reports" / "v1" / "metrics.csv", log=print) -> Path:
    from treewm import experiments as ex
    from treewm.geometry.build import load_features
    cfg = ex.config()
    metrics = pd.read_csv(metrics_csv)
    W, T = ex._tables()
    F = load_features("belgian")
    base = al.belgian_frame(W, F, T, "scan")
    bundle = {"version": "v1", "targets": {}, "ranges": {}, "species_seen": sorted(base.species_latin.dropna().unique())}
    for lt, d in base.groupby("leaf_type"):
        bundle["ranges"][lt] = {"dbh_cm": [float(d.dbh_used_cm.min()), float(d.dbh_used_cm.max())],
                                "height_m": [float(d.h_used_m.min()), float(d.h_used_m.max())]}
    for target in cfg["belgian"]["targets"]:
        df = base[base[target].notna() & base.log_dbh.notna() & base.log_h.notna()].copy()
        df[TARGET] = np.log(df[target])
        zoo = ex.belgian_models(target, cfg["belgian"]["learners"], cfg["xgboost"])
        entry = {}
        for key, sets in [("cloud", {"B", "C", "D"}), ("cloud+qsm", {"B", "C", "D", "E"})]:
            name, info = _choose(metrics, target, sets)
            model, smear, q = fit_calibrated(zoo[name][0], df, "site_id", "leave_one_site_out", cfg["interval_level"])
            entry[key] = {"name": name, "model": model, "smear": smear, "q": q, **info}
        model, smear, q = fit_calibrated(zoo[BASELINE][0], df, "site_id", "leave_one_site_out", cfg["interval_level"])
        entry["baseline"] = {"name": BASELINE, "model": model, "smear": smear, "q": q}
        bundle["targets"][target] = entry
        log(f"{target}: baseline {BASELINE}; cloud -> {entry['cloud']['name']} (validated={entry['cloud']['validated']}); "
            f"cloud+qsm -> {entry['cloud+qsm']['name']} (validated={entry['cloud+qsm']['validated']})")
    BUNDLE.parent.mkdir(exist_ok=True)
    with open(BUNDLE, "wb") as f:
        pickle.dump(bundle, f)
    return BUNDLE


def _leaf_type(species: str | None, leaf_type: str | None) -> str:
    if leaf_type:
        return leaf_type
    if not species:
        raise ValueError("Give --species or --leaf-type")
    return "conifer" if species.split()[0] in CONIFER_GENERA else "broadleaf"


def predict(cloud: str, species: str | None = None, leaf_type: str | None = None, qsm: str | None = None,
            bundle_path: Path = BUNDLE) -> dict:
    from treewm.geometry.features import cloud_features
    from treewm.io.pointcloud import read_points
    with open(bundle_path, "rb") as f:
        bundle = pickle.load(f)
    lt = _leaf_type(species, leaf_type)
    feats = cloud_features(read_points(cloud))
    cyl = None
    if qsm:
        from treewm.io.treeqsm_mat import read_treeqsm
        from treewm.qsm.cylinders import qsm_features
        cyl, _ = read_treeqsm(qsm)
        feats.update(qsm_features(cyl, 1.3))
    row = pd.DataFrame([{**feats, "leaf_type": lt}])
    dbh = row["pc_dbh_cm"].fillna(row.get("qsm_dbh_cm", pd.Series([np.nan])))
    row = al.add_features(row, dbh, row["pc_height_m"])
    d, h = float(row.dbh_used_cm.iloc[0]), float(row.h_used_m.iloc[0])

    flags = []
    has_dbh = np.isfinite(d)
    rng = bundle["ranges"].get(lt)
    if not has_dbh:
        flags.append("no DBH: the lower stem was not observed" + (" and the QSM gave none" if qsm else "")
                     + "; volume and mass are not estimated")
    if has_dbh and rng and not (rng["dbh_cm"][0] <= d <= rng["dbh_cm"][1]):
        flags.append(f"DBH {d:.1f} cm outside training range {rng['dbh_cm']} for {lt}")
    if rng and not (rng["height_m"][0] <= h <= rng["height_m"][1]):
        flags.append(f"height {h:.1f} m outside training range {rng['height_m']} for {lt}")
    if species and species not in bundle["species_seen"]:
        flags.append(f"species {species} not in training data {bundle['species_seen']}")
    if feats.get("pc_stem_visibility", 1) < 0.5:
        flags.append("lower stem poorly visible; DBH and lean are unreliable")
    if feats.get("pc_crown_completeness", 1) < 0.6:
        flags.append("crown incompletely observed")
    if has_dbh and not np.isfinite(feats.get("pc_dbh_cm", np.nan)):
        flags.append("DBH slice fit failed; using QSM DBH")

    def run(e):
        lp = float(e["model"].predict_log(row)[0])
        return {"model": e["name"], "estimate": float(np.exp(lp) * e["smear"]),
                "interval90": [float(np.exp(lp - e["q"])), float(np.exp(lp + e["q"]))]}

    estimates = {}
    key = "cloud+qsm" if qsm else "cloud"
    for target, e in bundle["targets"].items():
        if not has_dbh:
            estimates[target] = None
            continue
        corr = e[key]
        estimates[target] = {
            "baseline": run(e["baseline"]),
            "corrected": {**run(corr), "validated_out_of_sample": corr["validated"],
                          "loso_relMAE_pct": corr["loso_relMAE_pct"],
                          "baseline_loso_relMAE_pct": corr["baseline_loso_relMAE_pct"]},
        }
        best = estimates[target]["corrected"] if corr["validated"] else estimates[target]["baseline"]
        estimates[target]["recommended"] = best["model"]

    geometry = {k: (None if not np.isfinite(v) else round(float(v), 4)) for k, v in feats.items()
                if isinstance(v, (int, float, np.floating, np.integer)) and k.startswith(("pc_", "qsm_"))}
    out = {"input": {"cloud": str(cloud), "qsm": qsm, "species": species, "leaf_type": lt},
           "summary": {"dbh_cm": round(d, 1) if has_dbh else None, "height_m": round(h, 2),
                       "stem_lean_deg": geometry.get("pc_lean_deg"), "lean_azimuth_deg": geometry.get("pc_lean_azimuth_deg"),
                       "crown_offset_m": geometry.get("pc_crown_offset_m"), "stem_volume_m3": geometry.get("pc_stem_volume_m3")},
           "estimates": estimates, "flags": flags, "geometry": geometry}
    if cyl is not None and has_dbh:
        # Mechanics seed for the dynamics work: scale QSM cylinder volumes to the recommended fresh mass.
        from treewm.qsm.cylinders import base_moments, cylinder_volume
        fm = estimates["fresh_mass_total_kg"]
        mass = fm["corrected"]["estimate"] if fm["recommended"] == fm["corrected"]["model"] else fm["baseline"]["estimate"]
        rho = mass / float(cylinder_volume(cyl).sum())
        mech = base_moments(cyl, rho)
        out["mechanics"] = {"effective_fresh_density_kg_m3": round(rho, 1),
                            **{k: round(v, 3) for k, v in mech.items()},
                            "note": "uniform density over QSM cylinders, rigid tree, pivot at stem base"}
    return out


def to_json(obj) -> str:
    return json.dumps(obj, indent=2)

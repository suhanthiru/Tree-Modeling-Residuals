"""Train a deployable model bundle and run inference on a new single-tree scan.

The bundle is trained on all Belgian harvest trees in the scan-only scenario (DBH and height
from the point cloud), because that is what a new scan provides. For every target it holds
  * baseline:     DBH-only allometry (the most robust model across sites in the v1 evaluation)
  * cloud:        the v1 residual model with the lowest leave-one-site-out error on cloud-only
                  input (feature sets <= D), for scans without a QSM
  * cloud+rtwig:  the v1.1 pick for scans with a TreeQSM model, whose radii `predict` corrects
                  with rTwig. The pick is rTwig volume x density learned per leaf type, unless
                  another model is better with 95 % confidence on held-out sites (paired
                  bootstrap over trees); targets without that model take the lowest error.
                  Candidates include the v1.1 models without QSM input (DBH formulas and
                  correction D over the DBH formula), so a target can ignore the QSM.
                  The reported errors are those of the selected models on the predictions
                  they were selected on, so they are slightly optimistic.
  * cloud+qsm:    the v1 pick on TreeQSM features, used when rTwig cannot run (no R, or no twig
                  radius for the species)
A model is marked validated only if it beat the baseline out-of-sample.
"""
from __future__ import annotations

import json
import pickle
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from treewm.baselines import allometry as al
from treewm.data.ingest.ceda import CONIFER_GENERA
from treewm.eval.engine import fit_calibrated
from treewm.eval.metrics import paired_bootstrap
from treewm.models.residual import TARGET
from treewm.paths import OUTPUTS, V1, V1_1

BUNDLE = OUTPUTS / "model_bundle_v1.1.pkl"
BASELINE = "allometry A (DBH)"
DENSITY_MODEL = "QSM x fold density"  # rTwig volume x density learned per leaf type
NOT_DEPLOYABLE = {"residual over published", "published", "oracle"}  # need values a new scan lacks
DENSITY_WARN = 0.15  # flag new species whose published wood density is this far from the training ones


def _loso_scan(m: pd.DataFrame, target: str) -> pd.DataFrame:
    return m[(m.target == target) & (m.scenario == "scan") & (m.scheme == "leave_one_site_out")]


def _choose(metrics: pd.DataFrame, target: str, allowed_sets: set[str]) -> tuple[str, dict]:
    m = _loso_scan(metrics[metrics.experiment == "belgian"], target)
    cand = m[m.model.str.startswith("residual") & m.feature_set.isin(allowed_sets)]
    best = cand.sort_values("relMAE_pct").iloc[0]
    base = m[m.model == BASELINE].iloc[0]
    return best.model, {"loso_relMAE_pct": float(best.relMAE_pct), "loso_coverage90": float(best.coverage90),
                        "baseline_loso_relMAE_pct": float(base.relMAE_pct),
                        "baseline_loso_coverage90": float(base.coverage90),
                        "validated": bool(best.relMAE_pct < base.relMAE_pct)}


def choose_rtwig(metrics: pd.DataFrame, preds: pd.DataFrame, target: str) -> tuple[str, str, dict]:
    """(model, QSM source, info) for scans whose QSM is corrected with rTwig (v1.1 results)."""
    m = _loso_scan(metrics[metrics.experiment == "belgian_rtwig"], target)
    base = m[m.model == BASELINE].iloc[0]
    cand = m[m.qsm_source.isin(["none", "rtwig", "both"]) & ~m.family.isin(NOT_DEPLOYABLE)]
    best = cand.sort_values("relMAE_pct").iloc[0]
    pick, rule = best, "lowest held-out-site error"
    dens = cand[(cand.model == DENSITY_MODEL) & (cand.qsm_source == "rtwig")]
    if len(dens) and not (best.model == DENSITY_MODEL and best.qsm_source == "rtwig"):
        p = _loso_scan(preds[preds.experiment == "belgian_rtwig"], target)
        a = p[(p.model == DENSITY_MODEL) & (p.qsm_source == "rtwig")].set_index("tree_id")
        b = p[(p.model == best.model) & (p.qsm_source == best.qsm_source)].set_index("tree_id")
        a, b = a.align(b, join="inner", axis=0)
        if len(a) != int(best.n) or not np.isfinite(np.r_[a.yhat, b.yhat, a.y]).all():
            raise ValueError(f"held-out predictions for {target} do not match the v1.1 metrics "
                             "(rerun `treewm evaluate-rtwig`)")
        test = paired_bootstrap(a.yhat, b.yhat, a.y)
        if test["hi"] < 0:  # the best model's error is lower with 95 % confidence
            rule = (f"lowest held-out-site error; better than rTwig volume x density by {-test['diff_pp']:.1f} "
                    f"points (95 % interval {-test['hi']:.1f} to {-test['lo']:.1f})")
        else:
            pick = dens.iloc[0]
            rule = (f"rTwig volume x density learned per leaf type: the lowest-error model ({best.model}, "
                    f"{best.qsm_source}) is not better with 95 % confidence (its error minus this one's: "
                    f"{test['diff_pp']:+.1f} points, interval {test['lo']:+.1f} to {test['hi']:+.1f})")
    elif len(dens):
        rule = "rTwig volume x density learned per leaf type: lowest held-out-site error"
    return pick.model, pick.qsm_source, {
        "loso_relMAE_pct": float(pick.relMAE_pct), "loso_coverage90": float(pick.coverage90),
        "baseline_loso_relMAE_pct": float(base.relMAE_pct), "baseline_loso_coverage90": float(base.coverage90),
        "validated": bool(pick.relMAE_pct < base.relMAE_pct), "selection": rule}


def _rows(base: pd.DataFrame, target: str) -> pd.DataFrame:
    df = base[base[target].notna() & base.log_dbh.notna() & base.log_h.notna()].copy()
    df[TARGET] = np.log(df[target])
    return df


def train(metrics_csv: Path = V1 / "metrics.csv", rtwig_metrics_csv: Path = V1_1 / "metrics.csv",
          rtwig_predictions: Path = OUTPUTS / "predictions_v1.1.parquet", log=print) -> Path:
    from treewm import experiments as ex
    from treewm.baselines.density import lookup
    from treewm.geometry.build import load_features
    cfg, rcfg = ex.config(), ex.rtwig_config()
    metrics, m11 = pd.read_csv(metrics_csv), pd.read_csv(rtwig_metrics_csv)
    if not Path(rtwig_predictions).exists():
        raise FileNotFoundError(f"{rtwig_predictions} not found: run `treewm evaluate-rtwig` first")
    p11 = pd.read_parquet(rtwig_predictions)
    W, T = ex._tables()
    F, R = load_features("belgian"), load_features("belgian_rtwig")
    ex.check_rtwig_features(R, rcfg)
    frames = {"none": al.belgian_frame(W, F, T, "scan")}
    for src in ("rtwig", "both"):
        frames[src] = al.belgian_frame(W, ex.with_qsm_source(F, R, src), T, "scan")
    base = frames["none"]
    species = sorted(base.species_latin.dropna().unique())
    bundle = {"version": "v1.1", "targets": {}, "ranges": {}, "species_seen": species,
              "rtwig": {k: rcfg["rtwig"][k] for k in ("package_version", "treeqsm_version", "smooth")},
              "density_reference": {}}
    for lt, d in base.groupby("leaf_type"):
        bundle["ranges"][lt] = {"dbh_cm": [float(d.dbh_used_cm.min()), float(d.dbh_used_cm.max())],
                                "height_m": [float(d.h_used_m.min()), float(d.h_used_m.max())]}
        bundle["density_reference"][lt] = {sp: lookup(sp)[0] for sp in sorted(d.species_latin.unique()) if lookup(sp)}
    level = cfg["interval_level"]
    for target in cfg["belgian"]["targets"]:
        df = _rows(base, target)
        zoo = ex.belgian_models(target, cfg["belgian"]["learners"], cfg["xgboost"])
        entry = {}
        for key, sets, src in [("cloud", {"B", "C", "D"}, "none"), ("cloud+qsm", {"B", "C", "D", "E"}, "treeqsm")]:
            name, info = _choose(metrics, target, sets)
            model, smear, q = fit_calibrated(zoo[name][0], df, "site_id", "leave_one_site_out", level)
            entry[key] = {"name": name, "qsm_source": src, "model": model, "smear": smear, "q": q, **info}
        name, src, info = choose_rtwig(m11, p11, target)
        make = ex.rtwig_models(target, src, cfg["xgboost"])[name][0]
        model, smear, q = fit_calibrated(make, _rows(frames[src], target), "site_id", "leave_one_site_out", level)
        entry["cloud+rtwig"] = {"name": name, "qsm_source": src, "model": model, "smear": smear, "q": q, **info}
        model, smear, q = fit_calibrated(zoo[BASELINE][0], df, "site_id", "leave_one_site_out", level)
        entry["baseline"] = {"name": BASELINE, "qsm_source": "none", "model": model, "smear": smear, "q": q}
        bundle["targets"][target] = entry
        log(f"{target}: cloud -> {entry['cloud']['name']}; cloud+rtwig -> {name} ({src}; {info['selection']}); "
            f"TreeQSM fallback -> {entry['cloud+qsm']['name']}")
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


def density_flag(species: str | None, lt: str, bundle: dict) -> str | None:
    """Warning for a species outside training whose published wood density is more than
    DENSITY_WARN from every training species of its leaf type (the density the models learned)."""
    from treewm.baselines.density import lookup
    if not species or species in bundle["species_seen"]:
        return None
    ref = bundle.get("density_reference", {}).get(lt)
    hit = lookup(species)
    if not ref:
        return None
    names = ", ".join(f"{k} {v:.0f}" for k, v in ref.items())
    if not hit:
        return f"no published wood density for {species}; cannot compare it with the training {lt} species ({names} kg/m3)"
    nearest = min(ref.values(), key=lambda v: abs(hit[0] / v - 1))
    dev = hit[0] / nearest - 1
    if abs(dev) <= DENSITY_WARN:
        return None
    return (f"published wood density of {species} ({hit[0]:.0f} kg/m3, table row {hit[1]}) is {100 * dev:+.0f} % "
            f"from the nearest training {lt} species ({names} kg/m3); dry biomass may be off by about that much, "
            "and fresh mass also depends on water content")


def predict(cloud: str, species: str | None = None, leaf_type: str | None = None, qsm: str | None = None,
            bundle_path: Path = BUNDLE, use_rtwig: bool = True, twig_radius_mm: float | None = None,
            rscript: str | None = None, r_libs: str | None = None) -> dict:
    from treewm import experiments as ex
    from treewm.geometry.features import cloud_features
    from treewm.io.pointcloud import read_points
    with open(bundle_path, "rb") as f:
        bundle = pickle.load(f)
    if bundle.get("version") != "v1.1":
        raise ValueError(f"{bundle_path} is a {bundle.get('version')} bundle; run `treewm train` to build the v1.1 one")
    if species:  # Latin binomial capitalisation, as in the training data and rTwig's table
        parts = species.split()
        species = " ".join([parts[0].capitalize(), *(w.lower() for w in parts[1:])])
    if twig_radius_mm is not None and not twig_radius_mm > 0:
        raise ValueError(f"twig radius must be positive, got {twig_radius_mm}")
    lt = _leaf_type(species, leaf_type)
    flags = []
    feats = cloud_features(read_points(cloud))
    cyl = rcyl = rt = rt_meta = None
    if twig_radius_mm is not None and not (qsm and use_rtwig):
        flags.append("--twig-radius-mm ignored: it is only used when rTwig corrects a QSM")
    if qsm:
        from treewm.io.treeqsm_mat import read_treeqsm
        from treewm.qsm.cylinders import qsm_features
        cyl, _ = read_treeqsm(qsm)
        feats.update(qsm_features(cyl, 1.3))
        dbh_known = any(np.isfinite(feats.get(k, np.nan)) for k in ("pc_dbh_cm", "qsm_dbh_cm"))
        if use_rtwig and dbh_known:  # without a DBH nothing is estimated, so skip the R run
            from treewm.qsm.rtwig import correct_one, cylinder_features
            try:
                with tempfile.TemporaryDirectory(prefix="treewm_rtwig_", ignore_cleanup_errors=True) as tmp:
                    rcyl, rt_meta = correct_one(qsm, species, Path(tmp), twig_radius_mm, rscript, r_libs)
                rt = cylinder_features(rcyl, 1.3)
                if not np.isclose(rt["check_volume_total_m3"], feats["qsm_volume_total_m3"], rtol=1e-6, atol=0):
                    raise RuntimeError("rTwig's cylinders do not match the TreeQSM model")
                if str(rt_meta["rtwig_version"]) != str(bundle["rtwig"]["package_version"]):
                    flags.append(f"rTwig {rt_meta['rtwig_version']} differs from the {bundle['rtwig']['package_version']} "
                                 "the models were trained with")
                if twig_radius_mm is not None:
                    flags.append(f"twig radius set by hand ({twig_radius_mm} mm); the models were trained with "
                                 "rTwig's table values for the species or genus")
            except Exception as e:  # any failure falls back to the TreeQSM models, with the reason
                why = str(e) if isinstance(e, (FileNotFoundError, RuntimeError)) else f"{type(e).__name__}: {e}"
                flags.append(f"rTwig not used ({why}); QSM estimates use the v1 TreeQSM models")
                rcyl = rt = rt_meta = None
        elif not use_rtwig:
            flags.append("rTwig switched off; QSM estimates use the v1 TreeQSM models")
    key = "cloud+rtwig" if rt is not None else ("cloud+qsm" if qsm else "cloud")

    rows = {}

    def row_for(source: str) -> pd.DataFrame:
        if source not in rows:
            f1 = pd.DataFrame([{**feats, "leaf_type": lt}])
            if source in ("rtwig", "both"):
                f1 = ex.with_qsm_source(f1, pd.DataFrame([rt]), source)
            dbh = f1["pc_dbh_cm"].fillna(f1.get("qsm_dbh_cm", pd.Series([np.nan])))
            r1 = al.add_features(f1, dbh, f1["pc_height_m"])
            num = r1.select_dtypes("number").columns  # as load_features does for the training table
            r1[num] = r1[num].replace([np.inf, -np.inf], np.nan)
            rows[source] = r1
        return rows[source]

    row = row_for("none")
    d, h = float(row.dbh_used_cm.iloc[0]), float(row.h_used_m.iloc[0])
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
    if (msg := density_flag(species, lt, bundle)):
        flags.append(msg)
    if feats.get("pc_stem_visibility", 1) < 0.5:
        flags.append("lower stem poorly visible; DBH and lean are unreliable")
    if feats.get("pc_crown_completeness", 1) < 0.6:
        flags.append("crown incompletely observed")
    if has_dbh and not np.isfinite(feats.get("pc_dbh_cm", np.nan)):
        flags.append("DBH slice fit failed; using QSM DBH")

    def run(e):
        lp = float(e["model"].predict_log(row_for(e["qsm_source"]))[0])
        return {"model": e["name"], "qsm_source": e["qsm_source"], "estimate": float(np.exp(lp) * e["smear"]),
                "interval90": [float(np.exp(lp - e["q"])), float(np.exp(lp + e["q"]))]}

    estimates = {}
    for target, e in bundle["targets"].items():
        if not has_dbh:
            estimates[target] = None
            continue
        corr = e[key]
        estimates[target] = {
            "baseline": run(e["baseline"]),
            "corrected": {**run(corr), "validated_out_of_sample": corr["validated"],
                          "loso_relMAE_pct": corr["loso_relMAE_pct"], "loso_coverage90": corr["loso_coverage90"],
                          "baseline_loso_relMAE_pct": corr["baseline_loso_relMAE_pct"],
                          **({"selection": corr["selection"]} if "selection" in corr else {})},
        }
        best = estimates[target]["corrected"] if corr["validated"] else estimates[target]["baseline"]
        estimates[target]["recommended"] = best["model"]

    num = (int, float, np.floating, np.integer)
    geometry = {k: (None if not np.isfinite(v) else round(float(v), 4)) for k, v in {**feats, **(rt or {})}.items()
                if isinstance(v, num) and k.startswith(("pc_", "qsm_", "rtwig_"))}
    out = {"input": {"cloud": str(cloud), "qsm": qsm, "species": species, "leaf_type": lt},
           "summary": {"dbh_cm": round(d, 1) if has_dbh else None, "height_m": round(h, 2),
                       "stem_lean_deg": geometry.get("pc_lean_deg"), "lean_azimuth_deg": geometry.get("pc_lean_azimuth_deg"),
                       "crown_offset_m": geometry.get("pc_crown_offset_m"), "stem_volume_m3": geometry.get("pc_stem_volume_m3"),
                       "qsm_used": None if not qsm else ("rTwig-corrected" if rt is not None else "TreeQSM")},
           "estimates": estimates, "flags": flags, "geometry": geometry}
    if rt is not None:
        out["rtwig"] = {"twig_radius_mm": float(rt_meta["twig_radius_mm"]), "twig_radius_source": rt_meta["twig_source"],
                        "rtwig_version": str(rt_meta["rtwig_version"]), "seconds": round(float(rt_meta["seconds"]), 1),
                        "treeqsm_volume_total_m3": round(float(feats["qsm_volume_total_m3"]), 4),
                        "rtwig_volume_total_m3": round(float(rt["rtwig_volume_total_m3"]), 4),
                        "cylinders_changed_fraction": round(float(rt["rtwig_modified_fraction"]), 3)}
    if cyl is not None and has_dbh:
        # Mechanics seed for the dynamics work: scale QSM cylinder volumes to the recommended fresh mass.
        from treewm.qsm.cylinders import base_moments, cylinder_volume
        c = rcyl if rcyl is not None else cyl
        fm = estimates["fresh_mass_total_kg"]
        mass = fm["corrected"]["estimate"] if fm["recommended"] == fm["corrected"]["model"] else fm["baseline"]["estimate"]
        rho = mass / float(cylinder_volume(c).sum())
        mech = base_moments(c, rho)
        out["mechanics"] = {"effective_fresh_density_kg_m3": round(rho, 1),
                            **{k: round(v, 3) for k, v in mech.items()},
                            "note": f"uniform density over the {'rTwig-corrected' if rcyl is not None else 'TreeQSM'} "
                                    "cylinders, rigid tree, pivot at stem base"}
    return out


def to_json(obj) -> str:
    return json.dumps(obj, indent=2)

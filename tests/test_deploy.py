"""Model choice for rTwig-corrected scans, the new-species density warning, single-tree QSM
features and the single-tree rTwig run (without R)."""
import numpy as np
import pandas as pd
import pytest

from treewm import deploy
from treewm import experiments as ex
from treewm.qsm import rtwig

KEYS = {"experiment": "belgian_rtwig", "scenario": "scan", "scheme": "leave_one_site_out"}


def _results(models: dict, target: str = "agb_dry_kg"):
    """models: (name, source, family) -> per-tree relative errors. Returns (metrics, predictions)."""
    mets, preds = [], []
    for (name, src, fam), err in models.items():
        err = np.asarray(err, float)
        mets.append({**KEYS, "target": target, "model": name, "qsm_source": src, "family": fam,
                     "relMAE_pct": 100 * np.mean(np.abs(err)), "coverage90": 0.9, "n": len(err)})
        preds.append(pd.DataFrame({**KEYS, "target": target, "model": name, "qsm_source": src,
                                   "tree_id": [f"t{i}" for i in range(len(err))], "y": 100.0, "yhat": 100 * (1 + err)}))
    return pd.DataFrame(mets), pd.concat(preds, ignore_index=True)


BASE = ("allometry A (DBH)", "none", "fitted allometry")
DENS = ("QSM x fold density", "rtwig", "geometry x density")
CORR = ("residual E over A / ridge", "rtwig", "residual over allometry A")


def test_density_model_kept_unless_another_is_clearly_better():
    n = 40
    noisy = {BASE: [0.3] * n, DENS: [0.20, -0.10] * (n // 2), CORR: [0.10, -0.19] * (n // 2)}
    name, src, info = deploy.choose_rtwig(*_results(noisy), "agb_dry_kg")
    assert (name, src) == ("QSM x fold density", "rtwig")  # CORR is lower (14.5 vs 15) but not clearly
    assert "not better with 95 % confidence" in info["selection"] and info["validated"]

    clear = {BASE: [0.3] * n, DENS: [0.2, -0.2] * (n // 2), CORR: [0.05, -0.05] * (n // 2)}
    name, src, info = deploy.choose_rtwig(*_results(clear), "agb_dry_kg")
    assert (name, src) == ("residual E over A / ridge", "rtwig")
    assert info["loso_relMAE_pct"] == pytest.approx(5.0) and info["baseline_loso_relMAE_pct"] == pytest.approx(30.0)


def test_mismatched_predictions_are_rejected():
    n = 40
    met, pred = _results({BASE: [0.3] * n, DENS: [0.2, -0.2] * (n // 2), CORR: [0.05, -0.05] * (n // 2)})
    with pytest.raises(ValueError, match="do not match"):
        deploy.choose_rtwig(met, pred[pred.tree_id != "t0"], "agb_dry_kg")


def test_lowest_error_without_density_model_and_no_published_inputs():
    m = {BASE: [0.3] * 10, CORR: [0.1] * 10,
         ("published allometry + residual E / ensemble", "rtwig", "residual over published"): [0.01] * 10,
         ("residual E / ensemble", "treeqsm", "residual over allometry B"): [0.02] * 10}
    name, src, info = deploy.choose_rtwig(*_results(m, "volume_stem_m3"), "volume_stem_m3")
    assert (name, src) == ("residual E over A / ridge", "rtwig")  # published and TreeQSM-only models are not candidates
    assert info["selection"] == "lowest held-out-site error"


def test_density_flag_for_new_species():
    b = {"species_seen": ["Fagus sylvatica", "Fraxinus excelsior"],
         "density_reference": {"broadleaf": {"Fagus sylvatica": 580.0, "Fraxinus excelsior": 570.0}}}
    assert deploy.density_flag("Fagus sylvatica", "broadleaf", b) is None  # trained on it
    assert deploy.density_flag("Betula pendula", "broadleaf", b) is None  # 510 vs 575: within 15 %
    msg = deploy.density_flag("Populus tremula", "broadleaf", b)
    assert msg and "350" in msg and "-39 %" in msg
    assert "no published wood density" in deploy.density_flag("Eucalyptus globulus", "broadleaf", b)
    assert deploy.density_flag(None, "broadleaf", b) is None


def test_single_tree_qsm_sources():
    f = pd.DataFrame([{c: 1.0 for c in ex.RTWIG_SWAP} | {"qsm_dbh_cm": 30.0}])
    r = pd.DataFrame([{c.replace("qsm_", "rtwig_", 1): 2.0 for c in ex.RTWIG_SWAP} | {"rtwig_log_shrink": -0.2}])
    swapped = ex.with_qsm_source(f, r, "rtwig")
    assert (swapped[ex.RTWIG_SWAP] == 2.0).all(axis=None) and swapped.qsm_dbh_cm.iloc[0] == 30.0
    both = ex.with_qsm_source(f, r, "both")
    assert (both[ex.RTWIG_SWAP] == 1.0).all(axis=None)
    assert both.log_rtwig_branch.iloc[0] == pytest.approx(np.log(2.0)) and both.rtwig_log_shrink.iloc[0] == -0.2
    assert ex.with_qsm_source(f, None, "none") is f


def test_correct_one_reports_r_errors_and_passes_twig_radius(tmp_path, monkeypatch):
    jobs = []

    def fake_batch(rs, job, path, env, log, timeout=None):
        jobs.append(job.iloc[0].to_dict())
        if len(jobs) == 3:  # R died before reporting on the tree
            return [], "Error in library(rTwig) : there is no package called 'rTwig'"
        return ["RTWIG error tree no twig radius in rTwig's table for Quercus rubra"], ""

    monkeypatch.setattr(rtwig, "find_rscript", lambda rs=None: "Rscript")
    monkeypatch.setattr(rtwig, "write_qsm_only", lambda src, dst, overwrite=False: dst)
    monkeypatch.setattr(rtwig, "_run_batch", fake_batch)
    with pytest.raises(RuntimeError, match="no twig radius in rTwig's table for Quercus rubra"):
        rtwig.correct_one("tree.mat", "Quercus rubra", tmp_path)
    assert "twig_radius_mm" not in jobs[-1]
    with pytest.raises(RuntimeError):
        rtwig.correct_one("tree.mat", None, tmp_path, twig_radius_mm=2.5)
    assert jobs[-1]["twig_radius_mm"] == 2.5 and jobs[-1]["species_latin"] == ""
    with pytest.raises(RuntimeError, match="R said: Error in library"):
        rtwig.correct_one("tree.mat", "Quercus rubra", tmp_path)

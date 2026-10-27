import numpy as np
import pandas as pd
import pytest

from treewm.data.schema import check_measurements, measurement_rows
from treewm.eval.engine import cross_validate, cross_validate_many
from treewm.eval.splits import kfold
from treewm.models.residual import TARGET, LogLinear, ResidualModel


def test_schema_rejects_wrong_unit_and_unknown_quantity():
    ok = pd.DataFrame(measurement_rows("t1", {"dbh_cm": 30.0}, {"dbh_cm": "measured"}, "src"))
    assert len(check_measurements(ok)) == 1
    bad_unit = ok.assign(unit="m")
    with pytest.raises(ValueError, match="unit"):
        check_measurements(bad_unit)
    bad_q = ok.assign(quantity="mass")
    with pytest.raises(ValueError, match="unregistered"):
        check_measurements(bad_q)
    with pytest.raises(ValueError, match="duplicate"):
        check_measurements(pd.concat([ok, ok]))


def _synthetic(n=400, seed=0):
    rng = np.random.default_rng(seed)
    d = rng.uniform(10, 60, n)
    z = rng.normal(size=n)  # an extra feature that explains part of the residual
    logy = np.log(0.1) + 2.4 * np.log(d) + 0.15 * z + rng.normal(0, 0.1, n)
    return pd.DataFrame({"log_dbh": np.log(d), "z": z, TARGET: logy, "g": np.arange(n) % 5})


def test_conformal_coverage_and_residual_gain():
    df = _synthetic()
    outer = kfold(len(df), 5)
    p0 = cross_validate(lambda: LogLinear(["log_dbh"]), df, outer, "g", "kfold")
    p1 = cross_validate(lambda: ResidualModel(LogLinear(["log_dbh"]), ["log_dbh", "z"], "ridge"), df, outer, "g", "kfold")
    cov = np.mean((p1.y >= p1.lo) & (p1.y <= p1.hi))
    assert 0.85 <= cov <= 0.95
    err0 = np.mean(np.abs(np.log(p0.yhat / p0.y)))
    err1 = np.mean(np.abs(np.log(p1.yhat / p1.y)))
    assert err1 < 0.8 * err0


def test_parallel_cross_validation_matches_serial():
    df = _synthetic(n=200)
    outer = kfold(len(df), 5)
    makes = [lambda: LogLinear(["log_dbh"]),
             lambda: ResidualModel(LogLinear(["log_dbh"]), ["log_dbh", "z"], "ensemble", members=["ridge", "xgb", "gp"])]
    jobs = [{"make": m, "df": df, "outer": outer, "group_col": "g", "scheme": "kfold"} for m in makes]
    for job, (p, seconds) in zip(jobs, cross_validate_many(jobs, n_jobs=2)):
        pd.testing.assert_frame_equal(p, cross_validate(**job))
        assert seconds > 0

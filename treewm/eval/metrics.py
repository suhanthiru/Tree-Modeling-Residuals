"""Error metrics on the original scale plus interval coverage."""
from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(y, yhat, lo=None, hi=None) -> dict:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    ok = np.isfinite(y) & np.isfinite(yhat) & (y > 0) & (yhat > 0)
    y, yhat = y[ok], yhat[ok]
    rel = (yhat - y) / y
    out = {
        "n": int(ok.sum()),
        "MAE": float(np.mean(np.abs(yhat - y))),
        "RMSE": float(np.sqrt(np.mean((yhat - y) ** 2))),
        "bias_pct": float(100 * np.mean(rel)),
        "relMAE_pct": float(100 * np.mean(np.abs(rel))),
        "total_bias_pct": float(100 * (yhat.sum() / y.sum() - 1)),
        "log_RMSE": float(np.sqrt(np.mean((np.log(yhat) - np.log(y)) ** 2))),
    }
    if lo is not None and hi is not None:
        lo, hi = np.asarray(lo, float)[ok], np.asarray(hi, float)[ok]
        out["coverage90"] = float(np.mean((y >= lo) & (y <= hi)))
        out["interval_width_pct"] = float(100 * np.median((hi - lo) / yhat))
    return out


def by_group(pred: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for g, d in pred.groupby(group_col):
        rows.append({group_col: g, **summarize(d["y"], d["yhat"], d["lo"], d["hi"])})
    return pd.DataFrame(rows)


def paired_bootstrap(a, b, y, n: int = 5000, seed: int = 0) -> dict:
    """Error of model b minus error of model a on the same trees: mean of |b/y - 1| - |a/y - 1|
    in percentage points, with a 95 % bootstrap interval over trees. Trees are resampled
    independently, which ignores that trees of one site share errors."""
    y = np.asarray(y, float)
    diff = 100 * (np.abs(np.asarray(b, float) / y - 1) - np.abs(np.asarray(a, float) / y - 1))
    rng = np.random.default_rng(seed)
    bs = diff[rng.integers(0, len(diff), (n, len(diff)))].mean(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"diff_pp": float(diff.mean()), "lo": float(lo), "hi": float(hi), "a_better": int((diff > 0).sum()),
            "n": len(diff)}

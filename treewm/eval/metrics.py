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

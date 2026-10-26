"""Build the canonical tables from the raw downloads."""
from __future__ import annotations

import pandas as pd

from treewm.data.schema import check_measurements, check_trees
from treewm.paths import LABELS, PROCESSED, RAW


def build(log=print) -> dict[str, int]:
    from treewm.data.ingest import belgian, biodiv, ceda

    trees, meas = [], []
    bt, bm = belgian.ingest()
    trees.append(bt); meas.append(bm)
    log(f"belgian: {len(bt)} trees, {bm.tree_id.nunique()} with measurements")
    if (RAW / "ceda" / "demol_et_al_AGB_with_TLS.xlsx").exists():
        ct, cm = ceda.ingest(set(bt.tree_id))
        trees.append(ct); meas.append(cm)
        log(f"ceda: {len(ct)} external trees, {cm.tree_id.nunique()} trees with measurements (incl. Belgian dry AGB)")
    if (RAW / "biodiv" / "labels.csv").exists():
        dt, dm = biodiv.ingest()
        trees.append(dt); meas.append(dm)
        log(f"biodiv: {len(dt)} trees, {dt.graph_path.notna().sum()} graphs, {dt.uls_path.notna().sum()} ULS clouds")

    T = check_trees(pd.concat(trees, ignore_index=True))
    M = check_measurements(pd.concat(meas, ignore_index=True))
    PROCESSED.mkdir(parents=True, exist_ok=True)
    LABELS.mkdir(parents=True, exist_ok=True)
    T.to_parquet(PROCESSED / "trees.parquet", index=False)
    M.to_parquet(LABELS / "measurements.parquet", index=False)

    cyl = belgian.load_cylinders(bt)
    cyl.to_parquet(PROCESSED / "qsm_cylinders_belgian.parquet", index=False)
    log(f"belgian cylinders: {len(cyl)} rows over {cyl.tree_id.nunique()} trees")
    return {"trees": len(T), "measurements": len(M), "cylinders": len(cyl)}

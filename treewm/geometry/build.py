"""Compute per-tree feature tables for every dataset with geometry."""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from treewm.paths import PROCESSED


def _belgian_one(args):
    tid, cloud_path, qsm_path = args
    from treewm.geometry.features import cloud_features
    from treewm.io.pointcloud import read_points
    from treewm.io.treeqsm_mat import read_treeqsm
    from treewm.qsm.cylinders import qsm_features
    row = {"tree_id": tid}
    try:
        row.update(cloud_features(read_points(cloud_path)))
    except Exception as e:  # keep going; record the failure
        row["pc_error"] = repr(e)
    cyl, td = read_treeqsm(qsm_path)
    row.update(qsm_features(cyl, breast_height=1.3))
    return row


def _biodiv_one(args):
    tid, uls_path, graph_path = args
    from treewm.geometry.features import cloud_features
    from treewm.io.pointcloud import read_points
    row = {"tree_id": tid}
    uls_path = uls_path if isinstance(uls_path, str) else None      # missing paths come back as NaN
    graph_path = graph_path if isinstance(graph_path, str) else None
    if uls_path:
        try:
            f = cloud_features(read_points(uls_path))
            row.update({k.replace("pc_", "uls_", 1): v for k, v in f.items()})
        except Exception as e:
            row["uls_error"] = repr(e)
    if graph_path:
        from treewm.qsm.cylinders import qsm_features
        from treewm.qsm.graph import graph_to_cylinders
        try:
            row.update({k.replace("qsm_", "graph_", 1): v for k, v in qsm_features(graph_to_cylinders(graph_path), 1.37).items()})
        except Exception as e:
            row["graph_error"] = repr(e)
    return row


def _run(fn, jobs, workers, log, label):
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(fn, jobs, chunksize=4), 1):
            rows.append(r)
            if i % max(1, len(jobs) // 10) == 0:
                log(f"  {label}: {i}/{len(jobs)}")
    return pd.DataFrame(rows)


def build_features(datasets=("belgian", "biodiv"), workers: int | None = None, log=print) -> dict:
    trees = pd.read_parquet(PROCESSED / "trees.parquet")
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    out = {}
    if "belgian" in datasets:
        b = trees[trees.dataset_id == "belgian"]
        jobs = list(zip(b.tree_id, b.cloud_path, b.qsm_path))
        df = _run(_belgian_one, jobs, workers, log, "belgian")
        df.to_parquet(PROCESSED / "features_belgian.parquet", index=False)
        out["belgian"] = len(df)
    if "biodiv" in datasets:
        d = trees[trees.dataset_id == "biodiv"]
        jobs = [(t, u, g) for t, u, g in zip(d.tree_id, d.uls_path, d.graph_path)]
        df = _run(_biodiv_one, jobs, workers, log, "biodiv")
        df.to_parquet(PROCESSED / "features_biodiv.parquet", index=False)
        out["biodiv"] = len(df)
    return out


def load_features(dataset: str) -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED / f"features_{dataset}.parquet")
    return df.set_index("tree_id").replace([np.inf, -np.inf], np.nan)

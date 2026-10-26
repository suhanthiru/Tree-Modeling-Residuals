"""BioDiv-3DTrees (Griese et al. 2025, GRO.data doi:10.25625/8PB1IF).

labels.csv gives species, TLS-derived DBH/height/crown projection area, ULS height and the QSM
volume (volQSM, m3) with validation flags. No field or harvest measurements are included, so
every quantity here is "reconstructed". Graphs (GraphML) are converted to cylinders on demand.
"""
from __future__ import annotations

import pandas as pd

from treewm.data.schema import check_measurements, check_trees, measurement_rows
from treewm.paths import RAW

SOURCE = "griese2025_biodiv"


def ingest() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = RAW / "biodiv"
    lab = pd.read_csv(base / "labels.csv")
    graph_dir = base / "Graphs" / "Graph"
    uls_dir = base / "ULS" / "ULS"
    trees, meas = [], []
    for _, r in lab.iterrows():
        tid = f"biodiv:{r.treeID}"
        sp = str(r.species).replace("_", " ")
        g = graph_dir / f"{r.treeID}_cor_graph.graphml"
        u = uls_dir / f"{r.treeID}_ULS.laz"
        trees.append({"tree_id": tid, "dataset_id": "biodiv", "native_id": r.treeID, "site_id": r.ep,
                      "study_id": "Griese2025", "species_latin": sp, "genus": sp.split()[0],
                      "leaf_type": "conifer" if r.type == "conifer" else "broadleaf", "sensor": "TLS+ULS",
                      "graph_path": str(g) if g.exists() else None, "uls_path": str(u) if u.exists() else None,
                      "split": r.split})
        vals = {"dbh_tls_cm": r.dTLS, "height_tls_m": r.hTLS, "height_uls_m": r.hULS,
                "crown_projection_area_tls_m2": r.cpaHTLS}
        if r.validQSM is True or str(r.validQSM) == "True":
            vals["qsm_volume_total_m3"] = r.volQSM
        meas += measurement_rows(tid, vals, {k: "reconstructed" for k in vals}, SOURCE)
    return check_trees(pd.DataFrame(trees)), check_measurements(pd.DataFrame(meas))

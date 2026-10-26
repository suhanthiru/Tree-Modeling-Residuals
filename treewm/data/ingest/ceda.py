"""Global co-incident TLS / harvested biomass compilation (Demol et al. 2025, CEDA).

391 trees from 10 studies. The 65 trees with Author == "Demol2021" are the Belgian harvest
trees (Tree_ID matches the Belgian tree_name exactly); their rows are attached to the Belgian
tree_ids instead of creating duplicates, so they can never leak into the external benchmark.
"""
from __future__ import annotations

import re

import pandas as pd

from treewm.data.schema import check_measurements, check_trees, measurement_rows
from treewm.paths import RAW

SOURCE = "demol2025_ceda"
CONIFER_GENERA = {"Pinus", "Picea", "Larix", "Pseudotsuga", "Abies", "Tsuga", "Cupressus", "Juniperus",
                  "Thuja", "Sequoia", "Taxus", "Cedrus", "Podocarpus", "Araucaria"}


def _clean_author(a: str) -> str:
    # The source file stores "Kükenbrink" with a broken encoding (U+FFFD); transliterate it.
    return re.sub(r"[^A-Za-z0-9]", "", str(a).replace("�", "u").replace("ü", "u"))


def ingest(belgian_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = pd.read_excel(RAW / "ceda" / "demol_et_al_AGB_with_TLS.xlsx", sheet_name="merged_dataset")
    if len(x) != 391:
        raise ValueError(f"CEDA: expected 391 rows, got {len(x)}")
    trees, meas = [], []
    for i, r in x.iterrows():
        author = _clean_author(r.Author)
        if pd.isna(r.Tree_ID):  # Momo2017 rows have no identifier; use the sheet row
            r = r.copy()
            r["Tree_ID"] = f"row{i:03d}"
        if author == "Demol2021":
            tid = f"belgian:{r.Tree_ID}"
            if tid not in belgian_ids:
                raise ValueError(f"CEDA Demol2021 tree {r.Tree_ID} has no Belgian match")
        else:
            tid = f"ceda:{author}:{r.Tree_ID}"
            species = str(r.Species).strip()
            genus = species.split()[0] if species and species != "nan" else None
            trees.append({"tree_id": tid, "dataset_id": "ceda", "native_id": str(r.Tree_ID), "site_id": author,
                          "study_id": author, "species_latin": species, "genus": genus,
                          "leaf_type": "conifer" if genus in CONIFER_GENERA else "broadleaf",
                          "foliage": r.Foliage, "sensor": f"TLS {r.TLS_instrument}"})
        vals = {"agb_dry_kg": r.AGB_total_tree_destr, "agb_allom_dry_kg": r.AGB_allom,
                "agb_qsm_dry_kg": r.AGB_total_tree_QSM, "dbh_qsm_cm": r.DBH_QSM,
                "height_tls_m": r.Tree_height_TLS}
        prov = {"agb_dry_kg": "measured", "agb_allom_dry_kg": "derived", "agb_qsm_dry_kg": "reconstructed",
                "dbh_qsm_cm": "reconstructed", "height_tls_m": "reconstructed"}
        if author != "Demol2021":  # Belgian field DBH / height already come from the harvest CSV
            vals.update({"dbh_cm": r.DBH_ref, "height_m": r.Tree_height_ref})
            prov.update({"dbh_cm": "measured", "height_m": "measured"})
        meas += measurement_rows(tid, vals, prov, SOURCE)
    return check_trees(pd.DataFrame(trees)), check_measurements(pd.DataFrame(meas))

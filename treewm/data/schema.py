"""Canonical tables and the quantity registry.

Three tables (Parquet, under data/processed/ and data/labels/):
  trees         one row per tree, identity and provenance
  measurements  long format: tree_id, quantity, value, unit, provenance, source
  qsm_cylinders cylinder table per tree (rTwig-style columns + tree_id)

Each quantity has exactly one definition and one unit. Different definitions (fresh vs dry,
stem vs total, harvested vs QSM) are different quantities, never the same name.
"""
from __future__ import annotations

import pandas as pd

PROVENANCE = {"measured", "reconstructed", "derived"}

# quantity -> (unit, definition)
QUANTITIES: dict[str, tuple[str, str]] = {
    "dbh_cm": ("cm", "Stem diameter at breast height from field measurement"),
    "dbh_tls_cm": ("cm", "Stem diameter at breast height fitted to the TLS point cloud"),
    "dbh_qsm_cm": ("cm", "Stem diameter at breast height from QSM cylinders"),
    "height_m": ("m", "Total tree height measured on the felled tree or in the field"),
    "height_tls_m": ("m", "Tree height from the TLS point cloud"),
    "height_uls_m": ("m", "Tree height from the UAV point cloud"),
    "crown_projection_area_tls_m2": ("m2", "Crown projection area from the TLS point cloud"),
    "fresh_mass_total_kg": ("kg", "Fresh above-ground mass of the whole tree, weighed after felling"),
    "fresh_mass_stem_kg": ("kg", "Fresh mass of the stem, weighed after felling"),
    "fresh_mass_crown_kg": ("kg", "Fresh mass of the crown (branches + foliage), weighed after felling"),
    "agb_dry_kg": ("kg", "Dry above-ground biomass from destructive harvest"),
    "agb_allom_dry_kg": ("kg", "Dry above-ground biomass from the allometric model reported by the data owner"),
    "agb_qsm_dry_kg": ("kg", "Dry above-ground biomass from QSM volume x basic density, reported by the data owner"),
    "volume_total_m3": ("m3", "Woody volume of the whole tree from harvested fresh mass / fresh density"),
    "volume_stem_m3": ("m3", "Stem volume from harvested stem fresh mass / stem fresh density"),
    "qsm_volume_total_m3": ("m3", "QSM volume of the whole tree (mean over optimal models when reported)"),
    "qsm_volume_sd_m3": ("m3", "Standard deviation of QSM volume over optimal models"),
    "qsm_volume_stem_m3": ("m3", "QSM volume of the stem"),
    "qsm_volume_coarse_m3": ("m3", "QSM volume of coarse cylinders as reported by the data owner"),
    "fresh_density_kg_m3": ("kg/m3", "Whole-tree fresh wood density (disc-based, corrected)"),
    "fresh_density_stem_kg_m3": ("kg/m3", "Stem fresh wood density (disc-based, corrected)"),
    "fresh_density_base_kg_m3": ("kg/m3", "Fresh density of the base disc"),
    "basic_density_kg_m3": ("kg/m3", "Basic wood density (dry mass / green volume) of the base disc"),
    "dry_matter_content": ("1", "Dry mass / fresh mass of the base disc"),
}

TREE_COLUMNS = [
    "tree_id", "dataset_id", "native_id", "site_id", "study_id", "species_latin", "genus",
    "leaf_type", "foliage", "sensor", "cloud_path", "qsm_path", "graph_path", "uls_path", "split",
]


def check_measurements(df: pd.DataFrame) -> pd.DataFrame:
    need = {"tree_id", "quantity", "value", "unit", "provenance", "source"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"measurements missing columns {missing}")
    bad_q = set(df["quantity"]) - set(QUANTITIES)
    if bad_q:
        raise ValueError(f"unregistered quantities {bad_q}")
    expected = df["quantity"].map(lambda q: QUANTITIES[q][0])
    wrong = df[expected != df["unit"]]
    if not wrong.empty:
        raise ValueError(f"unit mismatch, e.g. {wrong.iloc[0].to_dict()}")
    bad_p = set(df["provenance"]) - PROVENANCE
    if bad_p:
        raise ValueError(f"unknown provenance {bad_p}")
    dup = df.duplicated(["tree_id", "quantity", "source"])
    if dup.any():
        raise ValueError(f"duplicate measurements, e.g. {df[dup].iloc[0].to_dict()}")
    return df.dropna(subset=["value"]).reset_index(drop=True)


def measurement_rows(tree_id: str, values: dict, provenance: dict, source: str) -> list[dict]:
    rows = []
    for q, v in values.items():
        if v is None or pd.isna(v):
            continue
        rows.append({"tree_id": tree_id, "quantity": q, "value": float(v), "unit": QUANTITIES[q][0],
                     "provenance": provenance[q], "source": source})
    return rows


def check_trees(df: pd.DataFrame) -> pd.DataFrame:
    for c in TREE_COLUMNS:
        if c not in df.columns:
            df[c] = None
    if df["tree_id"].duplicated().any():
        raise ValueError("duplicate tree_id")
    return df[TREE_COLUMNS]


def wide(measurements: pd.DataFrame, prefer: list[str] | None = None) -> pd.DataFrame:
    """Pivot to one row per tree. If a quantity has several sources, keep the first in `prefer`."""
    m = measurements.copy()
    if prefer:
        rank = {s: i for i, s in enumerate(prefer)}
        m["_r"] = m["source"].map(lambda s: rank.get(s, len(rank)))
        m = m.sort_values("_r").drop_duplicates(["tree_id", "quantity"])
    return m.pivot_table(index="tree_id", columns="quantity", values="value", aggfunc="first")

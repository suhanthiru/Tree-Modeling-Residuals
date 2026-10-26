"""Belgian destructive harvest (Demol et al. 2021, Zenodo 4557401).

Units in the CSV are not documented; they are resolved and checked here:
  DBH cm, heights m, fresh masses kg, densities g/cm3 (x1000 -> kg/m3),
  harvested and QSM volumes in litres (/1000 -> m3), qsm_DBHqsm in m.
The check: Volume_total_tree_harvested == Fresh_mass_total_tree_harvested / FWD_corrected.
Dry AGB and the published allometric estimate for the same trees come from the CEDA
compilation (Author == Demol2021) and are attached in ingest/ceda.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from treewm.data.schema import check_measurements, check_trees, measurement_rows
from treewm.paths import RAW

SITE_SPECIES = {
    "PSYLA": ("Pinus sylvestris", "conifer"),
    "PSYLB": ("Pinus sylvestris", "conifer"),
    "LXDC": ("Larix decidua", "conifer"),
    "FEXC": ("Fraxinus excelsior", "broadleaf"),
    "FSYL": ("Fagus sylvatica", "broadleaf"),
}
SOURCE = "demol2021_zenodo4557401"


def file_stem(tree_name: str) -> str:
    site, num = tree_name.split("-")
    return f"{site}{int(num)}"


def check_units(df: pd.DataFrame) -> None:
    implied = df["Fresh_mass_total_tree_harvested"] / df["FWD_corrected"]
    rel = (implied / df["Volume_total_tree_harvested"] - 1).abs()
    if rel.max() > 0.01:
        raise ValueError(f"Belgian units: volume != mass/density (max rel err {rel.max():.3f})")
    if not (df["DBH"].between(5, 150).all() and df["qsm_DBHqsm"].between(0.05, 1.5).all()):
        raise ValueError("Belgian units: DBH not in cm / qsm_DBHqsm not in m")


def ingest() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = RAW / "belgian"
    df = pd.read_csv(base / "Destructive_and_qsm_data_DEMOL.csv")
    check_units(df)
    trees, meas = [], []
    qsm_dir = base / "optimal_QSMs"
    cloud_dir = base / "pointclouds_clean" / "pointclouds_clean"
    names = set(df["tree_name"].map(file_stem))
    # unlabelled scans (e.g. FEXC12) are kept as trees without measurements
    extra = sorted(p.stem for p in qsm_dir.glob("*.mat") if p.stem not in names)
    for _, r in df.iterrows():
        tid = f"belgian:{r.tree_name}"
        stem = file_stem(r.tree_name)
        sp, lt = SITE_SPECIES[r.site_name]
        trees.append({"tree_id": tid, "dataset_id": "belgian", "native_id": r.tree_name, "site_id": r.site_name,
                      "study_id": "Demol2021", "species_latin": sp, "genus": sp.split()[0], "leaf_type": lt,
                      "sensor": "TLS RIEGL VZ-1000/VZ-400",
                      "cloud_path": str(cloud_dir / f"{stem}.txt"), "qsm_path": str(qsm_dir / f"{stem}.mat")})
        vals = {
            "dbh_cm": r.DBH, "height_m": r.TH_felled, "height_tls_m": r.PC_treeheight,
            "dbh_qsm_cm": 100 * r.qsm_DBHqsm,
            "fresh_mass_total_kg": r.Fresh_mass_total_tree_harvested,
            "fresh_mass_stem_kg": r.Fresh_mass_stem_harvested,
            "fresh_mass_crown_kg": r.Fresh_mass_crown_harvested,
            "volume_total_m3": r.Volume_total_tree_harvested / 1000,
            "volume_stem_m3": r.Volume_stem_harvested / 1000,
            "qsm_volume_total_m3": r.qsm_mean_volume / 1000,
            "qsm_volume_sd_m3": r.qsm_sd_volume / 1000,
            "qsm_volume_stem_m3": r.qsm_stem_volumes / 1000,
            "qsm_volume_coarse_m3": r.qsm_coarse_volume / 1000,
            "fresh_density_kg_m3": 1000 * r.FWD_corrected,
            "fresh_density_stem_kg_m3": 1000 * r.FWD_stem_corrected,
            "fresh_density_base_kg_m3": 1000 * r.FD_base_disc,
            "basic_density_kg_m3": 1000 * r.WSG_base_disc,
            "dry_matter_content": r.DMC_base_disc,
        }
        prov = {k: "measured" for k in vals}
        prov.update({k: "reconstructed" for k in vals if k.startswith("qsm_") or k in ("dbh_qsm_cm", "height_tls_m")})
        prov.update({"volume_total_m3": "derived", "volume_stem_m3": "derived"})
        meas += measurement_rows(tid, vals, prov, SOURCE)
    for stem in extra:
        site = "".join(ch for ch in stem if ch.isalpha())
        num = int("".join(ch for ch in stem if ch.isdigit()))
        sp, lt = SITE_SPECIES[site]
        trees.append({"tree_id": f"belgian:{site}-{num:02d}", "dataset_id": "belgian", "native_id": f"{site}-{num:02d}",
                      "site_id": site, "study_id": "Demol2021", "species_latin": sp, "genus": sp.split()[0],
                      "leaf_type": lt, "sensor": "TLS RIEGL VZ-1000/VZ-400",
                      "cloud_path": str(cloud_dir / f"{stem}.txt"), "qsm_path": str(qsm_dir / f"{stem}.mat")})
    return check_trees(pd.DataFrame(trees)), check_measurements(pd.DataFrame(meas))


def load_cylinders(trees: pd.DataFrame) -> pd.DataFrame:
    from treewm.io.treeqsm_mat import read_treeqsm
    out = []
    for _, t in trees.iterrows():
        cyl, _ = read_treeqsm(t.qsm_path)
        cyl.insert(0, "tree_id", t.tree_id)
        out.append(cyl)
    return pd.concat(out, ignore_index=True)

"""Published basic wood density per species (configs/wood_density.yaml).

Lookup is by species, then by genus, the same rule rTwig's twig-radius table uses.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from treewm.paths import CONFIGS

TABLE = CONFIGS / "wood_density.yaml"


@lru_cache(maxsize=1)
def table() -> dict:
    return yaml.safe_load(TABLE.read_text())


def lookup(species: str | None) -> tuple[float, str] | None:
    """(kg/m3, matched row) for a Latin name, or None if neither species nor genus is listed."""
    if not species:
        return None
    rows = table()["kg_m3"]
    for key in (species, species.split()[0]):
        if key in rows:
            return float(rows[key]), key
    return None

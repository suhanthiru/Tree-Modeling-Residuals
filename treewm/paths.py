"""Project paths. Everything is relative to the repository root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
LABELS = DATA / "labels"
OUTPUTS = ROOT / "outputs"


def raw_dir(dataset_id: str) -> Path:
    p = RAW / dataset_id
    p.mkdir(parents=True, exist_ok=True)
    return p

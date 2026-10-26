"""Shared chart style for report figures.

Light chart surface, recessive hairline grid, and a validated palette: the first three
categorical slots (blue, orange, aqua) pass colour-vision-deficiency checks for all pairs,
and the blue ordinal ramp is used for ordered classes such as branch order.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CONTEXT = "#c3c2b7"  # de-emphasised marks

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
BLUE_LIGHT, BLUE_DARK = "#86b6ef", "#1c5cab"
LABEL_BOX = {"boxstyle": "square,pad=0.15", "facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85}
ORDINAL = ["#0d366b", "#1c5cab", "#3987e5", "#86b6ef"]  # dark = low order (stem), light = fine branches


def apply() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK2,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.7, "grid.linestyle": "-",
        "axes.axisbelow": True, "axes.titlelocation": "left", "axes.titlesize": 10,
        "axes.titleweight": "semibold", "axes.titlecolor": INK, "axes.titlepad": 8,
        "xtick.color": AXIS, "ytick.color": AXIS, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.labelsize": 8.5,
        "text.color": INK, "font.size": 9,
        "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
        "legend.frameon": False, "legend.fontsize": 8, "lines.linewidth": 1.5,
        "savefig.dpi": 150, "savefig.bbox": "tight",
    })


def titled(ax, title: str, sub: str | None = None) -> None:
    """Panel title, with an optional secondary line under it."""
    ax.set_title(title, pad=17 if sub else 8)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=7.5, color=INK2, va="bottom", ha="left")


def dots(ax, x, y, color=BLUE, size=26, **kw):
    """Filled markers with a surface-coloured ring so overlaps stay legible."""
    return ax.scatter(x, y, s=size, color=color, edgecolors=SURFACE, linewidths=1.0, zorder=3, **kw)

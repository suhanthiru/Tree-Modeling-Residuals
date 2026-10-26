# Tree Modeling Residuals

Tree World Model v1: estimate tree geometry, volume and biomass from LiDAR, and learn
corrections (residuals) to classical allometric equations. Evaluated against destructively
harvested trees with site-held-out splits.

Work in progress. Setup:

```bash
uv sync
uv run treewm download belgian ceda biodiv
```

Raw data goes to `data/raw/<dataset>/` and is not committed.

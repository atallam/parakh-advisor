# parakh-advisor

Portfolio advisory for a WealthLens portfolio. It keeps a versioned thesis per holding, derives an advice label (add / hold / trim / exit / review) from the thesis, valuation and your risk policy, and alerts only when something changes. **Advisory only; it never trades. Not investment advice.**

Plan of record: `Stock Analysis\FRAMEWORK\00_SYSTEM_DESIGN_V2.md`.

## Day 1: portfolio risk snapshot

```powershell
uv sync
uv run parakh-advisor snapshot --input data\inbox\holdings.json --out out\portfolio.html
uv run pytest
```

Put your WealthLens export in `data\inbox\` (git-ignored). Edit your risk policy in `config\policy.yaml`.

# Golden example G2 — single variation, explicit subset

## Input (user prompt)
> "Just the faithful version of 'art deco golden peacock', portrait only — 5x7, 8x10, 11x14."

## Expected agent behavior
- Recognizes an explicit single-variation request → draft only the **faithful** prompt (skip elevated +
  wildcard), still apply the no-text spine.
- Generate one candidate set via `generate.py --label faithful --aspect 4:5 --n 2`.
- User picks the keeper.
- Author one `piece.json` with `"orientation": "portrait"` and `"sizes": ["5x7","8x10","11x14"]` (the
  explicit subset, NOT "all").
- `python .../artwork.py finalize piece.json` then `index`.

## Output-property assertions
- **One** titled folder.
- `prints/` contains exactly **3** files: `5x7.jpg`, `8x10.jpg`, `11x14.jpg` (no 4x6, no landscape sizes).
- `master.png`, `seo.md`, `listing.json`, `prompt.txt`, `meta.json` all present; `meta.json.sizes == ["5x7","8x10","11x14"]`.
- `run.json.piece_count == 1`.

## Why this is a golden case
It proves the skill honors an **explicit size subset and a single-variation request** instead of always
fanning out to 3 variations + the full size set — the over-eager failure mode.

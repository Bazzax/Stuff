# Golden example G1 — happy path (concept → 3 variations → 2 keepers → 2 titled folders)

## Input (user prompt)
> "Run the artwork orchestrator on 'misty Pacific Northwest forest at dawn, muted greens'."

## Expected agent behavior

### Step 1 — three prompt variations (shown for selection; no-text spine on each)
1. **Faithful:** "Misty Pacific Northwest forest at dawn, tall evergreens fading into fog, muted greens,
   soft diffused light — wall art, gallery print, high detail, no text, no watermark, no signature, no border --ar 4:5"
2. **Elevated (preset: Moody coastal):** "Misty PNW forest at dawn, layered evergreen silhouettes, soft fog,
   low-contrast desaturated blue-greys, atmospheric depth, film grain, quiet — wall art, gallery print, high
   detail, no text, no watermark, no signature, no border --ar 4:5"
3. **Wildcard:** "Misty PNW forest reimagined as a vintage botanical lithograph, antique sage & sepia, precise
   engraved linework, aged parchment — wall art, gallery print, high detail, no text, no watermark --ar 4:5"

User says "all three."

### Step 2 — generate (local)
```
source ~/.config/ai-images/env
python tooling/ad-creatives/generate.py "<faithful prompt>"  --model nano-banana-pro --aspect 4:5 --n 2 --label faithful --out <run>/_candidates
python tooling/ad-creatives/generate.py "<elevated prompt>"  --model nano-banana-pro --aspect 4:5 --n 2 --label elevated --out <run>/_candidates
python tooling/ad-creatives/generate.py "<wildcard prompt>"  --model nano-banana-pro --aspect 4:5 --n 2 --label wildcard --out <run>/_candidates
```
No-text guard: one elevated render baked in a faint caption → re-roll elevated once.

### Step 3 — keepers
User keeps the best faithful render and the best elevated render (2 pieces).

### Step 4 — title + SEO per keeper (agent authors piece.json, user can rename)
`piece-1.json`:
```json
{
  "run_dir": "tooling/digital-product-research/artwork-runs/pnw-forest-dawn",
  "title": "Dawn Cathedral — Misty Forest Print",
  "source_image": "tooling/.../_candidates/faithful-nano-banana-pro-1.png",
  "orientation": "portrait",
  "sizes": "all",
  "model": "nano-banana-pro",
  "prompt": "<faithful prompt>",
  "upscale": 4,
  "seo": {
    "title": "Misty Forest Wall Art, PNW Pacific Northwest Print, Foggy Evergreen Trees, Moody Nature Decor",
    "tags": ["forest wall art","pnw print","foggy forest","evergreen print","moody nature","misty trees",
             "woodland decor","pacific northwest","nature printable","green wall art","tree art","cabin decor","calm wall art"],
    "description": "Misty Pacific Northwest forest at dawn... Instant-download printable in 9 sizes (4x6 to 11x14), 300 DPI. No physical item shipped."
  }
}
```

### Step 5 — finalize each
```
python .../artwork.py finalize piece-1.json
python .../artwork.py finalize piece-2.json
```

### Step 6 — index
```
python .../artwork.py index tooling/digital-product-research/artwork-runs/pnw-forest-dawn
```

## Output-property assertions (Verify checks these, not exact bytes)
- Exactly **2 titled folders** exist under the run dir, named from slugified titles.
- Each folder has `master.png`, `prints/` with the **4 portrait sizes** (4x6,5x7,8x10,11x14) as 300-DPI JPEGs,
  `seo.md`, `listing.json` (title ≤140 chars, ≤13 tags), `prompt.txt`, `meta.json`.
- Run dir has `index.md` (table of 2 pieces) and `run.json` (piece_count = 2, records the upscaler + prompts).
- No ListingView calls, no mockups, no Etsy-research step occurred.

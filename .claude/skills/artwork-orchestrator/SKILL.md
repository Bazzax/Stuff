---
name: artwork-orchestrator
version: 1.1.0
description: "Take an artwork concept you already have and run it end-to-end into list-ready print products: draft a few prompt variations, generate locally, upscale, crop to print sizes, title each piece, file it into its own titled folder, and write local listing SEO. Triggers on 'run the artwork orchestrator on …', 'turn this concept into print-ready listings', 'generate + upscale + crop + title + SEO this artwork', 'make a titled folder of prints from this idea', 'cohesive print collection from <concept>'. Prompt-first and fully local — no ListingView. Do NOT use to discover/research what to make (→ etsy-research, or full-listing for the research-first ListingView run), to only generate images (→ tee-design-forge for apparel, tooling/ad-creatives for ad creatives, midjourney-artwork for MidJourney web), or to only crop/mockup files you already have (→ crop-and-mockups)."
---

# Artwork Orchestrator

Turn one artwork **concept you already have** into organized, list-ready print products on disk — in a
single run. You (the agent) do the judgment work: craft prompt variations, pick winners, title each piece,
write the SEO copy. The bundled `scripts/artwork.py` does the deterministic chain that no other skill
covers: **upscale → crop to print sizes → assemble the titled folder → write SEO + run manifest.**

This is a **sibling of `full-listing`, not a replacement**: `full-listing` starts from Etsy *research* and
lives inside *ListingView*; this skill starts from a *prompt* and writes *local titled folders*. Generation
reuses the shared `tooling/ad-creatives/generate.py` provider layer (same as `tee-design-forge`).

## When to use

- "Run the artwork orchestrator on '<concept>'."
- "Turn this concept into print-ready listings / a titled folder of prints."
- "Generate + upscale + crop + title + SEO this artwork."
- "Make a cohesive print collection from '<concept>'."

**Do NOT use when** (route elsewhere):
- The user wants to **discover what to make** / research bestsellers first → `etsy-research`, or
  `full-listing` for the research-first, ListingView end-to-end run.
- The user only wants to **generate images** and stop → `tee-design-forge` (apparel), `tooling/ad-creatives`
  (ad creatives), or `midjourney-artwork` (MidJourney web).
- The user only wants to **crop / mockup files they already have** → `crop-and-mockups`.
- The user only wants a **JSON prompt** authored, no generation → `06-json-prompt-builder` / `sheetsmith-image-generator`.

The boundary in one line: **a concept/prompt is given AND the whole make-it-ready chain is wanted.** If
there's no concept yet, or only one stage is wanted, it's a different skill.

## Prerequisites

- API keys at `~/.config/ai-images/env` (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`) — `source` it.
- The ad-creatives venv: `tooling/ad-creatives/.venv` (has Pillow). Run `artwork.py` with that Python.
- The **Real-ESRGAN upscaler** (one-time). Run preflight first; it tells you exactly how to install if missing:
  ```
  tooling/ad-creatives/.venv/bin/python .claude/skills/artwork-orchestrator/scripts/artwork.py preflight
  ```
  The skill **never silently skips the upscale** — if the upscaler is absent, stop and install it (native
  4K alone won't reach 300 DPI at the largest print sizes).

## The pipeline

> Throughout, `RUN=tooling/digital-product-research/artwork-runs/<concept-slug>` (override with your own path).
> `PY=tooling/ad-creatives/.venv/bin/python` · `ART=.claude/skills/artwork-orchestrator/scripts/artwork.py`

### Step 0 — Preflight
`$PY $ART preflight` → confirm keys, generator, Pillow, upscaler. Resolve any `[!!]` before generating.

### Step 1 — Draft prompt variations
From the concept, write **three** full, print-oriented prompts (each ends with the no-text spine from
`references/art-direction-presets.md`):
1. **Faithful** — the concept rendered straight; the obvious strong version.
2. **Signature (house style)** — the concept rendered in the **default house style**, included in *every*
   run (see `references/art-direction-presets.md` → House styles; currently **Plein-air tonal oil**). Append
   that style's description + its anti-content guard, and pass its `--ref` images at generation (Step 2). The
   user may swap it for another preset on request, but by default every run carries the house style.
3. **Wildcard** — a deliberate reinterpretation (different style/era/treatment) to surface a surprise.

Show the three; let the user pick which to render (default: all three). If the user explicitly asks for one
("just the faithful version"), draft only that one — don't fan out.

### Step 2 — Generate (local)
For each selected variation:
```
source ~/.config/ai-images/env
$PY tooling/ad-creatives/generate.py "<prompt>" --model nano-banana-pro --aspect 4:5 --n 2 --label <variation> --out $RUN/_candidates
```
- Default model `nano-banana-pro` (Gemini 3 Pro, up to ~4K). Swap with `--model` (`gpt-image-2`,
  `nano-banana-2`, …) if the user asks.
- Aspect sets orientation downstream: portrait (`4:5`, `2:3`) → portrait crop set; landscape (`3:2`, `16:9`)
  → landscape crop set.
- **Signature variation:** pass the house style's `--ref` images so the brushwork/palette is grounded, e.g.
  `--ref .../style-refs/plein-air-tonal-oil/ref-farmhouse.png --ref .../style-refs/plein-air-tonal-oil/ref-mountains.png`
  (two refs that share only the style → replicate the look, not the content). Keep the anti-content guard in the prompt.
- **No-text guard:** review the renders. If a model baked in a caption / signature / frame / watermark — or
  rendered the piece as a **framed print on a wall** (mockup) — **re-roll that variation once.** Common for
  oil/minimalist styles; the spine guards against it.

### Step 3 — Review candidates in a browser grid → select keepers
As soon as generation finishes, open a visual contact sheet so the user can compare every candidate side by side:
```
$PY $ART grid $RUN/_candidates
```
This writes `_candidates/contact-sheet.html` and opens it in the default browser; each card is labelled with
a **pick-code** (`1a`, `2b`, …) the user selects by. First move any rejected renders (framed mockups,
baked-in text) into `_candidates/_discarded/` so they don't clutter the grid — only top-level PNGs are shown.
The user keeps the winners by code; each keeper becomes its own titled folder.

### Step 4 — Title + SEO per keeper
For each keeper, **propose a title** (evocative, SEO-aware product name) — the user can rename it (it drives
the folder name + SEO). Then author the listing SEO and write a `piece.json`:
```json
{
  "run_dir": "tooling/digital-product-research/artwork-runs/<concept-slug>",
  "title": "Dawn Cathedral — Misty Forest Print",
  "source_image": "<path to the chosen candidate png>",
  "orientation": "portrait",
  "sizes": "all",
  "model": "nano-banana-pro",
  "prompt": "<the exact prompt used>",
  "upscale": 4,
  "seo": {
    "title": "<Etsy listing title, ≤140 chars, front-loaded keywords>",
    "tags": ["<up to 13 tags, each ≤20 chars>"],
    "description": "<benefit-led; note sizes + 300 DPI + instant download + no physical item>"
  }
}
```
SEO rules: title ≤140 chars, ≤13 tags each ≤20 chars (Etsy limits), description benefit-led. `sizes` is
`"all"` or an explicit subset of the orientation's sizes.

### Step 5 — Finalize each keeper
```
$PY $ART finalize piece.json
```
Per piece this does: **upscale 4× → crop to each print size (300 DPI JPEG) → assemble the titled folder**:
```
<title-slug>/
  master.png        # upscaled master
  <short>-prints/   # one JPEG per size, 300 DPI — see rename note below
  seo.md            # human listing copy
  listing.json      # machine listing copy
  prompt.txt        # exact prompt + reproducibility
  meta.json
```
**Rename the prints folder to a unique, simple name per piece.** `finalize` always writes the folder as
`prints/`, so in a multi-piece run every piece ends up with an identically-named `prints/` — confusing once
they're downloaded/zipped together. After finalizing each keeper, rename its `prints/` to a short slug drawn
from the title, e.g. `meadow-prints/`, `country-lane-prints/`, `golden-hour-prints/`. Nothing in
`meta.json`/`listing.json`/`run.json` references the path, so a plain `mv` is safe.

### Step 6 — Index the run
```
$PY $ART index $RUN
```
Writes `index.md` (overview table + thumbnails of every piece) and `run.json` (reproducibility manifest:
concept, prompts, models, upscaler, crop set).

## Collection mode (matched set)
For a cohesive multi-listing collection, fix **one preset + one palette** across every concept (see the
preset file) and vary only the subject. Land all pieces under one `$RUN` so they read as a set, then `index`
once. Use this when the user asks for "a collection" / "a matching set" rather than one-offs.

## Print sizes (300 DPI)
- **Portrait:** 4×6, 5×7, 8×10, 11×14
- **Landscape:** 12×9, 20×16, 24×18, 36×24, A2 (23.39×16.54)

The upscaled master is large enough that every crop only **downscales** — quality never degrades on the way
down. Largest (24×36 @ 300 DPI = 7200×10800px) is why the real upscale matters.

## Integrity rules (non-negotiable)
- **Never silently skip the upscale.** Preflight stops cleanly if the upscaler is missing; install it, don't
  fall back to native res. (`--skip-upscale` exists for DEV/TEST only — never in a real run.)
- **No-text spine on every prompt**, and re-roll a variation once if text/watermark slips through.
- **Local only.** No ListingView, no Etsy API, no mockups. (Those are `create-listing` / `crop-and-mockups`
  and were deliberately left out — keep the boundary.)
- **Reuse `generate.py`** for generation; never reimplement the providers here.
- **One titled folder per kept piece**, with the fixed contents above. The title slug names the folder, and
  the print-crop subfolder gets a **unique simple name** per piece (rename `finalize`'s default `prints/` —
  see Step 5), never a generic `prints/` shared across pieces.
- **Respect explicit scope:** if the user names one variation or a size subset, honor it — don't over-fan-out.

## Output
A run folder under `tooling/digital-product-research/artwork-runs/<concept-slug>/` containing one titled
subfolder per piece (master + a uniquely-named print-crop folder + seo.md/listing.json + prompt.txt +
meta.json), plus `index.md` and `run.json`. Finish with a chat summary: per piece — title, folder path,
# crops, SEO title preview.

> Output folders can hold many large print files — keep `artwork-runs/` out of git (the install adds it to
> `.gitignore`).

## Anti-patterns
- **Researching instead of using the given concept.** This skill starts from the user's prompt; if they want
  discovery, it's `full-listing`/`etsy-research`.
- **Firing on a bare "generate an image."** That's `tee-design-forge`/`tooling/ad-creatives`. This skill is
  the *whole chain to print products*, not a one-shot generator.
- **Re-doing crops from a generated (un-upscaled) source.** Always crop from the upscaled master.
- **Generating mockups or pushing to ListingView.** Out of scope by design.
- **Always fanning out to 3 variations + all sizes** when the user asked for less.

## Golden examples
- `references/examples/G1-happy-path.md` — concept → 3 variations → 2 keepers → 2 titled folders.
- `references/examples/G2-single-portrait.md` — single variation, explicit size subset (honors scope).

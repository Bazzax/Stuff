# Changelog — artwork-orchestrator

## v1.0.0 — 2026-06-26
- Initial release. Prompt-first, fully-local pipeline: concept → 3 prompt variations
  (faithful / elevated / wildcard) → local generation via tooling/ad-creatives/generate.py
  → 4× Real-ESRGAN upscale → 300-DPI print crops → per-piece titling → titled folder
  → local listing SEO (seo.md + listing.json) → run index.md + run.json.
- Bundled scripts/artwork.py: preflight · finalize · index.
- references/art-direction-presets.md (elevated-variation presets + no-text spine + collection mode).
- Standalone sibling of full-listing (research-first/ListingView); boundary = a concept/prompt is
  supplied AND the whole make-it-ready chain is wanted.

## v1.0.1 — 2026-06-26
- Fix: landscape print sizes were stored portrait-shaped (9x12/16x20/18x24/24x36), which would crop a
  landscape image to portrait. Corrected to true landscape dimensions (12x9, 20x16, 24x18, 36x24; A2
  unchanged). Found on first real landscape run; Verify had only exercised the portrait path.
- Fix: upscale() now passes `-m <models dir next to the binary>`. Real-ESRGAN ncnn-vulkan defaults to
  `./models` relative to CWD, so running from the repo root failed with an empty error; the binary itself
  works fine (Metal/Vulkan on Apple Silicon).

## v1.0.2 — 2026-06-26
- Prompt fix: the no-text spine used "wall art, gallery print", which made image models render the piece as
  a framed print on a wall (a mockup) instead of full-bleed artwork — common for oil/minimalist styles.
  Replaced with explicit full-bleed / no-frame / no-mockup wording. Found on the Dolomites run.

## v1.0.3 — 2026-06-26
- Feature: `artwork.py grid <candidates_dir>` builds an HTML contact sheet of all candidates and opens it
  in the browser, each card labelled with a pick-code (1a, 2b, …). Wired into Step 3 (review candidates in a
  browser grid → select keepers). Rejected renders go in `_candidates/_discarded/` and are excluded.

## v1.1.0 — 2026-06-26
- Feature: **maintained house styles** with persisted reference images under references/style-refs/. The
  first is **plein-air-tonal-oil** (the somber French-countryside oil-sketch look), marked as the DEFAULT
  signature style.
- Behavior: variation 2 is now the **Signature (house style)** slot — every run renders one variation in the
  default house style, grounded on its --ref images, with an anti-content guard (replicate style, not the
  reference's content). Replaces the old generic "elevated" slot (still swappable to another preset on request).
- art-direction-presets.md gains a "House styles" section (reference-image styles) above the quick text presets.

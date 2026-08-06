# Artwork Orchestrator (Grok port)

A self-contained mechanical pipeline that takes images generated with **Grok Imagine** (or any other source) and turns them into list-ready print-product folders: optional upscale → 300 DPI crops for standard print sizes → titled folders with SEO, prompt, and metadata.

This is a port of the core `artwork.py` logic from the original Claude Code skill `artwork-orchestrator`, adapted so it has **no dependency** on the original `tooling/ad-creatives/generate.py` or Real-ESRGAN binary.

## Quick start

```bash
# After generating images with Grok Imagine and downloading them
python scripts/artwork_grok.py preflight

# Create a piece.json for each keeper (see example below)
python scripts/artwork_grok.py finalize piece.json

# After all pieces are finalized
python scripts/artwork_grok.py index /path/to/run_dir
```

## Upscale note (important)

This port uses **Pillow LANCZOS** for the optional 4× upscale. It is a high-quality *approximation* only.

For true print-ready quality at the larger sizes (especially 24×36 / 36×24 @ 300 DPI), you should still run a real Real-ESRGAN (or equivalent) upscaler on the source image first, then pass the high-resolution master to `finalize` with `--upscale-method none` (or set `"upscale": 1` and feed the already-upscaled file as `source_image`).

The original skill refuses to skip a proper upscale; this port makes the limitation explicit so you can choose.

## Print sizes (300 DPI)

- **Portrait**: 4×6, 5×7, 8×10, 11×14
- **Landscape**: 12×9, 20×16, 24×18, 36×24, A2 (23.39×16.54)

## Grok Imagine prompt templates

Use these with Grok Imagine (or the xAI Imagine API). Always append the **no-text / full-bleed spine**.

### No-text spine (append to every prompt)
```
— full-bleed artwork filling the entire image edge to edge, NOT a photo of a framed print, no picture frame, no mat, no border, no wall, no room, no mockup, high detail, no text, no watermark, no signature
```

### House style description (for Signature variation)
```
painted as a small late-19th-century plein-air oil sketch on panel — somber muted tonal palette of olive green, ochre, slate grey, umber and warm stone, soft grey overcast sky, heavy textured impasto and visible directional palette-knife strokes, low contrast, restrained and atmospheric, antique muted panel finish
```

### Anti-content note
Grok Imagine currently supports reference images in some modes (check current docs). If you can pass refs, use the two images from the original skill (`ref-farmhouse.png` + `ref-mountains.png`) and add:
```
replicate ONLY the brushwork, palette, muted tone and panel texture of the reference — do NOT include any farmhouse, buildings, cypress trees, or other content from the reference; render the requested subject only.
```
Otherwise the pure text description above is the best approximation.

### Example concept → three variations

**Concept**: misty Pacific Northwest forest at dawn, muted greens

1. **Faithful**  
   Misty Pacific Northwest forest at dawn, tall evergreens fading into soft fog, muted greens and soft diffused light — full-bleed artwork filling the entire image edge to edge, NOT a photo of a framed print, no picture frame, no mat, no border, no wall, no room, no mockup, high detail, no text, no watermark, no signature

2. **Signature (house style)**  
   Misty Pacific Northwest forest at dawn, tall evergreens fading into soft fog, muted greens, painted as a small late-19th-century plein-air oil sketch on panel — somber muted tonal palette of olive green, ochre, slate grey, umber and warm stone, soft grey overcast sky, heavy textured impasto and visible directional palette-knife strokes, low contrast, restrained and atmospheric, antique muted panel finish — full-bleed artwork filling the entire image edge to edge, NOT a photo of a framed print, no picture frame, no mat, no border, no wall, no room, no mockup, high detail, no text, no watermark, no signature

3. **Wildcard (e.g. Vintage botanical)**  
   Misty Pacific Northwest forest reimagined as a vintage botanical lithograph, antique sage & sepia, precise engraved linework, aged parchment — full-bleed artwork filling the entire image edge to edge, NOT a photo of a framed print, no picture frame, no mat, no border, no wall, no room, no mockup, high detail, no text, no watermark, no signature

Generate 1–2 images per variation at a portrait aspect (4:5 or 2:3) or landscape as desired. Download the keepers, then build `piece.json` files.

### Example piece.json
```json
{
  "run_dir": "artwork-runs/pnw-forest-dawn",
  "title": "Dawn Cathedral — Misty Forest Print",
  "source_image": "path/to/your-downloaded-keeper.png",
  "orientation": "portrait",
  "sizes": "all",
  "model": "grok-imagine",
  "prompt": "<the exact prompt you used>",
  "upscale": 4,
  "seo": {
    "title": "Misty Forest Wall Art, PNW Pacific Northwest Print, Foggy Evergreen Trees, Moody Nature Decor",
    "tags": ["forest wall art", "pnw print", "foggy forest", "evergreen print", "moody nature", "misty trees", "woodland decor", "pacific northwest", "nature printable", "green wall art", "tree art", "cabin decor", "calm wall art"],
    "description": "Misty Pacific Northwest forest at dawn. Instant-download printable in multiple sizes at 300 DPI. No physical item shipped."
  }
}
```

Then:
```bash
python scripts/artwork_grok.py finalize piece.json --upscale-method pillow
# or --upscale-method none if you already upscaled externally
```

After finalizing each piece, rename the generic `prints/` folder inside the titled folder to something unique (e.g. `meadow-prints/`) if you will zip multiple pieces together.

## Commands

- `preflight` – check Pillow
- `finalize <piece.json> [--upscale-method pillow|none]` – upscale (optional) → crop → assemble folder
- `index <run_dir>` – write `index.md` + `run.json`
- `grid <candidates_dir>` – simple HTML contact sheet (optional)

## License / relation to original

Derived from the original `artwork-orchestrator` skill in this repository. Mechanical logic preserved; generation step replaced by Grok Imagine + manual download.

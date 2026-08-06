# Art-direction presets

## House styles (maintained, with reference images) — one is the DEFAULT every run

These are *persisted* styles with their own reference images under `style-refs/<name>/`. Exactly one is the
**default signature**: the skill renders one variation (the **Signature** slot) in that style **every run**,
grounding it on the saved `--ref` images. Maintain them; don't let them drift.

| House style | Folder | Default? | Summary |
|---|---|---|---|
| **Plein-air tonal oil** | `style-refs/plein-air-tonal-oil/` | ✅ **DEFAULT** | Somber late-19thC plein-air oil sketch on panel — muted olive/ochre/slate/umber, grey overcast, heavy palette-knife impasto, low contrast. See its `style.md` for the exact description + the two `--ref` images + the anti-content guard. |

To add another, see the bottom of any `style-refs/<name>/style.md`. To change which is default, move the ✅.

---

## Quick text presets (no reference image)

The **"elevated / wildcard"** variations can pull one of these to lift a concept past the literal render.
Each preset is a compact art-direction layer (medium · palette · light · finish) you append to the
subject. Pick the one that fits the concept, or let the user name a style. These are starting points,
not a closed list.

| Preset | Art-direction layer to append |
|---|---|
| **Japandi** | matte minimalist, warm neutral palette (oatmeal, clay, soft black), negative space, natural light, fine grain, calm |
| **Vintage botanical** | antique lithograph / engraving style, aged parchment tones, precise linework, muted sage & sepia, subtle foxing |
| **Mid-century abstract** | bold geometric shapes, 1950s palette (mustard, teal, burnt orange, cream), flat matte color, clean hard edges |
| **Moody coastal** | soft fog, low-contrast desaturated blue-greys, atmospheric depth, film-grain, quiet horizon |
| **Scandinavian line** | single-weight continuous line art, off-white ground, charcoal line, airy, lots of breathing room |
| **Dark academia** | oil-painting richness, deep umbers and forest greens, chiaroscuro lighting, classical, aged varnish |
| **Desert modern** | warm terracotta & sand, high sun, long soft shadows, organic curves, sun-bleached matte finish |
| **Dreamy pastel** | soft gradients, blush/lavender/mint, gentle bloom, low contrast, ethereal |
| **Bold graphic** | high-contrast poster style, limited 3-color palette, strong silhouette, screen-print texture |
| **Fine-art watercolour** | loose wet-on-wet washes, organic bleed, paper texture, gentle pigment pooling, white margins |

## The no-text spine (always appended, every variation)
> `— full-bleed artwork filling the entire image edge to edge, NOT a photo of a framed print, no picture frame, no mat, no border, no wall, no room, no mockup, high detail, no text, no watermark, no signature`

Wall-art models frequently hallucinate captions, frames, signatures — or worse, render the piece as a
**framed print hanging on a wall** (a mockup) instead of the artwork itself. This is especially common for
art-print styles ("oil painting", "minimalist print", "gallery"). **Avoid the words `wall art` / `gallery
print` in the spine** — they invite the mockup. Use the full-bleed wording above instead, and if a render
still comes back framed or with baked-in text, re-roll that variation once (no-text guard, B3).

## Collection mode (C2)
When generating a **matched set**, fix ONE preset + ONE palette across every concept in the run so the
pieces read as a cohesive collection. Vary only the subject between pieces; keep medium, palette, light,
and finish identical.

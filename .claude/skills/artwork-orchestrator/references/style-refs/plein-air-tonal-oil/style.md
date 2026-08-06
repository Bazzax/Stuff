# House style: Plein-air tonal oil  (`plein-air-tonal-oil`)

**This is the default signature style — every run uses it for one of the variations (the Signature slot).**

## Style description (append after the subject)
> painted as a small late-19th-century plein-air oil sketch on panel — somber muted tonal palette of olive
> green, ochre, slate grey, umber and warm stone, soft grey overcast sky, heavy textured impasto and visible
> directional palette-knife strokes, low contrast, restrained and atmospheric, antique muted panel finish

## Reference images (pass BOTH as `--ref` to ground the brushwork)
- `ref-farmhouse.png` — the original French-countryside oil sketch (farmhouse subject)
- `ref-mountains.png` — a Dolomites sketch in the same style (mountain subject)

The two refs share **only the style**, not the subject — that's deliberate. Passing both tells the model to
replicate the *brushwork / palette / muted tone / panel texture*, not the content. **Always include the
anti-content guard** in the prompt: "replicate ONLY the brushwork, palette, muted tone and panel texture of
the reference — do NOT include any farmhouse, buildings, cypress trees, or other content from the reference;
render the requested subject only."

## How to use (Signature variation, every run)
```
$PY tooling/ad-creatives/generate.py --prompt-file <signature.txt> \
    --model nano-banana-pro --aspect <a:b> --n 2 --label signature \
    --ref .claude/skills/artwork-orchestrator/references/style-refs/plein-air-tonal-oil/ref-farmhouse.png \
    --ref .claude/skills/artwork-orchestrator/references/style-refs/plein-air-tonal-oil/ref-mountains.png \
    --out $RUN/_candidates
```
The signature prompt = `<subject>, ` + the style description above + the anti-content guard + the full-bleed
no-mockup spine.

## Provenance
Developed 2026-06-26 from the French-countryside run, then validated by replicating it onto the Dolomites.

---
## Adding more house styles
Create a sibling folder `references/style-refs/<style-name>/` with its own `style.md` + ref image(s), and add
a row to `art-direction-presets.md` → "House styles". Mark exactly one as the **default signature**.

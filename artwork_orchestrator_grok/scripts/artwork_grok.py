#!/usr/bin/env python3
"""
artwork_grok.py — mechanical pipeline for Grok Imagine (or any source images).

Port of the original artwork-orchestrator/scripts/artwork.py.

  preflight                 check Pillow
  finalize <piece.json>     optional upscale -> crop to print sizes -> titled folder
  index <run_dir>           build index.md + run.json
  grid <dir>                HTML contact sheet of candidates

Upscale uses Pillow LANCZOS by default (approximation). For production prints
prefer an external Real-ESRGAN pass and then --upscale-method none.
"""

import argparse
import json
import os
import re
import shutil
import sys
import traceback
import webbrowser
from datetime import datetime, timezone

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: Pillow not available. Install with: pip install Pillow")

DPI = 300
JPEG_QUALITY = 95

# Prefer Resampling enum (Pillow >=9); fall back for older
try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.LANCZOS

SIZES = {
    "portrait":  {"4x6": (4, 6), "5x7": (5, 7), "8x10": (8, 10), "11x14": (11, 14)},
    "landscape": {"12x9": (12, 9), "20x16": (20, 16), "24x18": (24, 18),
                  "36x24": (36, 24), "A2": (23.39, 16.54)},
}


def slugify(text: str) -> str:
    text = re.sub(r"[—–]", "-", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "untitled"


def center_crop_resize(img: "Image.Image", w_px: int, h_px: int) -> "Image.Image":
    src_w, src_h = img.size
    target_ratio = w_px / h_px
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = round(src_h * target_ratio)
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:
        new_h = round(src_w / target_ratio)
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return img.crop(box).resize((w_px, h_px), RESAMPLE)


def now_stamp(explicit=None) -> str:
    if explicit:
        return explicit
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pillow_upscale(src: str, dst: str, factor: int = 4) -> None:
    print("  [WARN] Using Pillow LANCZOS upscale — this is an APPROXIMATION only.")
    print("  For true 300 DPI quality at large print sizes, upscale with Real-ESRGAN")
    print("  externally and then use --upscale-method none.")
    with Image.open(src) as img:
        w, h = img.size
        up = img.resize((w * factor, h * factor), RESAMPLE)
        up.save(dst)
        print(f"  upscaled {w}x{h} -> {up.size[0]}x{up.size[1]}")


def _write_seo(piece_dir: str, title: str, seo: dict) -> None:
    tags = seo.get("tags", [])
    desc = seo.get("description", "")
    seo_title = seo.get("title", title)
    with open(os.path.join(piece_dir, "seo.md"), "w") as f:
        f.write(f"# {title}\n\n")
        f.write(f"**Listing title** (≤140 chars): {seo_title}\n\n")
        f.write("**Tags** (Etsy: 13 max, ≤20 chars each):\n")
        for t in tags:
            f.write(f"- {t}\n")
        f.write(f"\n**Description:**\n\n{desc}\n")
    with open(os.path.join(piece_dir, "listing.json"), "w") as f:
        json.dump({"title": seo_title, "tags": tags, "description": desc}, f, indent=2)


def cmd_preflight(_args) -> int:
    print("Artwork Grok Orchestrator — preflight\n")
    print(f"  [ok]  Pillow: {Image.__version__ if hasattr(Image, '__version__') else 'present'}")
    print("\npreflight: PASS")
    print("Note: Real-ESRGAN is not required here; Pillow LANCZOS is used as approximation.")
    return 0


def cmd_finalize(args) -> int:
    with open(args.piece) as f:
        piece = json.load(f)

    run_dir = piece["run_dir"]
    title = piece["title"]
    source = piece["source_image"]
    orientation = piece.get("orientation", "portrait")
    want = piece.get("sizes", "all")
    factor = int(piece.get("upscale", 4))

    if orientation not in SIZES:
        sys.exit(f"ERROR: orientation must be portrait|landscape, got {orientation!r}")
    if not os.path.exists(source):
        sys.exit(f"ERROR: source_image not found: {source}")

    size_set = SIZES[orientation]
    if want != "all":
        if isinstance(want, str):
            want = [want]
        missing = [s for s in want if s not in size_set]
        if missing:
            sys.exit(f"ERROR: sizes {missing} not valid for {orientation}. Valid: {list(size_set)}")
        size_set = {k: size_set[k] for k in want}

    piece_dir = os.path.join(run_dir, slugify(title))
    prints_dir = os.path.join(piece_dir, "prints")
    os.makedirs(prints_dir, exist_ok=True)

    master = os.path.join(piece_dir, "master.png")
    method = getattr(args, "upscale_method", "pillow")
    if method == "none" or getattr(args, "skip_upscale", False):
        print("  copying source as master (no upscale)")
        shutil.copyfile(source, master)
        actual_upscale = 0
    else:
        print(f"  upscaling {factor}x via Pillow LANCZOS -> {master}")
        pillow_upscale(source, master, factor)
        actual_upscale = factor

    with Image.open(master) as img:
        img = img.convert("RGB")
        for name, (win, hin) in size_set.items():
            w_px, h_px = round(win * DPI), round(hin * DPI)
            out = os.path.join(prints_dir, f"{name}.jpg")
            cropped = center_crop_resize(img, w_px, h_px)
            cropped.save(out, "JPEG", quality=JPEG_QUALITY, dpi=(DPI, DPI))
            print(f"    {name}: {w_px}x{h_px}px -> {out}")

    _write_seo(piece_dir, title, piece.get("seo", {}))
    with open(os.path.join(piece_dir, "prompt.txt"), "w") as f:
        f.write(piece.get("prompt", "") + "\n")
    meta = {
        "title": title,
        "slug": slugify(title),
        "orientation": orientation,
        "sizes": list(size_set),
        "model": piece.get("model", ""),
        "upscale": actual_upscale,
        "prompt": piece.get("prompt", ""),
        "seo": piece.get("seo", {}),
        "finalized_at": now_stamp(getattr(args, "stamp", None)),
        "upscale_method": method,
    }
    with open(os.path.join(piece_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nfinalized: {piece_dir}")
    print("Remember to rename the 'prints/' subfolder to a unique name if packaging multiple pieces.")
    return 0


def cmd_index(args) -> int:
    run_dir = args.run_dir
    if not os.path.isdir(run_dir):
        sys.exit(f"ERROR: run_dir not found: {run_dir}")
    pieces = []
    for name in sorted(os.listdir(run_dir)):
        mpath = os.path.join(run_dir, name, "meta.json")
        if os.path.exists(mpath):
            with open(mpath) as f:
                pieces.append(json.load(f))

    lines = [f"# Artwork run — {os.path.basename(run_dir.rstrip('/'))}", ""]
    lines.append(f"{len(pieces)} piece(s).\n")
    lines.append("| Title | Folder | Orientation | Sizes | SEO title |")
    lines.append("|---|---|---|---|---|")
    for p in pieces:
        seo_t = p.get("seo", {}).get("title", p["title"])
        lines.append(f"| {p['title']} | `{p['slug']}/` | {p['orientation']} | "
                     f"{len(p['sizes'])} | {seo_t} |")
    lines.append("")
    for p in pieces:
        thumb = f"{p['slug']}/master.png"
        lines.append(f"### {p['title']}")
        lines.append(f"![{p['title']}]({thumb})")
        lines.append(f"- prompt: `{p.get('prompt','')[:120]}`")
        lines.append("")
    with open(os.path.join(run_dir, "index.md"), "w") as f:
        f.write("\n".join(lines))

    run = {
        "run_dir": run_dir,
        "generated_at": now_stamp(getattr(args, "stamp", None)),
        "upscaler": "Pillow-LANCZOS (approx) or external",
        "piece_count": len(pieces),
        "pieces": [{"title": p["title"], "slug": p["slug"], "model": p.get("model"),
                    "orientation": p["orientation"], "sizes": p["sizes"],
                    "prompt": p.get("prompt", "")} for p in pieces],
    }
    with open(os.path.join(run_dir, "run.json"), "w") as f:
        json.dump(run, f, indent=2)

    print(f"index: {os.path.join(run_dir, 'index.md')}  ({len(pieces)} pieces)")
    print(f"run.json: {os.path.join(run_dir, 'run.json')}")
    return 0


GRID_HTML = """<!doctype html><html><head><meta charset=\"utf-8\">
<title>Artwork candidates — {run}</title>
<style>
 body{{background:#1a1a1a;color:#eee;font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px}}
 h1{{font-weight:600;font-size:18px;margin:0 0 4px}}
 .sub{{color:#888;font-size:13px;margin-bottom:20px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px}}
 .card{{background:#262626;border-radius:10px;overflow:hidden;border:1px solid #333}}
 .card img{{width:100%;display:block;background:#000}}
 .cap{{padding:10px 12px}}
 .code{{font-weight:700;font-size:15px}}
 .lab{{color:#9ab;font-size:12px;text-transform:capitalize;margin-left:6px}}
 .fn{{color:#666;font-size:10px;word-break:break-all;margin-top:4px}}
</style></head><body>
<h1>Artwork candidates</h1>
<div class=\"sub\">{run} · {n} candidates · pick by code</div>
<div class=\"grid\">
{cards}
</div></body></html>"""


def cmd_grid(args) -> int:
    cdir = args.dir
    if not os.path.isdir(cdir):
        sys.exit(f"ERROR: not a directory: {cdir}")
    pngs = [f for f in os.listdir(cdir) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    if not pngs:
        sys.exit(f"ERROR: no image candidates in {cdir}")
    cards = "\n".join(
        f'<div class="card"><img src="{f}" loading="lazy">'
        f'<div class="cap"><span class="code">{i+1}</span>'
        f'<div class="fn">{f}</div></div></div>'
        for i, f in enumerate(sorted(pngs))
    )
    run = os.path.basename(os.path.dirname(os.path.abspath(cdir)) or cdir)
    out = os.path.join(cdir, "contact-sheet.html")
    with open(out, "w") as fh:
        fh.write(GRID_HTML.format(run=run, n=len(pngs), cards=cards))
    print(f"grid: {out}  ({len(pngs)} candidates)")
    if not getattr(args, "no_open", False):
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:
            print("  (could not open browser automatically)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Artwork Grok Orchestrator mechanical chain.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="check Pillow")

    fp = sub.add_parser("finalize", help="upscale (opt) -> crop -> assemble titled folder")
    fp.add_argument("piece", help="path to piece.json")
    fp.add_argument("--upscale-method", choices=["pillow", "none"], default="pillow",
                    help="pillow = LANCZOS approx; none = copy source as master")
    fp.add_argument("--skip-upscale", action="store_true", help="alias for --upscale-method none")
    fp.add_argument("--stamp", help="override timestamp")

    ip = sub.add_parser("index", help="build run index.md + run.json")
    ip.add_argument("run_dir")
    ip.add_argument("--stamp", help="override timestamp")

    gp = sub.add_parser("grid", help="build + open a browser contact sheet of candidates")
    gp.add_argument("dir", help="directory of candidate images")
    gp.add_argument("--no-open", action="store_true", help="write HTML but do not open browser")

    args = ap.parse_args()
    return {"preflight": cmd_preflight, "finalize": cmd_finalize,
            "index": cmd_index, "grid": cmd_grid}[args.cmd](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)

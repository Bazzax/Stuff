#!/usr/bin/env python3
"""
artwork.py — the mechanical tail of the Artwork Orchestrator skill.

The AGENT does the judgment work (prompt-variation craft, selection, titling, SEO copy).
This script does the deterministic chain that has no existing skill:

    preflight                 check env + venv + upscaler; tell the user how to install if missing
    finalize <piece.json>     upscale -> crop to print sizes -> assemble the titled folder
    index <run_dir>           build the run index.md + run.json across all piece folders

Generation is NOT here — the agent calls `tooling/ad-creatives/generate.py` directly (one place
that knows how to talk to each model). This script picks up from a chosen source image.

Design notes:
- Pure stdlib + Pillow. No network. No torch.
- Upscale shells out to the Real-ESRGAN ncnn-vulkan binary (lean, Metal/Vulkan on Apple Silicon).
  Fallback path (the `realesrgan` python package) is documented in upscale() but not required.
- Crops only ever DOWNSCALE from the upscaled master, so quality never degrades on the way down.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: Pillow not available. Run inside the ad-creatives venv "
             "(tooling/ad-creatives/.venv) or `pip install Pillow`.")

DPI = 300
JPEG_QUALITY = 100

# Print sizes (width x height in inches). Portrait = taller than wide; landscape =
# wider than tall (the same popular ratios rotated). Names read as actual w x h.
SIZES = {
    "portrait":  {"4x6": (4, 6), "5x7": (5, 7), "8x10": (8, 10), "11x14": (11, 14)},
    "landscape": {"12x9": (12, 9), "20x16": (20, 16), "24x18": (24, 18),
                  "36x24": (36, 24), "A2": (23.39, 16.54)},
}

UPSCALER_ENV = "ARTWORK_UPSCALER"          # optional explicit path to the binary
UPSCALER_BIN = "realesrgan-ncnn-vulkan"    # default name on PATH
ENV_FILE = os.path.expanduser("~/.config/ai-images/env")
GENERATE_PY = "tooling/ad-creatives/generate.py"


# ---------------------------------------------------------------- helpers
def slugify(text: str) -> str:
    text = re.sub(r"[—–]", "-", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "untitled"


def find_upscaler():
    """Return a path to the Real-ESRGAN binary, or None."""
    env = os.environ.get(UPSCALER_ENV)
    if env and os.path.exists(env):
        return env
    on_path = shutil.which(UPSCALER_BIN)
    if on_path:
        return on_path
    for cand in ("tooling/upscale/" + UPSCALER_BIN,
                 os.path.expanduser("~/.local/bin/" + UPSCALER_BIN)):
        if os.path.exists(cand):
            return cand
    return None


INSTALL_HELP = f"""\
Real-ESRGAN upscaler not found.  This skill never silently skips the upscale step
(generating at native res alone won't reach 300 DPI at the large print sizes).

One-time setup — pick ONE:

  A) ncnn-vulkan binary (recommended, no Python/torch):
     1. Download the macOS build from
        https://github.com/xinntao/Real-ESRGAN/releases  (realesrgan-ncnn-vulkan-*-macos.zip)
     2. Unzip, then:  mkdir -p tooling/upscale && mv realesrgan-ncnn-vulkan models tooling/upscale/
     3. chmod +x tooling/upscale/realesrgan-ncnn-vulkan
        (or put it on PATH, or set {UPSCALER_ENV}=/abs/path/to/realesrgan-ncnn-vulkan)

  B) Python package fallback (heavier; pulls torch):
     tooling/ad-creatives/.venv/bin/pip install realesrgan
     then set {UPSCALER_ENV} to a wrapper, or adapt upscale() to call it.
"""


def upscale(src: str, dst: str, factor: int = 4) -> None:
    """Upscale src -> dst by `factor` using Real-ESRGAN. Raises on failure."""
    binpath = find_upscaler()
    if not binpath:
        raise RuntimeError(INSTALL_HELP)
    # realesrgan-x4plus is the general-purpose 4x model shipped with the binary.
    cmd = [binpath, "-i", src, "-o", dst, "-s", str(factor), "-n", "realesrgan-x4plus"]
    # The ncnn-vulkan binary looks for models in ./models relative to CWD by default;
    # point it at the models dir shipped next to the binary so it works no matter where
    # the skill is invoked from.
    models = os.path.join(os.path.dirname(os.path.abspath(binpath)), "models")
    if os.path.isdir(models):
        cmd += ["-m", models]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError(f"Upscale failed (cmd: {' '.join(cmd)}):\n{proc.stderr or proc.stdout}")


def center_crop_resize(img: "Image.Image", w_px: int, h_px: int) -> "Image.Image":
    """Center-crop img to the target aspect, then resize to exactly (w_px, h_px)."""
    src_w, src_h = img.size
    target_ratio = w_px / h_px
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:          # source too wide -> crop sides
        new_w = round(src_h * target_ratio)
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:                                  # source too tall -> crop top/bottom
        new_h = round(src_w / target_ratio)
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return img.crop(box).resize((w_px, h_px), Image.LANCZOS)


def now_stamp(explicit=None) -> str:
    if explicit:
        return explicit
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- commands
def cmd_preflight(_args) -> int:
    ok = True
    print("Artwork Orchestrator — preflight\n")
    # env file
    if os.path.exists(ENV_FILE):
        print(f"  [ok]  api keys: {ENV_FILE}")
    else:
        ok = False
        print(f"  [!!]  missing {ENV_FILE} (GEMINI/OPENAI/OPENROUTER keys for generate.py)")
    # generate.py
    print(f"  [{'ok' if os.path.exists(GENERATE_PY) else '!!'}]  generator: {GENERATE_PY}")
    ok = ok and os.path.exists(GENERATE_PY)
    # Pillow already imported above
    print(f"  [ok]  Pillow: {Image.__version__ if hasattr(Image,'__version__') else 'present'}")
    # upscaler
    up = find_upscaler()
    if up:
        print(f"  [ok]  upscaler: {up}")
    else:
        ok = False
        print("  [!!]  upscaler: NOT FOUND\n")
        print(INSTALL_HELP)
    print("\npreflight:", "PASS" if ok else "FAIL — resolve the [!!] items above")
    return 0 if ok else 1


def _write_seo(piece_dir: str, title: str, seo: dict) -> None:
    tags = seo.get("tags", [])
    desc = seo.get("description", "")
    seo_title = seo.get("title", title)
    # human-readable
    with open(os.path.join(piece_dir, "seo.md"), "w") as f:
        f.write(f"# {title}\n\n")
        f.write(f"**Listing title** (≤140 chars): {seo_title}\n\n")
        f.write("**Tags** (Etsy: 13 max, ≤20 chars each):\n")
        for t in tags:
            f.write(f"- {t}\n")
        f.write(f"\n**Description:**\n\n{desc}\n")
    # machine-readable
    with open(os.path.join(piece_dir, "listing.json"), "w") as f:
        json.dump({"title": seo_title, "tags": tags, "description": desc}, f, indent=2)


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
        missing = [s for s in want if s not in size_set]
        if missing:
            sys.exit(f"ERROR: sizes {missing} not valid for {orientation}. "
                     f"Valid: {list(size_set)}")
        size_set = {k: size_set[k] for k in want}

    piece_dir = os.path.join(run_dir, slugify(title))
    prints_dir = os.path.join(piece_dir, "prints")
    os.makedirs(prints_dir, exist_ok=True)

    # 1) upscale -> master.png
    master = os.path.join(piece_dir, "master.png")
    if args.skip_upscale:
        print("  [warn] --skip-upscale: copying source as master (DEV/TEST ONLY)")
        shutil.copyfile(source, master)
    else:
        print(f"  upscaling {factor}x -> {master}")
        upscale(source, master, factor)

    # 2) crop master -> each print size
    with Image.open(master) as img:
        img = img.convert("RGB")
        for name, (win, hin) in size_set.items():
            w_px, h_px = round(win * DPI), round(hin * DPI)
            out = os.path.join(prints_dir, f"{name}.jpg")
            cropped = center_crop_resize(img, w_px, h_px)
            cropped.save(out, "JPEG", quality=JPEG_QUALITY, dpi=(DPI, DPI))
            print(f"    {name}: {w_px}x{h_px}px -> {out}")

    # 3) seo + prompt + meta
    _write_seo(piece_dir, title, piece.get("seo", {}))
    with open(os.path.join(piece_dir, "prompt.txt"), "w") as f:
        f.write(piece.get("prompt", "") + "\n")
    meta = {
        "title": title,
        "slug": slugify(title),
        "orientation": orientation,
        "sizes": list(size_set),
        "model": piece.get("model", ""),
        "upscale": factor if not args.skip_upscale else 0,
        "prompt": piece.get("prompt", ""),
        "seo": piece.get("seo", {}),
        "finalized_at": now_stamp(args.stamp),
    }
    with open(os.path.join(piece_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nfinalized: {piece_dir}")
    return 0


def cmd_index(args) -> int:
    run_dir = args.run_dir
    pieces = []
    for name in sorted(os.listdir(run_dir)):
        mpath = os.path.join(run_dir, name, "meta.json")
        if os.path.exists(mpath):
            with open(mpath) as f:
                pieces.append(json.load(f))

    # index.md (A1) — human overview
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

    # run.json (B4) — reproducibility manifest
    run = {
        "run_dir": run_dir,
        "generated_at": now_stamp(args.stamp),
        "upscaler": find_upscaler() or "MISSING",
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


GRID_HTML = """<!doctype html><html><head><meta charset="utf-8">
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
<div class="sub">{run} · {n} candidates · pick by code (e.g. &quot;1a, 2b&quot;)</div>
<div class="grid">
{cards}
</div></body></html>"""


def _parse_candidate(fname):
    """Best-effort ('1a', 'faithful') label from a generate.py output filename."""
    stem = os.path.basename(fname).rsplit(".", 1)[0]
    after = stem.split("_", 1)[1] if "_" in stem else stem
    label = after.split("-", 1)[0]                 # faithful / elevated2 / wildcard2
    try:
        idx = int(stem.rsplit("-", 1)[1])
    except (ValueError, IndexError):
        idx = 0
    fam = label.rstrip("0123456789")               # elevated2 -> elevated
    num = {"faithful": 1, "elevated": 2, "wildcard": 3}.get(fam)
    code = f"{num}{chr(97 + idx)}" if num is not None else f"{label}-{idx}"
    return code, fam or label, (num or 99, idx, label)


def cmd_grid(args) -> int:
    cdir = args.dir
    if not os.path.isdir(cdir):
        sys.exit(f"ERROR: not a directory: {cdir}")
    pngs = [f for f in os.listdir(cdir) if f.lower().endswith(".png")]
    if not pngs:
        sys.exit(f"ERROR: no .png candidates in {cdir} (only top-level pngs are shown)")
    items = sorted((_parse_candidate(f)[2], *_parse_candidate(f)[:2], f) for f in pngs)
    cards = "\n".join(
        f'<div class="card"><img src="{f}" loading="lazy">'
        f'<div class="cap"><span class="code">{code}</span>'
        f'<span class="lab">{fam}</span><div class="fn">{f}</div></div></div>'
        for _sk, code, fam, f in items
    )
    run = os.path.basename(os.path.dirname(os.path.abspath(cdir)) or cdir)
    out = os.path.join(cdir, "contact-sheet.html")
    with open(out, "w") as fh:
        fh.write(GRID_HTML.format(run=run, n=len(items), cards=cards))
    print(f"grid: {out}  ({len(items)} candidates)")
    if not args.no_open:
        webbrowser.open("file://" + os.path.abspath(out))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Artwork Orchestrator mechanical chain.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="check env + venv + upscaler")

    fp = sub.add_parser("finalize", help="upscale -> crop -> assemble a titled folder")
    fp.add_argument("piece", help="path to piece.json")
    fp.add_argument("--skip-upscale", action="store_true",
                    help="DEV/TEST ONLY: copy source as master, no upscale")
    fp.add_argument("--stamp", help="override timestamp (for reproducible tests)")

    ip = sub.add_parser("index", help="build run index.md + run.json")
    ip.add_argument("run_dir")
    ip.add_argument("--stamp", help="override timestamp (for reproducible tests)")

    gp = sub.add_parser("grid", help="build + open a browser contact sheet of candidates")
    gp.add_argument("dir", help="the _candidates directory to display")
    gp.add_argument("--no-open", action="store_true", help="write the HTML but do not launch a browser")

    args = ap.parse_args()
    return {"preflight": cmd_preflight, "finalize": cmd_finalize,
            "index": cmd_index, "grid": cmd_grid}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

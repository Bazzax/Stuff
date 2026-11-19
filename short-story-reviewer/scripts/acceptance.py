"""Live acceptance run: the three public-domain test stories through the real API.

    export ANTHROPIC_API_KEY=...
    python scripts/acceptance.py --out acceptance-output

Needs the editorial method in content/. Each story is uploaded as a
fragmented .docx copy (made from tests/fixtures/stories), run through every
stage, and written out for review. Checks that code can make are made here;
the rest are printed as a checklist for a human reader.

This spends real money: roughly $0.30 to $0.70 per story at default settings.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from docx_builder import fixture_docx  # noqa: E402
from reviewer import markets as market_data  # noqa: E402
from reviewer import method as methods  # noqa: E402
from reviewer import story_io  # noqa: E402
from reviewer.annotate import validate_docx  # noqa: E402
from reviewer.config import Settings  # noqa: E402
from reviewer.docxtext import extract_text  # noqa: E402
from reviewer.llm import AnthropicLLM  # noqa: E402
from reviewer.pipeline import Review  # noqa: E402

STORIES = {
    "saki": ("the-open-window", "The Open Window", False),
    "poe": ("the-cask-of-amontillado", "The Cask of Amontillado", False),
    "wells": ("the-country-of-the-blind", "The Country of the Blind", True),
}
BRIEF = {"draft_stage": "ready to submit", "edit_level": "developmental", "questions": "",
         "conventions": "UK", "mode": "diagnosis"}
# Notes on these lines of "The Open Window" must not "correct" them: the joke is the point.
SAKI_PROTECTED = ["Romance at short notice was her speciality", "I expect it was the spaniel",
                  "You may wonder why we keep that window wide open"]


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    return ok


def run_story(key: str, out: Path, settings: Settings, content, llm) -> bool:
    slug, title, speculative = STORIES[key]
    print(f"\n{title}")
    original = fixture_docx(slug, fragment=True)
    story = story_io.from_upload(f"{slug}.docx", original)
    review = Review(settings, llm, content, story, dict(BRIEF, title=title))
    result = None
    for event in review.events():
        if event["type"] in ("stage_start", "stage_skipped"):
            print(f"  {event['type']:<13} {event['stage']}")
        if event["type"] == "error":
            return check("run completed", False, event["message"])
        if event["type"] == "result":
            result = event

    folder = out / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "letter.md").write_text(result["files"]["letter_md"]["text"], encoding="utf-8")
    (folder / "letter.docx").write_bytes(base64.b64decode(result["files"]["letter_docx"]["b64"]))
    (folder / "stages.json").write_text(json.dumps(review.outputs, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "cost.json").write_text(json.dumps(result["cost"], indent=2), encoding="utf-8")
    (folder / "upload.docx").write_bytes(original)

    ok = check("run completed", True, f"${result['cost']['total_usd']:.2f}")
    ok &= check("genre layer ran only if speculative", ("genre" in result["stages_run"]) is speculative,
                ", ".join(result["stages_run"]))
    unsourced = [w for w in result["warnings"] if "not in the story" in w]
    ok &= check("letter contains no unsourced quotation (replacement prose)", not unsourced, "; ".join(unsourced))

    annotated_b64 = result["files"].get("annotated_docx", {}).get("b64")
    ok &= check("annotated manuscript produced", bool(annotated_b64))
    if annotated_b64:
        annotated = base64.b64decode(annotated_b64)
        (folder / "annotated.docx").write_bytes(annotated)
        ok &= check("annotated text identical to upload", extract_text(annotated) == extract_text(original))
        ok &= check("annotated file validates", validate_docx(annotated) == [])
    placed = sum(1 for n in result["located_notes"] if n.get("placed"))
    print(f"  located notes placed: {placed} of {len(result['located_notes'])}")

    if key == "saki":
        risky = [n for n in result["located_notes"]
                 if any(p.lower() in n["anchor"].lower() or n["anchor"].lower() in p.lower() for p in SAKI_PROTECTED)]
        print("  Notes on Vera's invention or the last line (check none 'corrects' the joke):")
        for n in risky or [{"anchor": "(none)", "note": ""}]:
            print(f"    - “{n['anchor']}”: {n['note']}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="acceptance-output")
    parser.add_argument("--stories", default="saki,poe,wells")
    args = parser.parse_args()

    settings = Settings.load()
    content = methods.load(settings.content_dir)
    llm = AnthropicLLM()
    out = Path(args.out)

    print("Market that bars AI assistance")
    asimovs = market_data.find(market_data.load(settings.markets_file), "asimovs")
    notice = market_data.notice(asimovs, 3000)
    all_ok = check("notice shows the market's wording and date",
                   bool(notice["ai_wording"]) and bool(notice["date_checked"]))
    all_ok &= check("rewrite mode is disabled", notice["rewrite_blocked"])

    for key in args.stories.split(","):
        all_ok &= run_story(key.strip(), out, settings, content, llm)

    print(f"\nOutputs are in {out}/. Read each letter and check by hand that it:")
    print("  - follows the method's order and section headings;")
    print("  - names the story's design plausibly;")
    print("  - contains no replacement prose;")
    print("  - (Saki) never corrects Vera's deadpan invention or the last line.")
    print("Open each annotated.docx in Word and confirm the comments sit in the margin.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

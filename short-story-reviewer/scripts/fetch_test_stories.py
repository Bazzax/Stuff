"""Fetch the three public-domain acceptance-test stories from Project Gutenberg.

Writes Markdown copies (paragraphs separated by blank lines, italics as
_underscores_) to tests/fixtures/stories/. The Project Gutenberg header and
licence are stripped, which leaves plain public-domain text.

    python scripts/fetch_test_stories.py

The committed fixtures were made with this script; rerun it only to refresh
them. Use scripts/make_test_docx.py to build .docx copies for upload tests.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "stories"

# (slug, title, author, Gutenberg URL, start marker, end marker inclusive)
STORIES = [
    (
        "the-open-window",
        "The Open Window",
        "Saki (H. H. Munro)",
        "https://www.gutenberg.org/cache/epub/269/pg269.txt",
        "THE OPEN WINDOW",
        "Romance at short notice was her speciality.",
    ),
    (
        "the-cask-of-amontillado",
        "The Cask of Amontillado",
        "Edgar Allan Poe",
        "https://www.gutenberg.org/cache/epub/1063/pg1063.txt",
        "Edgar Allan Poe",
        "In pace requiescat!",
    ),
    (
        "the-country-of-the-blind",
        "The Country of the Blind",
        "H. G. Wells",
        "https://www.gutenberg.org/cache/epub/11870/pg11870.txt",
        "THE COUNTRY OF THE BLIND.",
        "peacefully contented under the cold clear stars.",
    ),
]


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8-sig").replace("\r\n", "\n")


def slice_story(text: str, start: str, end: str) -> str:
    body_start = text.index("*** START OF")
    i = text.index(start, body_start) + len(start)
    j = text.index(end, i)
    j = text.index("\n", j)
    return text[i:j]


def to_paragraphs(raw: str) -> list[str]:
    paras = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [ln.strip() for ln in block.strip().splitlines()]
        para = " ".join(ln for ln in lines if ln)
        if not para:
            continue
        if re.fullmatch(r"(\*\s*)+", para):
            para = "* * *"
        para = re.sub(r"  +", " ", para)
        paras.append(para)
    return paras


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, title, author, url, start, end in STORIES:
        raw = slice_story(fetch(url), start, end)
        paras = to_paragraphs(raw)
        header = f"<!-- {title}, by {author}. Public domain; text from {url} -->\n\n"
        (OUT / f"{slug}.md").write_text(header + "\n\n".join(paras) + "\n", encoding="utf-8")
        words = sum(len(p.split()) for p in paras)
        print(f"{slug}: {len(paras)} paragraphs, ~{words} words")
    return 0


if __name__ == "__main__":
    sys.exit(main())

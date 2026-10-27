"""Load the editorial method, and sections of the research report on demand.

The method is the core of every model call. The report is reference: only
the sections a stage needs are loaded (for example the speculative-fiction
section for the genre layer), never the whole report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

METHOD_FILE = "Short story editorial method and checklist.md"
REPORT_FILE = "Short story craft and editing.md"
EXAMPLE_LETTER_FILE = "Example editorial letter - Sorcerer Soldier.md"

MAX_REPORT_CHARS = 40_000

# Report headings that each stage loads, matched case-insensitively.
REPORT_KEYWORDS = {
    "genre": ("speculative", "science fiction", "fantasy", "sf "),
    "register": ("comic", "comedy", "humour", "humor", "deadpan", "dark", "register", "tone"),
}


class MethodMissing(RuntimeError):
    pass


@dataclass
class Content:
    method: str
    report: Optional[str]
    example_letter: Optional[str]


def load(content_dir: Path) -> Content:
    method_path = content_dir / METHOD_FILE
    if not method_path.is_file():
        raise MethodMissing(
            f'The editorial method is missing. Put "{METHOD_FILE}" in {content_dir}.'
        )
    report_path = content_dir / REPORT_FILE
    example_path = content_dir / EXAMPLE_LETTER_FILE
    return Content(
        method=method_path.read_text(encoding="utf-8"),
        report=report_path.read_text(encoding="utf-8") if report_path.is_file() else None,
        example_letter=example_path.read_text(encoding="utf-8") if example_path.is_file() else None,
    )


def _sections(markdown: str) -> List[Tuple[int, str, str]]:
    """(level, heading, full section text) for every Markdown heading."""
    heads = [(m.start(), len(m.group(1)), m.group(2).strip())
             for m in re.finditer(r"^(#{1,4})\s+(.+)$", markdown, flags=re.M)]
    out = []
    for i, (start, level, title) in enumerate(heads):
        end = len(markdown)
        for later_start, later_level, _ in heads[i + 1:]:
            if later_level <= level:
                end = later_start
                break
        out.append((level, title, markdown[start:end].strip()))
    return out


def report_sections(report: Optional[str], keywords: Iterable[str]) -> str:
    """The report sections whose headings mention any keyword.

    A matching section's subsections come with it, so they are not added a
    second time.
    """
    if not report:
        return ""
    keys = [k.lower() for k in keywords]
    chosen: List[str] = []
    for _, title, text in _sections(report):
        if not any(k in title.lower() + " " for k in keys):
            continue
        if any(text in c for c in chosen):
            continue
        chosen.append(text)
    joined = "\n\n".join(chosen)
    return joined[:MAX_REPORT_CHARS]

"""Write .docx copies of the test stories, for trying uploads by hand.

    python scripts/make_test_docx.py [out_dir]

The copies are deliberately fragmented the way Word fragments text (split
runs, spell-check and layout markers), so they exercise the annotator.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from docx_builder import STORIES, fixture_docx  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test-docx")
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(STORIES.glob("*.md")):
        target = out / f"{path.stem}.docx"
        target.write_bytes(fixture_docx(path.stem))
        print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())

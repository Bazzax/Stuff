"""Run the app with canned model responses, to try the interface without an API key.

    python scripts/preview_server.py        # then open http://127.0.0.1:8000

Uses the test fixtures' stand-in method and the fake client from the tests:
the letter it produces is placeholder text, but every other part of the
flow (upload, counts, market notice, progress, downloads, the annotated
.docx) is real. Never deploy this script.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("SSR_CONTENT_DIR", str(ROOT / "tests" / "fixtures" / "content"))
os.environ.setdefault("ANTHROPIC_API_KEY", "preview-not-used")

import uvicorn  # noqa: E402

from fake_llm import FakeLLM  # noqa: E402
from reviewer.main import app  # noqa: E402


class PreviewLLM(FakeLLM):
    """Builds anchors from whatever story the request carries."""

    def __init__(self):
        super().__init__(paragraphs=[], register="deadpan")

    def run(self, call):
        body = call.story.split("\n", 1)[1].rsplit("\n</story>", 1)[0]
        self.paragraphs = [p for p in body.split("\n\n") if len(p.split()) >= 8] or [body]
        return super().run(call)


app.state.llm_factory = PreviewLLM

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))

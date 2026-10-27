"""Read a story from pasted text or an uploaded file, and measure it.

Everything happens in memory: callers pass bytes, never paths.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .docxtext import DocxError, extract_paragraphs

# Uploads arrive base64-encoded in a JSON body; 3 MB keeps that body under
# common serverless request limits (Vercel's is 4.5 MB). Stories are far smaller.
MAX_UPLOAD_BYTES = 3 * 1024 * 1024
MAX_WORDS = 17_500
ALLOWED_EXTENSIONS = (".docx", ".txt", ".md")

WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")


class StoryError(ValueError):
    """The story could not be read, or falls outside what the app handles."""


@dataclass
class Story:
    paragraphs: List[str]
    kind: str  # "paste", "docx", "txt" or "md"
    filename: Optional[str] = None
    docx_bytes: Optional[bytes] = None

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def word_count(self) -> int:
        return count_words(self.text)

    @property
    def band(self) -> str:
        return length_band(self.word_count)


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def length_band(words: int) -> str:
    if words < 1_500:
        return "flash"
    if words < 7_500:
        return "short story"
    if words <= MAX_WORDS:
        return "novelette"
    return "over novelette length"


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StoryError("The file's text encoding could not be read. Save it as UTF-8 and try again.")


def _split_paragraphs(text: str) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    if len(blocks) == 1:
        # No blank lines: treat each line as a paragraph.
        blocks = text.split("\n")
    paras = []
    for block in blocks:
        para = " ".join(line.strip() for line in block.split("\n") if line.strip())
        if para:
            paras.append(para)
    return paras


_MD_EMPHASIS = [
    re.compile(r"(?<![\w*])\*\*(?=\S)(.+?)(?<=\S)\*\*(?![\w*])"),
    re.compile(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])"),
    re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])"),
    re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])"),
]


def strip_markdown(text: str) -> str:
    """Reduce light Markdown to the plain text a reader would see."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s{0,3}>\s?", "", line)
        lines.append(line)
    text = "\n".join(lines)
    for pattern in _MD_EMPHASIS:
        text = pattern.sub(r"\1", text)
    return text


def from_paste(text: str) -> Story:
    paras = _split_paragraphs(text or "")
    if not paras:
        raise StoryError("Paste a story, or upload a file.")
    return Story(paragraphs=paras, kind="paste")


def from_upload(filename: str, data: bytes) -> Story:
    name = (filename or "").strip()
    lower = name.lower()
    ext = next((e for e in ALLOWED_EXTENSIONS if lower.endswith(e)), None)
    if ext is None:
        raise StoryError("Upload a .docx, .txt or .md file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise StoryError("That file is larger than 3 MB.")
    if not data:
        raise StoryError("That file is empty.")

    if ext == ".docx":
        try:
            paras = [p.strip() for p in extract_paragraphs(data)]
        except DocxError as exc:
            raise StoryError(str(exc)) from exc
        paras = [p for p in paras if p]
        if not paras:
            raise StoryError("That document has no text in its body.")
        return Story(paragraphs=paras, kind="docx", filename=name, docx_bytes=data)

    text = _decode(data)
    if ext == ".md":
        text = strip_markdown(text)
    paras = _split_paragraphs(text)
    if not paras:
        raise StoryError("That file has no text in it.")
    return Story(paragraphs=paras, kind=ext.lstrip("."), filename=name)


def check_length(story: Story) -> None:
    if story.word_count > MAX_WORDS:
        raise StoryError(
            f"This story is {story.word_count:,} words. The reviewer handles stories up to "
            f"{MAX_WORDS:,} words (the top of the novelette band)."
        )

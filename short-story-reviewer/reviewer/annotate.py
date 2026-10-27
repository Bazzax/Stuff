"""Attach located notes to a .docx as Word margin comments.

The rules, from the build brief, and why:

* Word splits text into many runs (spell-check marks, revision IDs, layout
  hints). Merge adjacent runs with identical formatting first, and remove
  w:lastRenderedPageBreak and w:proofErr markers, which split runs and carry
  no text.
* Match an anchor only inside a single run. A pattern that can stretch across
  runs or paragraphs will, when the match is rewritten, duplicate paragraph
  breaks and move text. The validator does not notice; a text comparison does.
* If the full quotation is not found (or is not unique), fall back to the
  longest shorter phrase from it that is unique. The phrase must keep at
  least two words and a third of the quotation; otherwise the note is
  reported as unplaced rather than guessed.
* Never change the story's text. After writing, extract the plain text of the
  upload and of the annotated file and assert they are identical, then
  validate the package.
"""
from __future__ import annotations

import copy
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import docx
from docx.text.run import Run
from lxml import etree

from .docxtext import W, extract_text

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
AUTHOR = "Short Story Reviewer"
INITIALS = "SSR"
MIN_FALLBACK_CHARS = 5

# Characters a model may write differently from the manuscript.
_EQUIVALENTS = {
    "'": "['‘’‛ʼ]",
    "‘": "['‘’‛ʼ]",
    "’": "['‘’‛ʼ]",
    '"': "[\"“”„‟]",
    "“": "[\"“”„‟]",
    "”": "[\"“”„‟]",
}


class AnnotationError(RuntimeError):
    """The annotated file failed the text-unchanged check or validation."""


@dataclass
class Note:
    anchor: str
    text: str
    label: str = ""


@dataclass
class Placement:
    note: Note
    placed: bool
    matched: str = ""
    fallback: bool = False


@dataclass
class AnnotationResult:
    docx_bytes: bytes
    placements: List[Placement] = field(default_factory=list)

    @property
    def unplaced(self) -> List[Note]:
        return [p.note for p in self.placements if not p.placed]


# ---------------------------------------------------------------- normalising

def _is_simple_text_run(r: etree._Element) -> bool:
    """A run holding only formatting and w:t text (no tabs, breaks, fields)."""
    has_text = False
    for child in r:
        if child.tag == W + "rPr":
            continue
        if child.tag == W + "t":
            has_text = True
            continue
        return False
    return has_text


def _rpr_key(r: etree._Element) -> bytes:
    rpr = r.find(W + "rPr")
    return b"" if rpr is None else etree.tostring(rpr, method="c14n")


def _set_text(r: etree._Element, text: str) -> None:
    ts = r.findall(W + "t")
    first = ts[0]
    for extra in ts[1:]:
        r.remove(extra)
    first.text = text
    first.set(XML_SPACE, "preserve")


def _run_text(r: etree._Element) -> str:
    return "".join(t.text or "" for t in r.findall(W + "t"))


def normalise(body: etree._Element) -> None:
    """Remove run-splitting markers and merge same-format neighbouring runs."""
    for tag in ("lastRenderedPageBreak", "proofErr"):
        for el in list(body.iter(W + tag)):
            el.getparent().remove(el)

    parents = {r.getparent() for r in body.iter(W + "r")}
    for parent in parents:
        children = list(parent)
        i = 0
        while i < len(children):
            r = children[i]
            if r.tag != W + "r" or not _is_simple_text_run(r):
                i += 1
                continue
            j = i + 1
            merged = [_run_text(r)]
            key = _rpr_key(r)
            while (
                j < len(children)
                and children[j].tag == W + "r"
                and _is_simple_text_run(children[j])
                and _rpr_key(children[j]) == key
            ):
                merged.append(_run_text(children[j]))
                parent.remove(children[j])
                j += 1
            _set_text(r, "".join(merged))
            children = list(parent)
            i += 1


# ---------------------------------------------------------------- matching

def _pattern(phrase: str) -> Optional[re.Pattern]:
    """A regex for `phrase` that tolerates quote style, whitespace and dashes.

    Whitespace becomes \\s+, but the pattern is only ever run against the text
    of one run, so it cannot reach into another run or paragraph.
    """
    phrase = phrase.strip().strip("…").strip()
    phrase = re.sub(r"\.\.\.$", "", phrase).strip()
    if not phrase:
        return None
    parts = []
    i = 0
    while i < len(phrase):
        ch = phrase[i]
        if ch.isspace():
            while i < len(phrase) and phrase[i].isspace():
                i += 1
            parts.append(r"\s+")
            continue
        if ch in ("—", "–") or phrase.startswith("--", i):
            i += 2 if phrase.startswith("--", i) else 1
            parts.append("(?:—|–|--)")
            continue
        if ch == "…" or phrase.startswith("...", i):
            i += 3 if phrase.startswith("...", i) else 1
            parts.append(r"(?:…|\.\.\.)")
            continue
        parts.append(_EQUIVALENTS.get(ch, re.escape(ch)))
        i += 1
    return re.compile("".join(parts))


def _text_runs(body: etree._Element) -> Iterator[etree._Element]:
    for r in body.iter(W + "r"):
        if _is_simple_text_run(r):
            yield r


def _find(body: etree._Element, phrase: str) -> List[Tuple[etree._Element, int, int]]:
    pat = _pattern(phrase)
    if pat is None:
        return []
    hits = []
    for r in _text_runs(body):
        text = _run_text(r)
        for m in pat.finditer(text):
            if m.end() > m.start():
                hits.append((r, m.start(), m.end()))
    return hits


def _locate(body: etree._Element, anchor: str) -> Tuple[Optional[Tuple[etree._Element, int, int]], bool]:
    """Find the anchor, or the longest unique shorter phrase from it.

    Returns ((run, start, end), used_fallback) or (None, False).
    """
    hits = _find(body, anchor)
    if len(hits) == 1:
        return hits[0], False
    words = anchor.split()
    # A fallback must keep a fair share of the quotation, or a note could be
    # pinned to a stray word that merely happens to be unique.
    min_words = max(2, -(-len(words) // 3))
    for size in range(len(words) - 1, min_words - 1, -1):
        for start in range(0, len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            if len(phrase.strip(".,;:!?\"'“”‘’")) < MIN_FALLBACK_CHARS:
                continue
            hits = _find(body, phrase)
            if len(hits) == 1:
                return hits[0], True
    return None, False


def _isolate(r: etree._Element, start: int, end: int) -> etree._Element:
    """Split a run so text[start:end] sits in a run of its own; return that run."""
    text = _run_text(r)
    if start > 0:
        before = copy.deepcopy(r)
        _set_text(before, text[:start])
        r.addprevious(before)
    if end < len(text):
        after = copy.deepcopy(r)
        _set_text(after, text[end:])
        r.addnext(after)
    _set_text(r, text[start:end])
    return r


# ---------------------------------------------------------------- validation

COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"


def validate_docx(data: bytes) -> List[str]:
    """Structural checks on a .docx package. Returns a list of problems."""
    problems: List[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["not a zip package"]
    with zf:
        bad = zf.testzip()
        if bad:
            problems.append(f"corrupt zip member {bad}")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
        parts: Dict[str, etree._Element] = {}
        for name in zf.namelist():
            if name.endswith((".xml", ".rels")):
                try:
                    parts[name] = etree.fromstring(zf.read(name), parser)
                except etree.XMLSyntaxError as exc:
                    problems.append(f"{name} is not well-formed XML: {exc}")
        if problems:
            return problems

        doc = parts.get("word/document.xml")
        if doc is None:
            return ["word/document.xml is missing"]

        def ids(tag: str) -> List[str]:
            return [el.get(W + "id") for el in doc.iter(W + tag)]

        starts, ends, refs = ids("commentRangeStart"), ids("commentRangeEnd"), ids("commentReference")
        if not (starts or ends or refs):
            return problems

        comments = parts.get("word/comments.xml")
        if comments is None:
            return ["comment markers present but word/comments.xml is missing"]
        defined = [c.get(W + "id") for c in comments.iter(W + "comment")]

        ct = parts.get("[Content_Types].xml")
        overrides = {
            o.get("PartName"): o.get("ContentType")
            for o in (ct.iter("{http://schemas.openxmlformats.org/package/2006/content-types}Override")
                      if ct is not None else [])
        }
        if overrides.get("/word/comments.xml") != COMMENTS_CT:
            problems.append("[Content_Types].xml has no override for /word/comments.xml")

        rels = parts.get("word/_rels/document.xml.rels")
        rel_ok = rels is not None and any(
            rel.get("Type") == COMMENTS_REL and rel.get("Target", "").endswith("comments.xml")
            for rel in rels
        )
        if not rel_ok:
            problems.append("document.xml.rels has no relationship to comments.xml")

        if len(set(defined)) != len(defined):
            problems.append("duplicate comment ids in comments.xml")
        for name, found in (("commentRangeStart", starts), ("commentRangeEnd", ends),
                            ("commentReference", refs)):
            if sorted(found) != sorted(set(found)):
                problems.append(f"duplicate {name} ids")
            if set(found) != set(defined):
                problems.append(f"{name} ids do not match the comments defined")

        order = {}
        for i, el in enumerate(doc.iter()):
            if el.tag in (W + "commentRangeStart", W + "commentRangeEnd"):
                order.setdefault(el.get(W + "id"), []).append((i, el.tag))
        for cid, marks in order.items():
            tags = [t for _, t in sorted(marks)]
            if tags != [W + "commentRangeStart", W + "commentRangeEnd"]:
                problems.append(f"comment {cid}: range start does not precede its end")

    try:
        docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - any failure to reopen is a validation failure
        problems.append(f"python-docx cannot reopen the file: {exc}")
    return problems


# ---------------------------------------------------------------- entry point

def annotate(docx_bytes: bytes, notes: List[Note]) -> AnnotationResult:
    """Return a copy of the document with each note attached as a comment.

    Raises AnnotationError if the annotated text differs from the upload or
    the package fails validation.
    """
    document = docx.Document(io.BytesIO(docx_bytes))
    body = document.element.body
    normalise(body)

    placements = []
    for note in notes:
        hit, used_fallback = _locate(body, note.anchor)
        if hit is None:
            placements.append(Placement(note=note, placed=False))
            continue
        r, start, end = hit
        matched = _run_text(r)[start:end]
        target = _isolate(r, start, end)
        comment_text = f"{note.label}: {note.text}" if note.label else note.text
        document.add_comment(Run(target, None), text=comment_text, author=AUTHOR, initials=INITIALS)
        placements.append(Placement(note=note, placed=True, matched=matched, fallback=used_fallback))

    out = io.BytesIO()
    document.save(out)
    result = out.getvalue()

    if extract_text(result) != extract_text(docx_bytes):
        raise AnnotationError("The annotated file's text differs from the upload; it was not returned.")
    problems = validate_docx(result)
    if problems:
        raise AnnotationError("The annotated file failed validation: " + "; ".join(problems))
    return AnnotationResult(docx_bytes=result, placements=placements)

"""Plain-text extraction straight from a .docx package.

This deliberately reads word/document.xml with lxml rather than going through
python-docx, so the check that annotation left the story untouched compares
two files with an extractor that shares no code with the annotator.
"""
from __future__ import annotations

import io
import zipfile
from typing import List

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % W_NS

# Elements inside a run that stand for characters.
_CHAR_ELEMENTS = {
    W + "tab": "\t",
    W + "br": "\n",
    W + "cr": "\n",
    W + "noBreakHyphen": "‑",
    W + "softHyphen": "­",
}


class DocxError(ValueError):
    """The bytes are not a readable .docx package."""


def read_document_xml(docx_bytes: bytes) -> etree._Element:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise DocxError("This file is not a Word .docx document.") from exc
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    return etree.fromstring(xml, parser)


def _paragraph_text(p: etree._Element) -> str:
    parts = []
    for el in p.iter():
        if el.tag == W + "t":
            parts.append(el.text or "")
        elif el.tag in _CHAR_ELEMENTS:
            parts.append(_CHAR_ELEMENTS[el.tag])
        elif el.tag == W + "sym":
            parts.append("�")
    return "".join(parts)


def extract_paragraphs(docx_bytes: bytes) -> List[str]:
    """Every body paragraph's text, in document order, empty ones included.

    Nested paragraphs (table cells, text boxes) are visited in order. Deleted
    tracked-change text lives in w:delText and is not counted.
    """
    root = read_document_xml(docx_bytes)
    body = root.find(W + "body")
    if body is None:
        return []
    # A paragraph nested in another paragraph (text box content) is part of
    # the outer paragraph's iteration, so only take outermost w:p elements
    # once and let _paragraph_text walk the rest.
    out = []
    for p in body.iter(W + "p"):
        if any(anc.tag == W + "p" for anc in p.iterancestors()):
            continue
        out.append(_paragraph_text(p))
    return out


def extract_text(docx_bytes: bytes) -> str:
    """The document's plain text, one line per paragraph."""
    return "\n".join(extract_paragraphs(docx_bytes))

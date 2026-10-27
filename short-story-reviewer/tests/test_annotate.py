import io
import zipfile

import pytest

pytest.importorskip("docx")

from docx_builder import build_docx, fixture_docx  # noqa: E402
from reviewer.annotate import AnnotationError, Note, annotate, validate_docx  # noqa: E402
from reviewer.docxtext import extract_text  # noqa: E402


def comments_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/comments.xml").decode("utf-8")


def document_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/document.xml").decode("utf-8")


@pytest.mark.parametrize("slug", ["the-open-window", "the-cask-of-amontillado", "the-country-of-the-blind"])
def test_text_unchanged_and_valid_on_fragmented_fixtures(slug):
    original = fixture_docx(slug, fragment=True)
    notes = [
        Note("self-possessed young lady of fifteen", "Note one"),
        Note("I vowed revenge", "Note two"),
        Note("the Country of the Blind", "Note three"),
        Note("Romance at short notice was her speciality.", "Note four"),
        Note("In pace requiescat!", "Note five"),
        Note("under the cold clear stars", "Note six"),
    ]
    result = annotate(original, notes)
    assert extract_text(result.docx_bytes) == extract_text(original)
    assert validate_docx(result.docx_bytes) == []
    assert any(p.placed for p in result.placements)


def test_anchor_is_found_inside_one_run_after_merging():
    original = build_docx(["The quick brown fox jumps over the lazy dog."], fragment=True, seed=3)
    # Fragmenting cut this sentence into several runs; the merge rejoins them.
    assert document_xml(original).count("<w:r>") > 1
    result = annotate(original, [Note("brown fox jumps", "Which fox?")])
    placement = result.placements[0]
    assert placement.placed and not placement.fallback
    assert placement.matched == "brown fox jumps"
    assert "Which fox?" in comments_xml(result.docx_bytes)


def test_anchor_never_spans_a_formatting_change():
    # "very" is italic, so the full anchor crosses runs. It must not be matched
    # across them; the longest unique phrase inside one run is used instead.
    original = build_docx(["She was _very_ sure the window was open that evening."])
    result = annotate(original, [Note("was very sure the window was open", "Check")])
    placement = result.placements[0]
    assert placement.placed and placement.fallback
    assert placement.matched == "sure the window was open"
    assert extract_text(result.docx_bytes) == extract_text(original)


def test_anchor_never_spans_paragraphs():
    original = build_docx(["The first paragraph ends here.", "The second begins here."])
    result = annotate(original, [Note("ends here. The second", "Across a break")])
    placement = result.placements[0]
    assert placement.placed and placement.fallback
    assert "\n" not in placement.matched
    assert extract_text(result.docx_bytes) == extract_text(original)


def test_quote_style_and_dash_differences_still_match():
    original = build_docx(["“I’m sure,” she said—quietly."])
    result = annotate(original, [Note("\"I'm sure,\" she said--quietly", "Tag")])
    assert result.placements[0].placed and not result.placements[0].fallback


def test_ambiguous_or_missing_anchor_is_reported_not_guessed():
    original = build_docx(["The dog barked.", "The dog barked."])
    result = annotate(original, [Note("The dog barked", "Which one?"), Note("no such words here", "x")])
    assert [p.placed for p in result.placements] == [False, False]
    assert len(result.unplaced) == 2
    assert validate_docx(result.docx_bytes) == []


def test_two_notes_on_the_same_run():
    original = build_docx(["Alpha beta gamma delta epsilon zeta eta theta."])
    result = annotate(original, [Note("beta gamma", "one"), Note("epsilon zeta", "two"),
                                 Note("gamma delta", "overlaps the first")])
    assert all(p.placed for p in result.placements[:2])
    assert extract_text(result.docx_bytes) == extract_text(original)
    assert validate_docx(result.docx_bytes) == []


def test_text_check_catches_a_changed_document(monkeypatch):
    import reviewer.annotate as mod

    original = build_docx(["Some text here."])
    real_isolate = mod._isolate

    def corrupting_isolate(r, start, end):
        target = real_isolate(r, start, end)
        mod._set_text(target, mod._run_text(target) + "\n")
        return target

    monkeypatch.setattr(mod, "_isolate", corrupting_isolate)
    with pytest.raises(AnnotationError):
        annotate(original, [Note("text here", "x")])


def test_validator_flags_dangling_comment_markers():
    original = build_docx(["Some text here."])
    good = annotate(original, [Note("text here", "x")]).docx_bytes
    src = io.BytesIO(good)
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b"commentRangeEnd", b"bookmarkEnd")
            zout.writestr(item, data)
    assert validate_docx(out.getvalue())

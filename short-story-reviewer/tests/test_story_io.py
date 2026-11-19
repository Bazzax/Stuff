import pytest

pytest.importorskip("docx")

from docx_builder import build_docx, fixture_docx, load_fixture  # noqa: E402
from reviewer import story_io  # noqa: E402


@pytest.mark.parametrize(
    "words, band",
    [(1, "flash"), (1_499, "flash"), (1_500, "short story"), (7_499, "short story"),
     (7_500, "novelette"), (17_500, "novelette"), (17_501, "over novelette length")],
)
def test_length_bands(words, band):
    assert story_io.length_band(words) == band


def test_word_count_handles_contractions_hyphens_and_dashes():
    assert story_io.count_words("It’s a well-made thing—truly. Don't.") == 6


def test_paste_splits_paragraphs():
    story = story_io.from_paste("One line\nwrapped.\n\nSecond para.")
    assert story.paragraphs == ["One line wrapped.", "Second para."]
    assert story.kind == "paste"


def test_markdown_upload_strips_markup():
    data = b"<!-- note -->\n# Title\n\nShe was _very_ sure, **quite** sure.\n\n* * *\n\nEnd."
    story = story_io.from_upload("s.md", data)
    assert story.paragraphs == ["Title", "She was very sure, quite sure.", "* * *", "End."]


def test_txt_falls_back_to_cp1252():
    story = story_io.from_upload("s.txt", "Café society.".encode("cp1252"))
    assert story.paragraphs == ["Café society."]


def test_docx_upload_matches_fixture_text():
    title, paras = load_fixture("the-open-window")
    story = story_io.from_upload("open-window.docx", fixture_docx("the-open-window"))
    assert story.kind == "docx"
    assert story.paragraphs[0] == title
    assert story.paragraphs[1:] == [p.replace("_", "") for p in paras]
    assert story.band == "flash"


def test_rejects_other_types_and_bad_docx():
    with pytest.raises(story_io.StoryError):
        story_io.from_upload("story.pdf", b"%PDF")
    with pytest.raises(story_io.StoryError):
        story_io.from_upload("story.docx", b"not a zip")


def test_check_length_refuses_novellas():
    story = story_io.from_paste("word " * 17_501)
    with pytest.raises(story_io.StoryError):
        story_io.check_length(story)


def test_empty_docx_body_is_an_error():
    with pytest.raises(story_io.StoryError):
        story_io.from_upload("empty.docx", build_docx([]))

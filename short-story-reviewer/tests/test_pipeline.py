import base64
import io
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("docx")

from docx_builder import fixture_docx, load_fixture  # noqa: E402
from fake_llm import FakeLLM  # noqa: E402
from reviewer import method as methods  # noqa: E402
from reviewer import story_io  # noqa: E402
from reviewer.annotate import validate_docx  # noqa: E402
from reviewer.config import OPUS, Settings, defaults  # noqa: E402
from reviewer.cost import estimate  # noqa: E402
from reviewer.docxtext import extract_text  # noqa: E402
from reviewer.pipeline import Review, sample_passages, stage_plan  # noqa: E402

CONTENT = Path(__file__).resolve().parent / "fixtures" / "content"

BRIEF = {"title": "", "draft_stage": "ready to submit", "edit_level": "developmental", "questions": "Does the end land?",
         "conventions": "UK", "mode": "diagnosis"}

STORIES = {
    # slug: (register the fake reports, speculative?)
    "the-open-window": ("deadpan", False),
    "the-cask-of-amontillado": ("dark", False),
    "the-country-of-the-blind": ("realist", True),
}


def md_story(slug):
    data = (Path(__file__).parent / "fixtures" / "stories" / f"{slug}.md").read_bytes()
    return story_io.from_upload(f"{slug}.md", data)


def run_review(story, fake, brief=None, market=None):
    review = Review(Settings(defaults()), fake, methods.load(CONTENT), story, dict(brief or BRIEF), market)
    events = list(review.events())
    return review, events


@pytest.mark.parametrize("slug", list(STORIES))
def test_genre_layer_runs_for_the_speculative_story_only(slug):
    register, speculative = STORIES[slug]
    story = md_story(slug)
    fake = FakeLLM(story.paragraphs, register=register, speculative=speculative)
    _, events = run_review(story, fake)
    result = events[-1]
    assert result["type"] == "result", events[-1]
    assert ("genre" in result["stages_run"]) is speculative
    assert ("register" in result["stages_run"]) is (register in {"comic", "deadpan", "dark"})
    skipped = {e["stage"] for e in events if e["type"] == "stage_skipped"}
    assert skipped == {"genre", "register"} - set(result["stages_run"])


def test_every_call_shares_the_cached_prefix():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan")
    run_review(story, fake)
    systems = {call.system for _, call in fake.calls}
    stories = {call.story for _, call in fake.calls}
    assert len(systems) == 1 and len(stories) == 1
    system = systems.pop()
    assert "TEST FIXTURE ONLY" in system  # the method is in the system prompt
    assert "Romance at short notice was her speciality." in stories.pop()


def test_each_stage_receives_brief_and_earlier_outputs():
    story = md_story("the-cask-of-amontillado")
    fake = FakeLLM(story.paragraphs, register="dark")
    run_review(story, fake)
    requests = dict((k, c.request) for k, c in fake.calls)
    assert "Does the end land?" in requests["cold_read"]
    assert '<stage name="cold_read">' in requests["design"]
    assert '<stage name="line">' in requests["letter"]
    assert "<counts>" in requests["line"]
    assert "<counts>" not in requests["triage"].split("<earlier_stages>")[0]
    assert "No rewriting." in requests["letter"]


def test_report_sections_load_on_demand():
    story = md_story("the-country-of-the-blind")
    fake = FakeLLM(story.paragraphs, speculative=True)
    run_review(story, fake)
    requests = dict((k, c.request) for k, c in fake.calls)
    assert "the novum and worldbuilding" in requests["genre"]
    assert "Subsection about science fiction" in requests["genre"]
    assert "Material about openings" not in requests["genre"]
    assert "<report_reference>" not in requests["cold_read"]


def test_long_story_line_pass_is_sampled():
    story = md_story("the-country-of-the-blind")
    assert story.word_count > 5000
    fake = FakeLLM(story.paragraphs, speculative=True)
    run_review(story, fake)
    line = dict((k, c.request) for k, c in fake.calls)["line"]
    for label in ("opening", "turning point", "climax", "ending"):
        assert f'<passage label="{label}">' in line


def test_short_story_line_pass_is_not_sampled():
    story = md_story("the-cask-of-amontillado")
    fake = FakeLLM(story.paragraphs, register="dark")
    run_review(story, fake)
    assert "<sampled_passages>" not in dict((k, c.request) for k, c in fake.calls)["line"]


def test_sample_passages_do_not_overlap():
    _, paras = load_fixture("the-country-of-the-blind")
    passages = sample_passages(paras, {"turning_point": {"anchor": paras[100][:40]},
                                       "climax": {"anchor": paras[180][:40]}}, 450)
    texts = [p["text"] for p in passages]
    assert len(texts) == 4
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            assert not set(a.split("\n\n")) & set(b.split("\n\n"))


def test_docx_upload_gets_annotated_with_text_unchanged():
    original = fixture_docx("the-country-of-the-blind", fragment=True)
    story = story_io.from_upload("country.docx", original)
    fake = FakeLLM(story.paragraphs, speculative=True)
    _, events = run_review(story, fake)
    result = events[-1]
    annotated = base64.b64decode(result["files"]["annotated_docx"]["b64"])
    assert extract_text(annotated) == extract_text(original)
    assert validate_docx(annotated) == []
    placed = [n["placed"] for n in result["located_notes"]]
    assert placed == [True, True, False]
    assert any("could not be found" in w for w in result["warnings"])


def test_rewrite_mode_keeps_suggestions_out_of_the_manuscript():
    original = fixture_docx("the-open-window", fragment=True)
    story = story_io.from_upload("window.docx", original)
    fake = FakeLLM(story.paragraphs, register="deadpan")
    _, events = run_review(story, fake, brief=dict(BRIEF, mode="rewrites"))
    result = events[-1]
    letter_call = dict(fake.calls)["letter"]
    assert "suggestions" in letter_call.schema["properties"]
    assert "Rewrites." in letter_call.request
    assert "Suggestion" in result["files"]["letter_md"]["text"]
    assert "suggestions only" in result["files"]["letter_md"]["text"]
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["files"]["annotated_docx"]["b64"]))) as zf:
        comments = zf.read("word/comments.xml").decode("utf-8")
    assert "Cut the second clause" not in comments
    # Earlier stages are diagnosis-only even in rewrite mode.
    assert "No rewriting." in dict(fake.calls)["triage"].request


def test_diagnosis_mode_has_no_suggestions_field():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan")
    run_review(story, fake)
    assert "suggestions" not in dict(fake.calls)["letter"].schema["properties"]


def test_unsourced_quotation_in_letter_is_flagged():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan", letter_quote="her aunt walked slowly into the garden")
    _, events = run_review(story, fake)
    assert any("not in the story" in w for w in events[-1]["warnings"])


def test_quoting_the_story_exactly_is_not_flagged():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan", letter_quote="Romance at short notice was her speciality.")
    _, events = run_review(story, fake)
    assert not any("not in the story" in w for w in events[-1]["warnings"])


def test_truncated_stage_is_retried_with_a_larger_cap():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan", truncate="line")
    review, events = run_review(story, fake)
    assert events[-1]["type"] == "result"
    line_calls = [c for k, c in fake.calls if k == "line"]
    assert len(line_calls) == 2
    assert line_calls[-1].max_tokens == int(defaults()["stages"]["line"]["max_tokens"] * 1.5)
    assert sum(1 for s in review.stage_costs if s["stage"] == "line") == 2


def test_cancelled_review_stops_before_the_next_stage():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan")
    review = Review(Settings(defaults()), fake, methods.load(CONTENT), story, dict(BRIEF))
    review.should_stop = lambda: len(fake.calls) >= 1
    events = list(review.events())
    assert events[-1] == {"type": "error", "message": "The review was cancelled.", "spent_usd": events[-1]["spent_usd"]}
    assert len(fake.calls) == 1


def test_costs_are_tallied_per_stage():
    story = md_story("the-open-window")
    fake = FakeLLM(story.paragraphs, register="deadpan")
    review, events = run_review(story, fake)
    cost = events[-1]["cost"]
    assert len(cost["by_stage"]) == len(events[-1]["stages_run"])
    assert cost["total_usd"] == pytest.approx(review.spent, abs=1e-3)


def test_estimate_for_15000_words_on_opus_throughout():
    data = defaults()
    for stage in data["stages"].values():
        stage["model"] = OPUS
    settings = Settings(data)
    story_text = ("word " * 15_000).strip()
    est = estimate(settings, stage_plan(), story_text, "m" * 40_000, {})
    # The brief's rough target: under $1 expected for a staged edit of this size.
    assert est["expected_usd"] < 1.0
    assert est["max_usd"] > est["expected_usd"]

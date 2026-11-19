import base64
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("docx")

from fastapi.testclient import TestClient  # noqa: E402

from docx_builder import fixture_docx  # noqa: E402
from fake_llm import FakeLLM  # noqa: E402
from reviewer import story_io  # noqa: E402
from reviewer.config import Settings, defaults  # noqa: E402
from reviewer.main import app  # noqa: E402
from reviewer.guards import RateLimiter, SpendTracker  # noqa: E402

HERE = Path(__file__).resolve().parent
CONTENT = HERE / "fixtures" / "content"
SAKI = (HERE / "fixtures" / "stories" / "the-open-window.md").read_text(encoding="utf-8")
BRIEF = {"draft_stage": "early draft", "edit_level": "developmental", "conventions": "UK", "mode": "diagnosis"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SSR_CONTENT_DIR", str(CONTENT))
    monkeypatch.delenv("SSR_ACCESS_CODE", raising=False)
    app.state.settings = Settings(defaults())
    app.state.rate = RateLimiter()
    app.state.spend = SpendTracker()
    story = story_io.from_paste(story_io.strip_markdown(SAKI))
    app.state.llm_factory = lambda: FakeLLM(story.paragraphs, register="deadpan")
    yield TestClient(app)
    app.state.llm_factory = None


def events_of(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_config_lists_markets_with_dated_notices(client):
    data = client.get("/api/config").json()
    assert data["method_loaded"] is True
    asimovs = next(m for m in data["markets"] if m["id"] == "asimovs")
    assert asimovs["notice"]["date_checked"] == "2026-10-27"
    assert "assisted by these tools" in asimovs["notice"]["ai_wording"]
    assert asimovs["notice"]["rewrite_blocked"] is True


def test_analyse_pasted_story(client):
    data = client.post("/api/analyse", json={"story": {"text": story_io.strip_markdown(SAKI)}}).json()
    assert data["band"] == "flash"
    assert 1150 < data["word_count"] < 1300
    assert data["counts_summary"]


def test_analyse_docx_upload(client):
    b64 = base64.b64encode(fixture_docx("the-cask-of-amontillado")).decode()
    data = client.post("/api/analyse", json={"story": {"file_name": "cask.docx", "file_b64": b64}}).json()
    assert data["kind"] == "docx"
    assert data["band"] == "short story"


def test_market_that_bars_ai_shows_wording_and_blocks_rewrites(client):
    body = {"story": {"text": "A short story. " * 50}, "brief": dict(BRIEF, market_id="asimovs")}
    data = client.post("/api/estimate", json=body).json()
    notice = data["notice"]
    assert notice["rewrite_blocked"] is True
    assert "We will not consider any submissions written, developed, or assisted" in notice["ai_wording"]
    assert notice["date_checked"]
    assert any("Rewrite mode is off" in s for s in notice["statements"])
    assert any("under this market's minimum" in s for s in notice["statements"])

    blocked = client.post("/api/run", json={"story": body["story"], "brief": dict(body["brief"], mode="rewrites")})
    assert blocked.status_code == 400
    assert "rewrite mode is off" in blocked.json()["error"]


def test_custom_market_has_no_policy_on_file(client):
    body = {"story": {"text": "A short story. " * 50}, "brief": dict(BRIEF, market_name="The Village Quarterly")}
    notice = client.post("/api/estimate", json=body).json()["notice"]
    assert notice["custom"] is True
    assert "no policy on file" in notice["statements"][0]


def test_full_run_streams_progress_then_result(client):
    body = {"story": {"text": story_io.strip_markdown(SAKI)}, "brief": BRIEF}
    response = client.post("/api/run", json=body)
    assert response.status_code == 200
    events = events_of(response)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "stage_start" and kinds[-1] == "result"
    assert "stage_skipped" in kinds  # the genre layer, for a non-speculative story
    result = events[-1]
    assert "<h3>" in result["letter_html"]
    assert result["files"]["letter_md"]["text"].startswith("# Editorial letter")
    assert "annotated_docx" not in result["files"]


def test_validation_errors_do_not_echo_the_story(client):
    secret = "The secret plot twist is that the butler did it."
    response = client.post("/api/run", json={"story": {"text": secret}, "brief": dict(BRIEF, mode="rewrite-everything")})
    assert response.status_code == 422
    assert secret not in response.text


def test_runs_are_rate_limited(client):
    app.state.settings.data["limits"]["runs_per_hour_per_ip"] = 1
    body = {"story": {"text": story_io.strip_markdown(SAKI)}, "brief": BRIEF}
    assert client.post("/api/run", json=body).status_code == 200
    assert client.post("/api/run", json=body).status_code == 429


def test_run_refused_over_the_per_run_cap(client):
    app.state.settings.data["limits"]["max_run_cost_usd"] = 0.01
    body = {"story": {"text": story_io.strip_markdown(SAKI)}, "brief": BRIEF}
    response = client.post("/api/run", json=body)
    assert response.status_code == 400
    assert "per-run cap" in response.json()["error"]


def test_access_code(client, monkeypatch):
    monkeypatch.setenv("SSR_ACCESS_CODE", "lantern")
    body = {"story": {"text": "Some words here."}}
    assert client.post("/api/analyse", json=body).status_code == 401
    assert client.post("/api/analyse", json=body, headers={"X-Access-Code": "lantern"}).status_code == 200


def test_run_refused_without_method(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SSR_CONTENT_DIR", str(tmp_path))
    body = {"story": {"text": "Some words here."}, "brief": BRIEF}
    response = client.post("/api/run", json=body)
    assert response.status_code == 503
    assert "method" in response.json()["error"]


def test_pages_served(client):
    assert "Short Story Reviewer" in client.get("/").text
    assert "processes them in memory" in client.get("/privacy").text

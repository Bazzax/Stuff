"""The web app.

    uvicorn reviewer.main:app --reload

Stories arrive in JSON request bodies (files base64-encoded), are processed
in memory and are dropped when the request ends. Nothing about a story is
written to disk or logged.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import queue
import threading
from pathlib import Path
from typing import Dict, Iterator, Literal, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import counts as counting
from . import markets as market_data
from . import method as methods
from .config import Settings
from .cost import estimate as estimate_cost
from .cost import tokens_for
from .guards import RateLimiter, SpendTracker
from .llm import AnthropicLLM
from .pipeline import Review, stage_plan
from .story_io import MAX_WORDS, Story, StoryError, check_length, from_paste, from_upload

log = logging.getLogger("reviewer")
STATIC = Path(__file__).resolve().parent / "static"
# Assumed method size for estimates made before the method file is installed.
ASSUMED_METHOD_CHARS = 60_000
HEARTBEAT_SECONDS = 10


class StoryIn(BaseModel):
    text: Optional[str] = Field(None, max_length=200_000)
    file_name: Optional[str] = Field(None, max_length=255)
    file_b64: Optional[str] = Field(None, max_length=4_300_000)


class BriefIn(BaseModel):
    title: str = Field("", max_length=200)
    market_id: Optional[str] = Field(None, max_length=100)
    market_name: str = Field("", max_length=200)
    draft_stage: Literal["early draft", "ready to submit", "accepted"] = "early draft"
    edit_level: Literal["developmental", "line", "copy"] = "developmental"
    questions: str = Field("", max_length=3_000)
    conventions: Literal["UK", "US"] = "UK"
    mode: Literal["diagnosis", "rewrites"] = "diagnosis"


class AnalyseIn(BaseModel):
    story: StoryIn


class RunIn(BaseModel):
    story: StoryIn
    brief: BriefIn


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


app = FastAPI(title="Short Story Reviewer", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.state.settings = Settings.load()
app.state.rate = RateLimiter()
app.state.spend = SpendTracker()
# None means the real Anthropic client; tests install a fake factory here.
app.state.llm_factory = None


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    # FastAPI's default response echoes the submitted input; never echo a story.
    fields = sorted({".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()})
    return JSONResponse({"error": "Some fields were not valid: " + ", ".join(fields)}, status_code=422)


# ---------------------------------------------------------------- helpers

def _settings() -> Settings:
    return app.state.settings


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _guard(request: Request, bucket: str, limit: float, window: float) -> None:
    code = _settings().access_code
    if code and request.headers.get("x-access-code", "") != code:
        raise ApiError(401, "This reviewer needs an access code.")
    if not app.state.rate.allow(f"{bucket}:{_client_ip(request)}", int(limit), window):
        raise ApiError(429, "Too many requests from this address. Wait a while and try again.")


def _read_story(data: StoryIn) -> Story:
    try:
        if data.file_b64:
            try:
                raw = base64.b64decode(data.file_b64, validate=True)
            except (binascii.Error, ValueError):
                raise ApiError(400, "The uploaded file could not be read.")
            return from_upload(data.file_name or "", raw)
        return from_paste(data.text or "")
    except StoryError as exc:
        raise ApiError(400, str(exc))


def _market(brief: BriefIn) -> Tuple[Optional[Dict], Optional[Dict]]:
    """(market for the model brief, notice for the page)."""
    listed = market_data.find(market_data.load(_settings().markets_file), brief.market_id)
    if listed:
        return listed, None
    if brief.market_name.strip():
        name = brief.market_name.strip()
        return {"id": "", "name": name}, {
            "name": name, "custom": True, "rewrite_blocked": False,
            "statements": ["There is no policy on file for this market. Check its guidelines on AI use "
                           "before you run."],
        }
    return None, None


def _content() -> Optional[methods.Content]:
    try:
        return methods.load(_settings().content_dir)
    except methods.MethodMissing:
        return None


def _estimate(story: Story, content: Optional[methods.Content]) -> Dict:
    method_text = content.method if content else "x" * ASSUMED_METHOD_CHARS
    report = content.report if content else None
    report_tokens = {
        key: tokens_for(methods.report_sections(report, words)) for key, words in methods.REPORT_KEYWORDS.items()
    }
    if content and content.example_letter:
        report_tokens["letter"] = tokens_for(content.example_letter)
    return estimate_cost(_settings(), stage_plan(), story.text, method_text, report_tokens)


# ---------------------------------------------------------------- pages

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/privacy")
def privacy():
    return FileResponse(STATIC / "privacy.html")


@app.get("/api/config")
def config():
    settings = _settings()
    content = _content()
    return {
        "markets": [{"id": m["id"], "name": m["name"], "notice": market_data.notice(m)}
                    for m in market_data.load(settings.markets_file)],
        "method_loaded": content is not None,
        "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "access_code_required": bool(settings.access_code),
        "max_words": MAX_WORDS,
        "max_run_cost_usd": settings.limits["max_run_cost_usd"],
        "stages": [{"key": k, "model": settings.stage(k).model} for k in stage_plan()],
    }


@app.post("/api/analyse")
def analyse(body: AnalyseIn, request: Request):
    _guard(request, "req", _settings().limits["requests_per_minute_per_ip"], 60)
    story = _read_story(body.story)
    words = story.word_count
    return {
        "word_count": words,
        "band": story.band,
        "kind": story.kind,
        "filename": story.filename,
        "paragraphs": len(story.paragraphs),
        "too_long": words > MAX_WORDS,
        "counts_summary": counting.summary_lines(counting.count_story(story.paragraphs)),
    }


@app.post("/api/estimate")
def estimate(body: RunIn, request: Request):
    _guard(request, "req", _settings().limits["requests_per_minute_per_ip"], 60)
    story = _read_story(body.story)
    listed, custom_notice = _market(body.brief)
    notice = custom_notice or market_data.notice(listed if listed and listed.get("id") else None, story.word_count)
    est = _estimate(story, _content())
    return {
        "notice": notice,
        "estimate": est,
        "within_run_cap": est["max_usd"] <= _settings().limits["max_run_cost_usd"],
    }


@app.post("/api/run")
def run(body: RunIn, request: Request):
    settings = _settings()
    _guard(request, "run", settings.limits["runs_per_hour_per_ip"], 3600)

    content = _content()
    if content is None:
        raise ApiError(503, "The editorial method has not been installed on this server yet.")
    factory = app.state.llm_factory
    if factory is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ApiError(503, "No Anthropic API key is configured on this server.")
        factory = AnthropicLLM

    story = _read_story(body.story)
    try:
        check_length(story)
    except StoryError as exc:
        raise ApiError(400, str(exc))

    market, _ = _market(body.brief)
    if body.brief.mode == "rewrites" and market_data.rewrite_blocked(market):
        raise ApiError(400, f"{market['name']} bars AI-written or AI-edited text, so rewrite mode is off.")

    est = _estimate(story, content)
    if est["max_usd"] > settings.limits["max_run_cost_usd"]:
        raise ApiError(400, f"This run could cost up to ${est['max_usd']:.2f}, over the per-run cap of "
                            f"${settings.limits['max_run_cost_usd']:.2f}.")
    if not app.state.spend.can_afford(est["max_usd"], settings.limits["daily_spend_cap_usd"]):
        raise ApiError(503, "The reviewer has reached today's spending cap. Try again tomorrow.")

    try:
        llm = factory()
    except Exception:  # noqa: BLE001 - surface any client setup failure without detail
        log.exception("could not create the Anthropic client")
        raise ApiError(503, "The Anthropic client could not be set up on this server.")

    review = Review(settings, llm, content, story, body.brief.model_dump(), market,
                    spend_hook=app.state.spend.add)
    return StreamingResponse(_stream(review), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _stream(review: Review) -> Iterator[bytes]:
    """Run the review on a worker thread; relay its events, with heartbeats."""
    events: "queue.Queue[Optional[Dict]]" = queue.Queue()
    stop = threading.Event()
    review.should_stop = stop.is_set

    def work() -> None:
        try:
            for event in review.events():
                events.put(event)
        except Exception as exc:  # noqa: BLE001 - never let story text reach the log
            log.error("review failed: %s", type(exc).__name__)
            events.put({"type": "error", "message": "Something went wrong during the review. "
                        "Nothing has been kept; please try again."})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    try:
        while True:
            try:
                event = events.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield b'{"type": "tick"}\n'
                continue
            if event is None:
                break
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    finally:
        # The browser went away, or the run finished: stop before the next
        # stage. The story is dropped with the Review when the thread ends.
        stop.set()

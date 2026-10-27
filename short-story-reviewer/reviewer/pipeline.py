"""Run the method's stages in order and assemble the results.

`Review.events()` yields progress events as each stage starts and finishes,
then one final "result" event. The story is held in memory for the length
of the run and is never written to disk or logged.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
from typing import Dict, Iterator, List, Optional

from . import counts as counting
from . import letter as letters
from . import method as methods
from .annotate import AnnotationError, Note, annotate
from .config import Settings
from .cost import usage_cost
from .llm import StageCall, StageError, StageTruncated
from .stages import (ANCHOR_RULES, BY_KEY, DIAGNOSIS_RULE, LAYERED_REGISTERS, REWRITE_RULE, STAGES,
                     SYSTEM_CLOSE, SYSTEM_PREAMBLE, voice_rules)
from .story_io import Story


def system_prompt(method_text: str) -> str:
    return SYSTEM_PREAMBLE + method_text.strip() + SYSTEM_CLOSE


def story_block(story: Story, title: str) -> str:
    safe_title = title.replace('"', "'") if title else "Untitled"
    return f'<story title="{safe_title}">\n{story.text}\n</story>'


def _canon(text: str) -> str:
    text = re.sub(r"[‘’']", "'", text)
    text = re.sub(r"[“”\"]", '"', text)
    text = re.sub(r"—|–|--", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def find_paragraph(paragraphs: List[str], anchor: str) -> Optional[int]:
    needle = _canon(anchor)
    if not needle:
        return None
    for i, para in enumerate(paragraphs):
        if needle in _canon(para):
            return i
    return None


def _take_words(paragraphs: List[str], start: int, step: int, words: int) -> List[int]:
    picked, total, i = [], 0, start
    while 0 <= i < len(paragraphs) and total < words:
        picked.append(i)
        total += len(paragraphs[i].split())
        i += step
    return sorted(picked)


def sample_passages(paragraphs: List[str], scene_map: Dict, words_each: int) -> List[Dict]:
    """Opening, turning point, climax and ending, each about `words_each` words."""
    plan = [("opening", 0, 1), ("ending", len(paragraphs) - 1, -1)]
    for label, key in (("turning point", "turning_point"), ("climax", "climax")):
        idx = find_paragraph(paragraphs, (scene_map.get(key) or {}).get("anchor", ""))
        if idx is not None:
            plan.insert(-1, (label, idx, 1))
    passages, used = [], set()
    for label, start, step in plan:
        idxs = [i for i in _take_words(paragraphs, start, step, words_each) if i not in used]
        if not idxs:
            continue
        used.update(idxs)
        passages.append({"label": label, "text": "\n\n".join(paragraphs[i] for i in idxs)})
    return passages


def model_brief(brief: Dict, story: Story, market: Optional[Dict]) -> Dict:
    return {
        "story_title": brief.get("title") or "Untitled",
        "word_count": story.word_count,
        "length_band": story.band,
        "target_market": market["name"] if market else "none given",
        "draft_stage": brief["draft_stage"],
        "level_of_edit": brief["edit_level"],
        "writer_questions": brief.get("questions") or "none",
        "conventions": brief["conventions"],
        "mode": "diagnosis plus suggested rewrites" if brief["mode"] == "rewrites" else "diagnosis only",
    }


def stage_plan() -> List[str]:
    return [s.key for s in STAGES]


def format_date(conventions: str, today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    if conventions == "US":
        return f"{today:%B} {today.day}, {today.year}"
    return f"{today.day} {today:%B} {today.year}"


class Review:
    def __init__(self, settings: Settings, llm, content: methods.Content, story: Story,
                 brief: Dict, market: Optional[Dict] = None, spend_hook=None):
        self.settings = settings
        self.llm = llm
        self.content = content
        self.story = story
        self.brief = brief
        self.market = market
        self.spend_hook = spend_hook  # called with each stage's actual cost
        self.should_stop = lambda: False  # checked before each stage
        self.outputs: Dict[str, Dict] = {}
        self.spent = 0.0
        self.stage_costs: List[Dict] = []
        self.counts: Optional[Dict] = None
        self.system = system_prompt(content.method)
        self.story_text = story_block(story, brief.get("title", ""))

    # ------------------------------------------------------------ requests

    def _skip_reason(self, key: str) -> Optional[str]:
        design = self.outputs.get("design", {})
        if key == "genre" and not design.get("speculative", {}).get("is_speculative"):
            return "The design statement does not identify the story as speculative fiction."
        if key == "register":
            reg = design.get("register", {})
            if not ({reg.get("primary"), reg.get("secondary")} & LAYERED_REGISTERS):
                return "The story's register is not comic, deadpan or dark."
        return None

    def _data_for(self, key: str) -> List[str]:
        blocks = []
        if key in methods.REPORT_KEYWORDS:
            ref = methods.report_sections(self.content.report, methods.REPORT_KEYWORDS[key])
            if ref:
                blocks.append(f"<report_reference>\n{ref}\n</report_reference>")
        if key == "line":
            self.counts = counting.count_story(self.story.paragraphs)
            blocks.append("<counts>\n" + json.dumps(self.counts, ensure_ascii=False, indent=1) + "\n</counts>")
            if self.story.word_count > self.settings.data["line_pass_sample_over_words"]:
                passages = sample_passages(self.story.paragraphs, self.outputs.get("scene_map", {}),
                                           self.settings.data["line_pass_sample_words"])
                body = "\n\n".join(f'<passage label="{p["label"]}">\n{p["text"]}\n</passage>' for p in passages)
                blocks.append(
                    "<sampled_passages>\nThis story is over "
                    f"{self.settings.data['line_pass_sample_over_words']:,} words, so the line pass covers these "
                    f"passages only.\n{body}\n</sampled_passages>")
        if key == "letter" and self.content.example_letter:
            blocks.append(
                "<example_letter>\nA finished letter for a different story, supplied only as a model of shape, "
                "depth and tone. Do not copy its content or wording.\n"
                f"{self.content.example_letter}\n</example_letter>")
        return blocks

    def request_text(self, key: str) -> str:
        stage = BY_KEY[key]
        earlier = "\n".join(
            f'<stage name="{k}">\n{json.dumps(v, ensure_ascii=False)}\n</stage>' for k, v in self.outputs.items()
        )
        rules = [ANCHOR_RULES]
        rules.append(REWRITE_RULE if (key == "letter" and self.brief["mode"] == "rewrites") else DIAGNOSIS_RULE)
        rules.append(voice_rules(self.brief["conventions"]))
        parts = [
            "<brief>\n" + json.dumps(model_brief(self.brief, self.story, self.market), ensure_ascii=False, indent=1)
            + "\n</brief>",
            f"<earlier_stages>\n{earlier}\n</earlier_stages>" if earlier else "<earlier_stages/>",
            *self._data_for(key),
            f"<stage_to_carry_out>\nCarry out {stage.method_part}, as the method describes it.\n"
            f"{stage.instructions}\n</stage_to_carry_out>",
            "<rules>\n" + "\n\n".join(rules) + "\n</rules>",
        ]
        return "\n\n".join(parts)

    # ------------------------------------------------------------ running

    def _charge(self, key: str, usage_rows: List[Dict]) -> float:
        cost = sum(usage_cost(self.settings, row["model"], row) for row in usage_rows)
        self.spent += cost
        self.stage_costs.append({"stage": key, "usd": round(cost, 4), "usage": usage_rows})
        if self.spend_hook:
            self.spend_hook(cost)
        return cost

    def _run_stage(self, key: str) -> Dict:
        st = self.settings.stage(key)
        call = StageCall(
            model=st.model, effort=st.effort, max_tokens=st.max_tokens,
            system=self.system, story=self.story_text, request=self.request_text(key),
            schema=BY_KEY[key].schema(self.brief),
        )
        try:
            result = self.llm.run(call)
        except StageTruncated as exc:
            self._charge(key, getattr(exc, "usage", []))
            bigger = int(st.max_tokens * self.settings.data["retry_cap_multiplier"])
            worst = bigger * self.settings.price(st.model)["output"] / 1e6
            if self.spent + worst > self.settings.limits["max_run_cost_usd"]:
                raise StageError(
                    f"{BY_KEY[key].title} ran out of output tokens, and retrying would pass the per-run "
                    "spending cap. Raise this stage's max_tokens in the config.") from exc
            call.max_tokens = bigger
            try:
                result = self.llm.run(call)
            except StageTruncated as again:
                self._charge(key, getattr(again, "usage", []))
                raise StageError(
                    f"{BY_KEY[key].title} ran out of output tokens twice. Raise this stage's max_tokens "
                    "in the config.") from again
        self._charge(key, result.usage)
        return result.data

    def events(self) -> Iterator[Dict]:
        try:
            for stage in STAGES:
                if self.should_stop():
                    yield {"type": "error", "message": "The review was cancelled.",
                           "spent_usd": round(self.spent, 4)}
                    return
                reason = self._skip_reason(stage.key)
                if reason:
                    yield {"type": "stage_skipped", "stage": stage.key, "title": stage.title, "reason": reason}
                    continue
                yield {"type": "stage_start", "stage": stage.key, "title": stage.title,
                       "model": self.settings.stage(stage.key).model}
                self.outputs[stage.key] = self._run_stage(stage.key)
                yield {"type": "stage_done", "stage": stage.key, "title": stage.title,
                       "spent_usd": round(self.spent, 4)}
            yield {"type": "assembling"}
            yield self._result()
        except StageError as exc:
            yield {"type": "error", "message": str(exc), "spent_usd": round(self.spent, 4)}

    # ------------------------------------------------------------ results

    def _located_notes(self) -> List[Dict]:
        notes = []
        for n in self.outputs.get("triage", {}).get("margin_notes", []):
            notes.append({"anchor": n["anchor"], "note": n["note"], "kind": n.get("kind", "query")})
        return notes

    def _result(self) -> Dict:
        letter_json = self.outputs["letter"]
        located = self._located_notes()
        title = self.brief.get("title") or (self.story.filename or "Untitled")
        meta = {
            "story_title": title,
            "subtitle": letters.subtitle(title, self.story.word_count, self.story.band, self.brief,
                                         format_date(self.brief["conventions"])),
        }

        warnings: List[str] = []
        annotated_b64 = None
        if self.story.kind == "docx" and self.story.docx_bytes:
            notes = [Note(anchor=n["anchor"], text=n["note"], label=letters.KIND_LABELS.get(n["kind"], ""))
                     for n in located]
            try:
                annotated = annotate(self.story.docx_bytes, notes)
            except AnnotationError as exc:
                warnings.append(f"The annotated manuscript was not produced: {exc}")
                for n in located:
                    n["placed"] = False
            else:
                annotated_b64 = base64.b64encode(annotated.docx_bytes).decode("ascii")
                for n, placement in zip(located, annotated.placements):
                    n["placed"] = placement.placed
                    n["matched"] = placement.matched
        else:
            for n in located:
                n["placed"] = find_paragraph(self.story.paragraphs, n["anchor"]) is not None

        unplaced = [n for n in located if not n.get("placed")]
        if unplaced:
            warnings.append(f"{len(unplaced)} located note(s) quote text that could not be found in the story; "
                            "they are listed with the letter but not placed in the manuscript.")
        if self.brief["mode"] != "rewrites":
            for quote in letters.unsourced_quotes(letter_json, self.story.text):
                warnings.append(f"The letter quotes words that are not in the story: “{quote}”")

        markdown = letters.to_markdown(meta, letter_json, located)
        letter_docx = letters.to_docx(meta, letter_json, located)
        base = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "story"
        files = {
            "letter_md": {"name": f"{base}-editorial-letter.md", "text": markdown},
            "letter_docx": {"name": f"{base}-editorial-letter.docx",
                            "b64": base64.b64encode(letter_docx).decode("ascii")},
        }
        if annotated_b64:
            files["annotated_docx"] = {"name": f"{base}-with-notes.docx", "b64": annotated_b64}

        return {
            "type": "result",
            "letter_html": letters.to_html(meta, letter_json),
            "located_notes": located,
            "warnings": warnings,
            "files": files,
            "counts_summary": counting.summary_lines(self.counts) if self.counts else [],
            "stages_run": list(self.outputs),
            "cost": {"total_usd": round(self.spent, 4), "by_stage": self.stage_costs},
        }

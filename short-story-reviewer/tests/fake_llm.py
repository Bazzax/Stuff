"""A stand-in for the Anthropic client that returns stage-shaped JSON.

Anchors are real quotations taken from the story, so the located-notes and
annotation paths run exactly as they would on a live response.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from reviewer.llm import StageResult, StageTruncated


def stage_of(schema: Dict) -> str:
    props = schema["properties"]
    if "reactions" in props:
        return "cold_read"
    if "design_statement" in props:
        return "design"
    if "scenes" in props:
        return "scene_map"
    if "count_findings" in props:
        return "line"
    if "headline_issues" in props:
        return "triage"
    if "salutation" in props:
        return "letter"
    note_props = props["notes"]["items"]["properties"]
    return "register" if "could_be_the_joke" in note_props else "genre"


class FakeLLM:
    def __init__(self, paragraphs: List[str], register: str = "realist", speculative: bool = False,
                 letter_quote: Optional[str] = None, truncate: Optional[str] = None):
        self.paragraphs = [p for p in paragraphs if len(p.split()) >= 8]
        self.register = register
        self.speculative = speculative
        self.letter_quote = letter_quote
        self.truncate = truncate
        self.calls = []

    def anchor(self, i: int, words: int = 6) -> str:
        para = self.paragraphs[i % len(self.paragraphs)]
        return " ".join(para.split()[1:1 + words]).rstrip(",;:")

    def run(self, call) -> StageResult:
        key = stage_of(call.schema)
        self.calls.append((key, call))
        usage = [{"model": call.model, "input_tokens": 900, "output_tokens": 1200,
                  "cache_read_input_tokens": 0 if len(self.calls) == 1 else 20000,
                  "cache_creation_input_tokens": 20000 if len(self.calls) == 1 else 0}]
        if key == self.truncate:
            self.truncate = None
            err = StageTruncated("out of tokens")
            err.usage = usage
            raise err
        data = getattr(self, "_" + key)(call)
        return StageResult(data=data, model=call.model, usage=usage)

    def _cold_read(self, call):
        return {"reactions": [{"anchor": self.anchor(0), "kind": "engaged", "reaction": "Drawn in."},
                              {"anchor": self.anchor(3), "kind": "curious", "reaction": "Wondering why."}],
                "overall_response": "A confident story."}

    def _design(self, call):
        return {
            "design_statement": "A story built to turn on one revelation.",
            "central_character": "The protagonist", "desire_or_question": "What is real?",
            "intended_effect": "A final twist.", "point_of_view": "third person", "tense": "past",
            "register": {"primary": self.register, "secondary": "none", "evidence_anchor": self.anchor(1)},
            "speculative": {"is_speculative": self.speculative,
                            "kind": "science fiction" if self.speculative else "none",
                            "premise": "", "evidence_anchor": self.anchor(2)},
        }

    def _scene_map(self, call):
        n = len(self.paragraphs)
        return {"scenes": [{"number": 1, "start_anchor": self.anchor(0), "summary": "Opening.", "function": "Set-up."}],
                "turning_point": {"anchor": self.anchor(n // 2), "explanation": "The turn."},
                "climax": {"anchor": self.anchor(n - 3), "explanation": "The climax."},
                "structural_notes": [{"anchor": self.anchor(4), "note": "Pacing slows.", "checklist_ref": "S3"}]}

    def _genre(self, call):
        return {"notes": [{"anchor": self.anchor(5), "note": "The premise is introduced cleanly.",
                           "checklist_ref": "G1"}], "summary": "Sound."}

    def _register(self, call):
        return {"notes": [{"anchor": self.anchor(6), "note": "Is this oddity the joke?", "checklist_ref": "M8",
                           "could_be_the_joke": True}], "summary": "Consistent."}

    def _line(self, call):
        return {"notes": [{"anchor": self.anchor(7), "note": "Speech tag draws attention.",
                           "checklist_ref": "L2", "scope": "instance"}],
                "count_findings": [{"count": "speech verbs", "judgement": "Fine for the period."}],
                "summary": "Clean."}

    def _triage(self, call):
        return {
            "headline_issues": [{"title": "Pacing in the middle", "diagnosis": "It sags.",
                                 "why_it_matters": "The twist needs momentum.",
                                 "evidence_anchors": [self.anchor(4)]}],
            "pattern_notes": [{"note": "Long sentences cluster.", "anchors": [self.anchor(8)]}],
            "taste_notes": [], "strengths": [{"note": "Strong voice.", "anchor": self.anchor(0)}],
            "margin_notes": [
                {"anchor": self.anchor(0), "kind": "strength", "note": "This opening line works."},
                {"anchor": self.anchor(4), "kind": "headline", "note": "Pacing slows here."},
                {"anchor": "zebra quantum marmalade xylophone", "kind": "query", "note": "Lost note."},
            ],
        }

    def _letter(self, call):
        quote = self.letter_quote or self.anchor(0)
        letter = {"salutation": "Dear writer,",
                  "sections": [{"heading": "What the story is doing",
                                "paragraphs": [f"The line “{quote}” sets the tone."]},
                               {"heading": "The main issues", "paragraphs": ["Pacing in the middle."]}],
                  "sign_off": "With best wishes,"}
        if "suggestions" in call.schema["properties"]:
            letter["suggestions"] = [{"anchor": self.anchor(4), "suggestion": "Cut the second clause.",
                                      "reason": "Momentum."}]
        return letter


def words_in(text: str) -> int:
    return len(re.findall(r"\w+", text))

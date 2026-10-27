"""Deterministic counts passed to the line pass as data.

Code counts; the model judges. Nothing here decides that a hit is an error:
a lower-case word after a comma and an opening quote is often a continued
sentence, a present-tense sentence in a past-tense story is often a general
truth. Every list carries short exact quotations so the model can check them.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from typing import Dict, List, Tuple

MAX_EXAMPLES = 8
SNIPPET = 90

SPEECH_VERBS = {
    "added", "admitted", "agreed", "announced", "answered", "argued", "asked",
    "barked", "begged", "bellowed", "blurted", "boomed", "breathed", "called",
    "chuckled", "commanded", "complained", "continued", "cried", "croaked",
    "declared", "demanded", "drawled", "echoed", "exclaimed", "explained",
    "gasped", "giggled", "groaned", "growled", "grumbled", "grunted", "hissed",
    "howled", "inquired", "enquired", "insisted", "interrupted", "joked",
    "laughed", "lied", "moaned", "mumbled", "murmured", "muttered", "noted",
    "observed", "offered", "ordered", "pleaded", "pressed", "promised",
    "protested", "purred", "queried", "quipped", "remarked", "repeated",
    "replied", "responded", "retorted", "roared", "sang", "scoffed",
    "screamed", "shouted", "shrieked", "sighed", "smiled", "snapped",
    "snarled", "sneered", "sobbed", "spat", "sputtered", "stammered",
    "stated", "stuttered", "suggested", "teased", "thundered", "urged",
    "volunteered", "wailed", "warned", "whimpered", "whined", "whispered",
    "yelled",
}

FILTER_VERBS = {
    "felt": "feel", "feel": "feel", "feels": "feel", "feeling": "feel",
    "sensed": "sense", "sense": "sense", "senses": "sense", "sensing": "sense",
    "realised": "realise", "realise": "realise", "realises": "realise", "realising": "realise",
    "realized": "realise", "realize": "realise", "realizes": "realise", "realizing": "realise",
    "noticed": "notice", "notice": "notice", "notices": "notice", "noticing": "notice",
}

PRESENT_MARKERS = {
    "is", "are", "am", "has", "does", "says", "seems", "looks", "goes", "comes",
    "knows", "thinks", "wants", "sees", "stands", "sits", "turns", "walks", "lies",
}
PAST_MARKERS = {
    "was", "were", "had", "did", "said", "seemed", "looked", "went", "came",
    "knew", "thought", "wanted", "saw", "stood", "sat", "turned", "walked", "lay",
}
PAST_ED = re.compile(r"^[a-z]{3,}ed$")

HONORIFICS = ("Mr", "Mrs", "Ms", "Dr", "St")

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def _snippet(text: str, start: int, end: int) -> str:
    """A short exact quotation around text[start:end], trimmed to whole words."""
    pad = max(0, (SNIPPET - (end - start)) // 2)
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    if a > 0:
        space = text.find(" ", a, start)
        a = space + 1 if space != -1 else a
    if b < len(text):
        space = text.rfind(" ", end, b)
        b = space if space != -1 else b
    return text[a:b].strip()


def detect_speech_style(text: str) -> str:
    doubles = text.count("“") + text.count("”") + text.count('"')
    singles_open = len(re.findall(r"(?:^|[\s(\[—])‘", text))
    if doubles >= 2 and doubles >= singles_open:
        return "double"
    if singles_open >= 2:
        return "single"
    return "none"


def speech_spans(paragraph: str, style: str) -> List[Tuple[int, int]]:
    """(start, end) spans of quoted speech in one paragraph, quotes included.

    Speech left open at the end of a paragraph closes there; the next
    paragraph of a long speech opens its own quotation.
    """
    spans = []
    if style == "double":
        start = None
        for i, ch in enumerate(paragraph):
            if ch == "“" or (ch == '"' and start is None):
                if start is None:
                    start = i
            elif ch == "”" or ch == '"':
                if start is not None:
                    spans.append((start, i + 1))
                    start = None
        if start is not None:
            spans.append((start, len(paragraph)))
    elif style == "single":
        start = None
        for i, ch in enumerate(paragraph):
            prev = paragraph[i - 1] if i else " "
            nxt = paragraph[i + 1] if i + 1 < len(paragraph) else " "
            if ch == "‘" and start is None and not prev.isalnum():
                start = i
            elif ch == "’" and start is not None and not nxt.isalnum():
                spans.append((start, i + 1))
                start = None
        if start is not None:
            spans.append((start, len(paragraph)))
    return spans


def _narration_mask(paragraph: str, spans: List[Tuple[int, int]]) -> str:
    """The paragraph with speech blanked out, same length, for position-safe searches."""
    chars = list(paragraph)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def _sentences(text: str) -> List[Tuple[int, int]]:
    out = []
    start = 0
    for m in re.finditer(r"[.!?…]+[\"'”’)]*\s+", text):
        out.append((start, m.end()))
        start = m.end()
    if start < len(text):
        out.append((start, len(text)))
    return out


class _Bucket:
    def __init__(self) -> None:
        self.count = 0
        self.examples: List[str] = []

    def hit(self, text: str, start: int, end: int) -> None:
        self.count += 1
        if len(self.examples) < MAX_EXAMPLES:
            snip = _snippet(text, start, end)
            if snip not in self.examples:
                self.examples.append(snip)

    def as_dict(self) -> Dict:
        return {"count": self.count, "examples": self.examples}


def _name_variants(paragraphs: List[str]) -> List[Dict]:
    names: Counter = Counter()
    for para in paragraphs:
        for m in re.finditer(r"(?<=[a-z,;] )([A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)?)", para):
            word = re.sub(r"['’]s$", "", m.group(1))
            names[word] += 1
    candidates = [n for n, c in names.items() if len(n) >= 4]
    variants = []
    seen = set()
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if a.lower() == b.lower() or a.rstrip("s") == b.rstrip("s"):
                continue
            if difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() < 0.8:
                continue
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            variants.append({"forms": {a: names[a], b: names[b]}})
    return variants[:MAX_EXAMPLES]


def _hyphenation_variants(text: str) -> List[Dict]:
    hyphenated = Counter(m.group(0).lower() for m in re.finditer(r"\b[a-zA-Z]+-[a-zA-Z]+\b", text))
    words = Counter(w.lower() for w in re.findall(r"\b[a-zA-Z]+\b", text))
    out = []
    for form, n in hyphenated.items():
        closed = form.replace("-", "")
        if words.get(closed):
            out.append({"forms": {form: n, closed: words[closed]}})
    return out[:MAX_EXAMPLES]


def count_story(paragraphs: List[str]) -> Dict:
    text = "\n\n".join(paragraphs)
    style = detect_speech_style(text)

    lower_after = _Bucket()
    other_verbs: Counter = Counter()
    verb_examples: List[str] = []
    said = 0
    excl = _Bucket()
    ellipses_speech = _Bucket()
    ellipses_narr = _Bucket()
    filter_hits: Counter = Counter()
    filter_bucket = _Bucket()
    past_total = present_total = 0
    narration_sentences: List[Tuple[str, int, int, int, int]] = []

    for para in paragraphs:
        spans = speech_spans(para, style)
        narr = _narration_mask(para, spans)

        # An opening quotation mark preceded by a comma or colon, whose
        # speech starts with a lower-case letter.
        for a, b in spans:
            if not para[:a].rstrip().endswith((",", ":")):
                continue
            first = re.search(r"[A-Za-z]", para[a:b])
            if first and first.group(0).islower():
                lower_after.hit(para, a, a + first.end())

        # Speech tags: narration within a few words of a quotation.
        for a, b in spans:
            before = narr[max(0, a - 40):a]
            after = narr[b:b + 40]
            for chunk, offset in ((before, max(0, a - 40)), (after, b)):
                for m in re.finditer(r"[A-Za-z]+", chunk):
                    w = m.group(0).lower()
                    if w == "said":
                        said += 1
                    elif w in SPEECH_VERBS:
                        other_verbs[w] += 1
                        if len(verb_examples) < MAX_EXAMPLES:
                            snip = _snippet(para, offset + m.start(), offset + m.end())
                            if snip not in verb_examples:
                                verb_examples.append(snip)

        for m in re.finditer(r"!", narr):
            excl.hit(para, m.start(), m.end())

        for m in re.finditer(r"\.\s?\.\s?\.|…", para):
            inside = any(a <= m.start() < b for a, b in spans)
            (ellipses_speech if inside else ellipses_narr).hit(para, m.start(), m.end())

        for m in re.finditer(r"[A-Za-z]+", narr):
            lemma = FILTER_VERBS.get(m.group(0).lower())
            if lemma:
                filter_hits[lemma] += 1
                filter_bucket.hit(para, m.start(), m.end())

        for s, e in _sentences(narr):
            words = [w.lower() for w in re.findall(r"[A-Za-z]+", narr[s:e])]
            if len(words) < 3:
                continue
            past = sum(1 for w in words if w in PAST_MARKERS or PAST_ED.match(w))
            present = sum(1 for w in words if w in PRESENT_MARKERS)
            past_total += past
            present_total += present
            narration_sentences.append((para, s, e, past, present))

    dominant = "past" if past_total >= present_total else "present"
    shifts = _Bucket()
    for para, s, e, past, present in narration_sentences:
        odd = present if dominant == "past" else past
        main = past if dominant == "past" else present
        if odd and not main:
            shifts.hit(para, s, e)

    honorifics = {}
    for h in HONORIFICS:
        with_stop = len(re.findall(r"\b%s\.\s" % h, text))
        without = len(re.findall(r"\b%s\s+[A-Z]" % h, text))
        if with_stop or without:
            honorifics[h] = {"with full stop": with_stop, "without": without}

    quotes = {
        "straight_double": text.count('"'),
        "curly_double": text.count("“") + text.count("”"),
        "straight_single": text.count("'"),
        "curly_single": text.count("‘") + text.count("’"),
    }
    quotes["mixed"] = bool(
        (quotes["straight_double"] and quotes["curly_double"])
        or (quotes["straight_single"] and quotes["curly_single"])
    )

    return {
        "speech_quotation_style": style,
        "speech_opened_lower_case_after_comma_or_colon": lower_after.as_dict(),
        "speech_verbs": {
            "said": said,
            "other": dict(other_verbs.most_common()),
            "examples": verb_examples,
        },
        "exclamation_marks_outside_speech": excl.as_dict(),
        "ellipses": {
            "in_speech": ellipses_speech.as_dict(),
            "in_narration": ellipses_narr.as_dict(),
        },
        "filter_verbs": {
            "total": sum(filter_hits.values()),
            "by_verb": dict(filter_hits.most_common()),
            "examples": filter_bucket.examples,
        },
        "name_variants": _name_variants(paragraphs),
        "honorifics": honorifics,
        "hyphenation_variants": _hyphenation_variants(text),
        "quotation_marks": quotes,
        "tense": {
            "dominant_in_narration": dominant,
            "past_markers": past_total,
            "present_markers": present_total,
            "candidate_shifts": shifts.as_dict(),
        },
    }


def summary_lines(counts: Dict) -> List[str]:
    """A few human-readable lines for the results page."""
    sv = counts["speech_verbs"]
    other = sum(sv["other"].values())
    q = counts["quotation_marks"]
    return [
        f"Speech opened in lower case after a comma or colon: "
        f"{counts['speech_opened_lower_case_after_comma_or_colon']['count']}",
        f"Speech verbs: said {sv['said']}, others {other}",
        f"Exclamation marks outside speech: {counts['exclamation_marks_outside_speech']['count']}",
        f"Ellipses: {counts['ellipses']['in_speech']['count']} in speech, "
        f"{counts['ellipses']['in_narration']['count']} in narration",
        f"Filter verbs (felt, sensed, realised, noticed): {counts['filter_verbs']['total']}",
        f"Possible name variants: {len(counts['name_variants'])}",
        "Quotation marks: " + ("mixed straight and curly" if q["mixed"] else "consistent"),
        f"Candidate tense shifts: {counts['tense']['candidate_shifts']['count']}",
    ]

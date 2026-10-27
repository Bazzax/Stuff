"""Cost accounting and the estimate shown before a run.

Estimates use a characters-per-token ratio rather than a tokenizer call, and
err high: the newer Claude tokenizer can use up to about 1.35 times as many
tokens as older rules of thumb suggest.
"""
from __future__ import annotations

from typing import Dict, List

from .config import Settings

CHARS_PER_TOKEN = 3.3
# Fixed instruction text sent with every stage (rules, schema, brief).
STAGE_OVERHEAD_TOKENS = 1_800
# Expected share of each stage's output cap actually used: longer stories
# produce more reactions, scenes and notes. These are planning figures; the
# real cost of every run is reported from the API's usage counts.
MIN_OUTPUT_SHARE = 0.3
MAX_OUTPUT_SHARE = 0.5
FULL_LENGTH_WORDS = 15_000


def expected_output_share(words: int) -> float:
    return MIN_OUTPUT_SHARE + (MAX_OUTPUT_SHARE - MIN_OUTPUT_SHARE) * min(1.0, words / FULL_LENGTH_WORDS)


def tokens_for(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def usage_cost(settings: Settings, model: str, usage: Dict) -> float:
    p = settings.price(model)
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
    ) / 1_000_000


def estimate(
    settings: Settings,
    stage_keys: List[str],
    story_text: str,
    method_text: str,
    report_tokens: Dict[str, int],
) -> Dict:
    """Expected and worst-case cost of a run, stage by stage.

    The method and story form a cached prefix: the first stage on each model
    writes the cache, later stages on that model read it. Earlier stages'
    outputs are re-sent uncached to later stages.
    """
    prefix = tokens_for(method_text) + tokens_for(story_text)
    share = expected_output_share(len(story_text.split()))
    warmed = set()
    carried_expected = 0
    carried_max = 0
    rows = []
    for key in stage_keys:
        st = settings.stage(key)
        p = settings.price(st.model)
        cache_cost = prefix * (p["cache_read"] if st.model in warmed else p["cache_write"])
        warmed.add(st.model)
        fresh = STAGE_OVERHEAD_TOKENS + report_tokens.get(key, 0)
        out_expected = int(st.max_tokens * share)
        expected = (cache_cost + (fresh + carried_expected) * p["input"] + out_expected * p["output"]) / 1e6
        worst = (cache_cost + (fresh + carried_max) * p["input"] + st.max_tokens * p["output"]) / 1e6
        rows.append({
            "stage": key,
            "model": st.model,
            "max_output_tokens": st.max_tokens,
            "expected_usd": round(expected, 4),
            "max_usd": round(worst, 4),
        })
        # Thinking is not carried forward; roughly a third of output is the JSON itself.
        carried_expected += out_expected // 3
        carried_max += st.max_tokens // 3
    return {
        "stages": rows,
        "prefix_tokens": prefix,
        "expected_usd": round(sum(r["expected_usd"] for r in rows), 2),
        "max_usd": round(sum(r["max_usd"] for r in rows), 2),
    }

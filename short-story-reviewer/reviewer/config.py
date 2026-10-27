"""Settings: models per stage, output caps, prices and limits.

Defaults live here. Override any of them with a JSON file named in the
SSR_CONFIG environment variable, shaped like `defaults()` below, e.g.

    {"stages": {"letter": {"model": "claude-sonnet-5-5"}},
     "limits": {"max_run_cost_usd": 1.5}}

The Anthropic API key is never part of this; the SDK reads ANTHROPIC_API_KEY
from the server's environment.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

PROJECT_DIR = Path(__file__).resolve().parent.parent

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"

# USD per million tokens, October 2026. Cache writes (5-minute TTL) cost
# 1.25x input. The build brief lists Sonnet 5.5 cache reads at $0.10; the
# API reference current at build time lists $0.20, so $0.20 is used here.
DEFAULT_PRICES = {
    OPUS: {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    SONNET: {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    # Server-side fallback targets, priced so a fallback hop is never under-counted.
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}


def defaults() -> Dict:
    return {
        "stages": {
            # max_tokens caps thinking plus the JSON answer. A stage that hits
            # its cap is retried once (see retry_cap_multiplier).
            "cold_read": {"model": SONNET, "effort": "medium", "max_tokens": 6_000},
            "design": {"model": SONNET, "effort": "medium", "max_tokens": 3_000},
            "scene_map": {"model": SONNET, "effort": "medium", "max_tokens": 6_000},
            "genre": {"model": SONNET, "effort": "medium", "max_tokens": 5_000},
            "register": {"model": SONNET, "effort": "medium", "max_tokens": 5_000},
            "line": {"model": SONNET, "effort": "medium", "max_tokens": 10_000},
            "triage": {"model": OPUS, "effort": "medium", "max_tokens": 8_000},
            "letter": {"model": OPUS, "effort": "medium", "max_tokens": 12_000},
        },
        "prices": copy.deepcopy(DEFAULT_PRICES),
        "limits": {
            # Refuse a run whose worst-case estimate exceeds this.
            "max_run_cost_usd": 2.00,
            # Refuse new runs once the server has spent this much today (UTC).
            "daily_spend_cap_usd": 20.00,
            "runs_per_hour_per_ip": 4,
            "requests_per_minute_per_ip": 30,
        },
        # A stage that hits its output cap is retried once with this multiple
        # of the cap, if the run stays within max_run_cost_usd.
        "retry_cap_multiplier": 1.5,
        # Stories longer than this get a sampled line pass.
        "line_pass_sample_over_words": 5_000,
        "line_pass_sample_words": 450,
    }


@dataclass
class StageSettings:
    model: str
    effort: str
    max_tokens: int


def _merge(base: Dict, override: Dict) -> Dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


class Settings:
    def __init__(self, data: Dict):
        self.data = data

    @classmethod
    def load(cls) -> "Settings":
        data = defaults()
        path = os.environ.get("SSR_CONFIG")
        if path:
            _merge(data, json.loads(Path(path).read_text(encoding="utf-8")))
        env_limits = {
            "SSR_MAX_RUN_COST_USD": "max_run_cost_usd",
            "SSR_DAILY_SPEND_CAP_USD": "daily_spend_cap_usd",
            "SSR_RUNS_PER_HOUR_PER_IP": "runs_per_hour_per_ip",
        }
        for env, key in env_limits.items():
            if os.environ.get(env):
                data["limits"][key] = float(os.environ[env])
        return cls(data)

    def stage(self, key: str) -> StageSettings:
        s = self.data["stages"][key]
        return StageSettings(model=s["model"], effort=s["effort"], max_tokens=int(s["max_tokens"]))

    def price(self, model: str) -> Dict[str, float]:
        prices = self.data["prices"]
        if model in prices:
            return prices[model]
        # Unknown model: charge at the dearest known rate so estimates stay safe.
        return max(prices.values(), key=lambda p: p["output"])

    @property
    def limits(self) -> Dict:
        return self.data["limits"]

    @property
    def content_dir(self) -> Path:
        return Path(os.environ.get("SSR_CONTENT_DIR", PROJECT_DIR / "content"))

    @property
    def markets_file(self) -> Path:
        return Path(os.environ.get("SSR_MARKETS_FILE", PROJECT_DIR / "data" / "markets.json"))

    @property
    def access_code(self) -> str:
        return os.environ.get("SSR_ACCESS_CODE", "")

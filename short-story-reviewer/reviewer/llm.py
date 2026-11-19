"""One stage, one model call.

Request shape, chosen for cost:

    system   = preamble + method          (cache breakpoint)
    user[0]  = the story                   (cache breakpoint)
    user[1]  = brief, earlier outputs, data and this stage's instructions

The method and story are identical across stages, so after the first call
on each model they are read from the prompt cache. Effort is pinned per
stage in config, because changing effort between requests on one model
invalidates the messages cache.

Server-side refusal fallback (`fallbacks="default"`) is on: if a model's
safety classifier declines a request, the API retries it on Anthropic's
recommended fallback model inside the same call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class StageError(RuntimeError):
    """A stage call failed in a way the writer should be told about."""


class StageTruncated(StageError):
    """The stage ran out of output tokens before finishing its JSON."""


@dataclass
class StageCall:
    model: str
    effort: str
    max_tokens: int
    system: str
    story: str
    request: str
    schema: Dict


@dataclass
class StageResult:
    data: Dict
    model: str
    # One entry per model that ran (more than one only after a fallback).
    usage: List[Dict] = field(default_factory=list)


def _usage_dict(u, model: str) -> Dict:
    return {
        "model": getattr(u, "model", None) or model,
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


class AnthropicLLM:
    """The real client. The API key comes from ANTHROPIC_API_KEY on the server."""

    def __init__(self, api_key: Optional[str] = None):
        import anthropic  # imported here so the rest of the app works without it

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)

    def run(self, call: StageCall) -> StageResult:
        anthropic = self._anthropic
        try:
            with self.client.beta.messages.stream(
                model=call.model,
                max_tokens=call.max_tokens,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=[{"type": "text", "text": call.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": call.story, "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": call.request},
                    ],
                }],
                output_config={
                    "effort": call.effort,
                    "format": {"type": "json_schema", "schema": call.schema},
                },
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise StageError("The server's Anthropic API key was rejected.") from exc
        except anthropic.RateLimitError as exc:
            raise StageError("The Anthropic API is rate-limiting this server. Try again in a minute.") from exc
        except anthropic.BadRequestError as exc:
            raise StageError(f"The Anthropic API rejected the request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise StageError(f"The Anthropic API returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise StageError("Could not reach the Anthropic API.") from exc

        usage = message.usage
        iterations = getattr(usage, "iterations", None) or []
        if iterations:
            usage_rows = [_usage_dict(it, message.model) for it in iterations]
        else:
            usage_rows = [_usage_dict(usage, message.model)]

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise StageError(
                "The model declined this stage" + (f" ({category})." if category else ".")
            )
        if message.stop_reason == "max_tokens":
            err = StageTruncated("The stage reached its output cap before finishing.")
            err.usage = usage_rows  # type: ignore[attr-defined]
            raise err

        # After a fallback, text from the declined model precedes the fallback
        # block; only the text after the last fallback block is the answer.
        parts: List[str] = []
        for block in message.content:
            if block.type == "fallback":
                parts = []
            elif block.type == "text":
                parts.append(block.text)
        try:
            data = json.loads("".join(parts))
        except json.JSONDecodeError as exc:
            raise StageError("The model's answer for this stage was not valid JSON.") from exc
        return StageResult(data=data, model=message.model, usage=usage_rows)

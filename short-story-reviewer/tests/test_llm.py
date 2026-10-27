"""The real Anthropic client, driven against a mock HTTP transport.

Checks that the SDK accepts the request this app builds (fallbacks, cache
markers, structured output, effort) and that streamed answers, refusals,
truncation and fallback hops are handled.
"""
import json

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from reviewer.llm import AnthropicLLM, StageCall, StageError, StageTruncated  # noqa: E402

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"],
          "additionalProperties": False}


def sse(content_blocks, stop_reason="end_turn", usage=None, model="claude-sonnet-5-5"):
    usage = usage or {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 5,
                      "cache_creation_input_tokens": 7}
    events = [("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": usage["input_tokens"], "output_tokens": 1}}})]
    for i, block in enumerate(content_blocks):
        if block["type"] == "text":
            events.append(("content_block_start", {"type": "content_block_start", "index": i,
                                                   "content_block": {"type": "text", "text": ""}}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "text_delta", "text": block["text"]}}))
        else:
            events.append(("content_block_start", {"type": "content_block_start", "index": i,
                                                   "content_block": block}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events.append(("message_delta", {"type": "message_delta",
                                     "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                     "usage": usage}))
    events.append(("message_stop", {"type": "message_stop"}))
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


def make_llm(body: str, seen: list):
    def handler(request):
        seen.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    llm = AnthropicLLM(api_key="test-key")
    llm.client = anthropic.Anthropic(
        api_key="test-key", max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return llm


def call():
    return StageCall(model="claude-sonnet-5-5", effort="medium", max_tokens=1000,
                     system="METHOD", story="<story>S</story>", request="REQUEST", schema=SCHEMA)


def test_request_shape_and_parsed_answer():
    seen = []
    llm = make_llm(sse([{"type": "text", "text": '{"x": "ok"}'}]), seen)
    result = llm.run(call())
    assert result.data == {"x": "ok"}
    assert result.usage[0]["cache_read_input_tokens"] == 5
    assert result.usage[0]["cache_creation_input_tokens"] == 7

    req = seen[0]
    body = json.loads(req.content)
    assert "server-side-fallback-2026-07-01" in req.headers["anthropic-beta"]
    assert body["fallbacks"] == "default"
    assert body["stream"] is True
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in body["messages"][0]["content"][1]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in body  # adaptive by default on these models
    assert "test-key" in (req.headers.get("x-api-key", "") + req.headers.get("authorization", ""))


def test_text_after_a_fallback_block_is_the_answer():
    blocks = [
        {"type": "text", "text": '{"x": "partial'},
        {"type": "fallback", "from": {"model": "claude-sonnet-5-5"}, "to": {"model": "claude-sonnet-5"},
         "trigger": {"type": "refusal"}},
        {"type": "text", "text": '{"x": "rescued"}'},
    ]
    llm = make_llm(sse(blocks), [])
    assert llm.run(call()).data == {"x": "rescued"}


def test_refusal_raises():
    llm = make_llm(sse([], stop_reason="refusal"), [])
    with pytest.raises(StageError, match="declined"):
        llm.run(call())


def test_max_tokens_raises_truncated_with_usage():
    llm = make_llm(sse([{"type": "text", "text": '{"x": "cut'}], stop_reason="max_tokens"), [])
    with pytest.raises(StageTruncated) as info:
        llm.run(call())
    assert info.value.usage[0]["output_tokens"] == 20


def test_http_errors_become_stage_errors():
    def handler(request):
        error = {"type": "authentication_error", "message": "bad key"}
        return httpx2.Response(401, json={"type": "error", "error": error})

    llm = AnthropicLLM(api_key="test-key")
    llm.client = anthropic.Anthropic(api_key="test-key", max_retries=0,
                                     http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    with pytest.raises(StageError, match="API key was rejected"):
        llm.run(call())

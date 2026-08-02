import json

import pytest

from src.agents.finance.realm26_capability_llm import (
    CapabilityProviderError,
    build_capability_request_body,
    call_capability_model,
)
from src.agents.finance.realm26_capability_methods import (
    CAPABILITY_ANSWER_CONTRACT,
    CAPABILITY_REACT_PROMPT,
    CAPABILITY_STATIC_PROMPT,
    PROMPT_UTF8_BYTE_LIMIT,
    _bounded_fit_prompt,
    parse_capability_action,
)


MODELS = (
    "openai/gpt-4o-mini",
    "openai/gpt-5.6-luna",
    "openai/gpt-5.6-terra",
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _normalized_body(model):
    body = build_capability_request_body(
        prompt="synthetic", requested_model=model, max_tokens=384,
        action_schema="react", seed=20260802, stop=[],
    )
    body["model"] = "<MODEL>"
    body.pop("reasoning_effort", None)
    return body


def test_request_bodies_are_model_independent_except_authorized_reasoning_omission():
    assert _normalized_body(MODELS[0]) == _normalized_body(MODELS[1]) == _normalized_body(MODELS[2])
    control = build_capability_request_body(
        prompt="synthetic", requested_model=MODELS[0], max_tokens=384,
        action_schema="finish", seed=20260802,
    )
    luna = build_capability_request_body(
        prompt="synthetic", requested_model=MODELS[1], max_tokens=384,
        action_schema="finish", seed=20260802,
    )
    assert "reasoning_effort" not in control
    assert luna["reasoning_effort"] == "none"
    assert "response_format" not in control
    assert control["tool_choice"]["function"]["name"] == "realm_action"
    assert len(control["tools"]) == 1
    schema = control["tools"][0]["function"]["parameters"]
    assert set(schema["properties"]) == {"action", "argument", "answer"}
    assert schema["additionalProperties"] is False
    assert "thought" not in json.dumps(control).lower()
    assert "1024" in schema["properties"]["argument"]["description"]
    assert "1024" in schema["properties"]["answer"]["description"]
    assert schema["properties"]["argument"]["enum"] == [""]
    search = build_capability_request_body(
        prompt="synthetic", requested_model=MODELS[0], max_tokens=384,
        action_schema="search", seed=20260802,
    )
    assert search["tools"][0]["function"]["parameters"]["properties"]["answer"]["enum"] == [""]


@pytest.mark.parametrize("schema,valid", [
    ("finish", '{"action":"Finish","argument":"","answer":"7"}'),
    ("search", '{"action":"Search","argument":"revenue","answer":""}'),
    ("react", '{"action":"Lookup","argument":"margin","answer":""}'),
])
def test_compact_parser_accepts_exactly_one_schema_valid_object(schema, valid):
    assert parse_capability_action(valid, action_schema=schema)["parse_status"] == "ok"
    for suffix in (" trailing", "\n{}", "\n" + valid):
        assert parse_capability_action(valid + suffix, action_schema=schema)["parse_status"] == "malformed_fallback"


def test_compact_parser_rejects_extra_fields_wrong_field_use_and_length():
    malformed = [
        '{"thought":"x","action":"Finish","argument":"","answer":"7"}',
        '{"action":"Finish","argument":"query","answer":"7"}',
        '{"action":"Search","argument":"query","answer":"7"}',
        json.dumps({"action": "Search", "argument": "x" * 1025, "answer": ""}),
        json.dumps({"action": "Finish", "argument": "", "answer": "x" * 1025}),
    ]
    assert all(parse_capability_action(row)["parse_status"] == "malformed_fallback" for row in malformed)
    assert parse_capability_action(malformed[2])["parse_error"] == "retrieval_field_semantics"
    assert "thought" not in CAPABILITY_ANSWER_CONTRACT.lower()
    assert "thought" not in CAPABILITY_STATIC_PROMPT.lower()
    assert "thought" not in CAPABILITY_REACT_PROMPT.lower()


def test_prompt_byte_ceiling_fails_closed_or_returns_at_most_8192_bytes():
    def fake_fit(*, context_word_budget, evidence, **_):
        prompt = "fixed " + " ".join(evidence.split()[:context_word_budget])
        return prompt, evidence, ""

    prompt, _, _ = _bounded_fit_prompt(
        fake_fit, context_word_budget=4096, evidence=("évidence " * 4096)
    )
    assert len(prompt.encode("utf-8")) <= PROMPT_UTF8_BYTE_LIMIT


def _tool_call(arguments, *, name="realm_action"):
    return {
        "id": "call_synthetic",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _provider_payload(arguments, *, finish_reason="tool_calls", content=None, tool_calls=None):
    return {
        "model": MODELS[0], "provider": "OpenAI",
        "choices": [{
            "finish_reason": finish_reason,
            "message": {
                "content": content,
                "tool_calls": [_tool_call(arguments)] if tool_calls is None else tool_calls,
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "cost": 0.00001},
    }


@pytest.mark.parametrize("finish_reason", [None, "stop", "length", "content_filter"])
def test_provider_rejects_non_tool_finish_reasons(monkeypatch, finish_reason):
    arguments = '{"action":"Finish","argument":"","answer":"7"}'
    payload = _provider_payload(arguments, finish_reason=finish_reason)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.post", lambda *_, **__: FakeResponse(payload))
    with pytest.raises(CapabilityProviderError, match="finish reason"):
        call_capability_model(
            prompt="synthetic", requested_model=MODELS[0], canonical_slug=MODELS[0],
            max_tokens=384, action_schema="finish", seed=20260802,
        )


def test_provider_accepts_exactly_one_strict_action_tool(monkeypatch):
    arguments = '{"action":"Finish","argument":"","answer":"7"}'
    payload = _provider_payload(arguments)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.post", lambda *_, **__: FakeResponse(payload))
    response = call_capability_model(
        prompt="synthetic", requested_model=MODELS[0], canonical_slug=MODELS[0],
        max_tokens=384, action_schema="finish", seed=20260802,
    )
    assert response.result.text == arguments
    assert response.finish_reason == "tool_calls"
    assert response.request_parameters["action_transport"] == "strict_single_function_tool"


@pytest.mark.parametrize("payload,error", [
    (
        _provider_payload(
            '{"action":"Finish","argument":"","answer":"7"}',
            tool_calls=[
                _tool_call('{"action":"Finish","argument":"","answer":"7"}'),
                _tool_call('{"action":"Finish","argument":"","answer":"8"}'),
            ],
        ),
        "multiple action tools",
    ),
    (
        _provider_payload(
            '{"action":"Finish","argument":"","answer":"7"}',
            content="extra text",
        ),
        "text beside",
    ),
    (
        _provider_payload('{"action":"Finish","argument":"","answer":"7"}\n{}'),
        "not_exactly_one_json_value",
    ),
])
def test_provider_rejects_extra_tool_or_content_or_argument_object(monkeypatch, payload, error):
    payload = {
        **payload,
    }
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.post", lambda *_, **__: FakeResponse(payload))
    with pytest.raises(CapabilityProviderError, match=error):
        call_capability_model(
            prompt="synthetic", requested_model=MODELS[0], canonical_slug=MODELS[0],
            max_tokens=384, action_schema="finish", seed=20260802,
        )

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
    schema = control["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]) == {"action", "argument", "answer"}
    assert schema["additionalProperties"] is False
    assert "thought" not in json.dumps(control).lower()
    assert "256" in schema["properties"]["argument"]["description"]
    assert "256" in schema["properties"]["answer"]["description"]


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
        json.dumps({"action": "Search", "argument": "x" * 257, "answer": ""}),
        json.dumps({"action": "Finish", "argument": "", "answer": "x" * 257}),
    ]
    assert all(parse_capability_action(row)["parse_status"] == "malformed_fallback" for row in malformed)
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


@pytest.mark.parametrize("finish_reason", [None, "length", "content_filter", "tool_calls"])
def test_provider_rejects_nonstop_finish_reasons(monkeypatch, finish_reason):
    payload = {
        "model": MODELS[0], "provider": "OpenAI",
        "choices": [{
            "finish_reason": finish_reason,
            "message": {"content": '{"action":"Finish","argument":"","answer":"7"}'},
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "cost": 0.00001},
    }
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("src.agents.finance.realm26_capability_llm.requests.post", lambda *_, **__: FakeResponse(payload))
    with pytest.raises(CapabilityProviderError, match="finish reason"):
        call_capability_model(
            prompt="synthetic", requested_model=MODELS[0], canonical_slug=MODELS[0],
            max_tokens=384, action_schema="finish", seed=20260802,
        )

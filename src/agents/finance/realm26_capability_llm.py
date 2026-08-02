"""Exact OpenRouter binding for the frozen REALM capability tiers.

The request builder is deliberately model-independent.  The sole prospective
exception is that GPT-4o-mini omits an unsupported reasoning parameter while
Luna and Terra explicitly send ``reasoning_effort=none``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import requests

from src.shared.llm_telemetry import LLMResult, parse_openrouter_usage

from .protocol_v2 import ProtocolError


CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_SEED = 20260802
ARGUMENT_MAX_LENGTH = 256
ANSWER_MAX_LENGTH = 256

_ACTIONS = {
    "finish": ["Finish"],
    "search": ["Search"],
    "react": ["Search", "Lookup", "Finish"],
}
_REASONING_OMISSION_MODELS = frozenset({
    "openai/gpt-4o-mini",
    "openai/gpt-4o-mini-2024-07-18",
})
_REASONING_NONE_MODELS = frozenset({
    "openai/gpt-5.6-luna",
    "openai/gpt-5.6-terra",
})
_CANONICAL_SLUGS = {
    "openai/gpt-4o-mini": "openai/gpt-4o-mini",
    "openai/gpt-5.6-luna": "openai/gpt-5.6-luna-20260709",
    "openai/gpt-5.6-terra": "openai/gpt-5.6-terra-20260709",
}


class CapabilityProviderError(ProtocolError):
    """A frozen model, provider, request, or telemetry condition failed."""


@dataclass(frozen=True)
class CapabilityResponse:
    result: LLMResult
    provider_name: str
    finish_reason: str
    request_parameters: Dict[str, Any]


def _choice(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    error = payload.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        message = str(error.get("message") or "provider generation error")[:300]
        raise CapabilityProviderError(f"Provider error {code!r}: {message}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise CapabilityProviderError("Provider returned missing or ambiguous choices")
    return choices[0]


def _text(choice: Mapping[str, Any]) -> str:
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise CapabilityProviderError("Provider returned no assistant message")
    refusal = message.get("refusal")
    if refusal not in (None, "", []):
        raise CapabilityProviderError("Provider returned a refusal")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise CapabilityProviderError("Provider returned no text")
    return content.strip()


def build_capability_request_body(
    *,
    prompt: str,
    requested_model: str,
    max_tokens: int,
    action_schema: str,
    seed: int = DEFAULT_SEED,
    stop: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the one shared request body, with the authorized reasoning exception."""

    if action_schema not in _ACTIONS:
        raise CapabilityProviderError(f"Unknown structured action schema: {action_schema}")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise CapabilityProviderError("max_tokens must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise CapabilityProviderError("seed must be a non-negative integer")
    if stop:
        raise CapabilityProviderError("Stop sequences are forbidden by the shared contract")
    if requested_model not in _REASONING_OMISSION_MODELS | _REASONING_NONE_MODELS:
        raise CapabilityProviderError(f"Reasoning policy is undefined for model: {requested_model}")

    body: Dict[str, Any] = {
        "model": requested_model,
        "messages": [{"role": "user", "content": str(prompt)}],
        "max_tokens": max_tokens,
        "seed": seed,
        "provider": {
            "only": ["OpenAI"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        },
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"realm_{action_schema}_action",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": _ACTIONS[action_schema],
                        },
                        "argument": {
                            "type": "string",
                            "description": f"At most {ARGUMENT_MAX_LENGTH} characters; empty for Finish.",
                        },
                        "answer": {
                            "type": "string",
                            "description": f"At most {ANSWER_MAX_LENGTH} characters; empty for retrieval actions.",
                        },
                    },
                    "required": ["action", "argument", "answer"],
                    "additionalProperties": False,
                },
            },
        },
    }
    if requested_model in _REASONING_NONE_MODELS:
        body["reasoning_effort"] = "none"
    if "temperature" in body or "top_p" in body:
        raise CapabilityProviderError("Sampling parameters are forbidden")
    return body


def _selected_catalog_row(payload: Mapping[str, Any], model_id: str) -> Mapping[str, Any]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise CapabilityProviderError("OpenRouter model catalog schema changed")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("id") == model_id]
    if len(matches) != 1:
        raise CapabilityProviderError(f"Catalog model unavailable or duplicated: {model_id}")
    return matches[0]


def _selected_endpoint(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    endpoints = data.get("endpoints") if isinstance(data, Mapping) else None
    if not isinstance(endpoints, list):
        raise CapabilityProviderError("OpenRouter endpoint catalog schema changed")
    matches = [
        endpoint for endpoint in endpoints
        if isinstance(endpoint, Mapping)
        and endpoint.get("provider_name") == "OpenAI"
        and endpoint.get("tag") == "openai"
    ]
    if len(matches) != 1:
        raise CapabilityProviderError("Standard OpenAI endpoint unavailable or ambiguous")
    return matches[0]


def _normalized_catalog(model: Mapping[str, Any], endpoint: Mapping[str, Any]) -> Dict[str, Any]:
    pricing = endpoint.get("pricing") if isinstance(endpoint.get("pricing"), Mapping) else {}
    return {
        "canonical_slug": model.get("canonical_slug"),
        "context_length": model.get("context_length"),
        "created_unix": model.get("created"),
        "id": model.get("id"),
        "openai_endpoint": {
            "context_length": endpoint.get("context_length"),
            "max_completion_tokens": endpoint.get("max_completion_tokens"),
            "name": endpoint.get("name"),
            "pricing": {
                key: pricing.get(key)
                for key in ("completion", "input_cache_read", "input_cache_write", "prompt")
            },
            "provider_name": endpoint.get("provider_name"),
            "status": endpoint.get("status"),
            "supported_parameters": sorted(endpoint.get("supported_parameters") or []),
            "tag": endpoint.get("tag"),
        },
    }


def validate_live_catalog(snapshot_path: Path, timeout: float = 30.0) -> Dict[str, str]:
    """Fail closed if identity, endpoint parameters, limits, or prices drifted."""

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    model_response = requests.get(MODELS_URL, timeout=timeout)
    model_response.raise_for_status()
    model_payload = model_response.json()
    validated: Dict[str, str] = {}
    for tier, frozen in snapshot["models"].items():
        model_id = str(frozen["id"])
        endpoint_response = requests.get(f"{MODELS_URL}/{model_id}/endpoints", timeout=timeout)
        endpoint_response.raise_for_status()
        current = _normalized_catalog(
            _selected_catalog_row(model_payload, model_id),
            _selected_endpoint(endpoint_response.json()),
        )
        expected = {
            "canonical_slug": frozen["canonical_slug"],
            "context_length": frozen["context_length"],
            "created_unix": frozen["created_unix"],
            "id": frozen["id"],
            "openai_endpoint": {
                **frozen["openai_endpoint"],
                "supported_parameters": sorted(frozen["openai_endpoint"]["supported_parameters"]),
            },
        }
        if current != expected:
            raise CapabilityProviderError(f"{tier}: OpenRouter catalog identity/pricing/schema drift")
        validated[tier] = str(current["canonical_slug"])
    return validated


def call_capability_model(
    *,
    prompt: str,
    requested_model: str,
    canonical_slug: str,
    max_tokens: int,
    action_schema: str,
    seed: int = DEFAULT_SEED,
    stop: Optional[List[str]] = None,
    timeout: float = 180.0,
) -> CapabilityResponse:
    """Make one immutable provider attempt under the exact frozen request body."""

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise CapabilityProviderError("OPENROUTER_API_KEY is unavailable")
    if _CANONICAL_SLUGS.get(requested_model) != canonical_slug:
        raise CapabilityProviderError("Requested model and canonical catalog slug disagree")
    body = build_capability_request_body(
        prompt=prompt,
        requested_model=requested_model,
        max_tokens=int(max_tokens),
        action_schema=action_schema,
        seed=seed,
        stop=stop,
    )
    started = time.perf_counter()
    try:
        response = requests.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise CapabilityProviderError(f"Provider request failed without retry: {type(exc).__name__}: {exc}") from exc
    latency_ms = (time.perf_counter() - started) * 1000
    choice = _choice(payload)
    finish_reason = choice.get("finish_reason")
    if finish_reason != "stop":
        raise CapabilityProviderError(
            f"Unexpected or missing finish reason: {finish_reason!r}"
        )
    text = _text(choice)
    resolved = str(payload.get("model") or "")
    provider = str(payload.get("provider") or "")
    usage = parse_openrouter_usage(payload)
    # OpenRouter currently returns the requested stable alias here. The dated
    # catalog slug is validated independently before execution and retained in
    # every result row; accepting a different response alias remains forbidden.
    if resolved != requested_model:
        raise CapabilityProviderError(f"Unexpected resolved model: {resolved!r}")
    if provider != "OpenAI":
        raise CapabilityProviderError(f"Unexpected or missing provider: {provider!r}")
    if (
        usage.total_tokens <= 0
        or usage.input_tokens <= 0
        or usage.output_tokens <= 0
        or usage.total_tokens < usage.input_tokens + usage.output_tokens
        or usage.reasoning_tokens != 0
        or usage.provider_cost_usd is None
    ):
        raise CapabilityProviderError("Required token telemetry is missing")
    from .realm26_capability_methods import parse_capability_action

    parsed = parse_capability_action(
        text,
        action_schema=action_schema,
        argument_max_length=ARGUMENT_MAX_LENGTH,
        answer_max_length=ANSWER_MAX_LENGTH,
    )
    if parsed["parse_status"] != "ok":
        raise CapabilityProviderError("Provider returned malformed structured output")
    return CapabilityResponse(
        result=LLMResult(
            text=text,
            requested_model=requested_model,
            resolved_model=resolved,
            backend="openrouter",
            input_tokens=usage.input_tokens,
            cached_tokens=usage.cached_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=latency_ms,
            provider_cost_usd=usage.provider_cost_usd,
            retry_count=0,
            status="ok",
        ),
        provider_name=provider,
        finish_reason=finish_reason,
        request_parameters={
            "action_schema": action_schema,
            "max_tokens": int(max_tokens),
            "reasoning_effort": body.get("reasoning_effort"),
            "reasoning_parameter_sent": "reasoning_effort" in body,
            "seed": seed,
            "structured_outputs": True,
            "sampling_parameters_sent": [],
        },
    )

"""Exact OpenRouter binding for the frozen REALM capability tiers.

This module is separate so the completed hash-bound harmonized-v2 request path
remains unchanged. It changes only model binding: both tiers use
``reasoning_effort=none`` and omit sampling parameters.
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


class CapabilityProviderError(ProtocolError):
    """A frozen model, provider, request, or telemetry condition failed."""


@dataclass(frozen=True)
class CapabilityResponse:
    result: LLMResult
    provider_name: str
    request_parameters: Dict[str, Any]


def _text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


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
    stop: Optional[List[str]] = None,
    timeout: float = 180.0,
) -> CapabilityResponse:
    """Make one immutable provider attempt under the exact frozen request body."""

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise CapabilityProviderError("OPENROUTER_API_KEY is unavailable")
    body: Dict[str, Any] = {
        "model": requested_model,
        "messages": [{"role": "user", "content": str(prompt)}],
        "max_tokens": int(max_tokens),
        "reasoning_effort": "none",
        "provider": {
            "only": ["OpenAI"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        },
    }
    if stop:
        body["stop"] = list(stop)
    if "temperature" in body or "top_p" in body:
        raise CapabilityProviderError("Sampling parameters are forbidden")
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
    text = _text(payload)
    resolved = str(payload.get("model") or "")
    provider = str(payload.get("provider") or "")
    usage = parse_openrouter_usage(payload)
    if not text:
        raise CapabilityProviderError("Provider returned no text")
    if resolved != canonical_slug:
        raise CapabilityProviderError(f"Unexpected resolved model: {resolved!r}")
    if provider != "OpenAI":
        raise CapabilityProviderError(f"Unexpected or missing provider: {provider!r}")
    if usage.total_tokens <= 0 or usage.input_tokens <= 0 or usage.output_tokens <= 0:
        raise CapabilityProviderError("Required token telemetry is missing")
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
        request_parameters={
            "max_tokens": int(max_tokens),
            "reasoning_effort": "none",
            "sampling_parameters_sent": [],
        },
    )

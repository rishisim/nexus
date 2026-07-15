"""Structured telemetry helpers for shared LLM calls.

The price table is a dated, reproducibility-oriented fallback.  Callers should
prefer provider-reported cost whenever it is present in an API response.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional


PRICE_SNAPSHOT_DATE = "2026-07-09"

# USD per one million text tokens.  These values were snapshotted from the
# OpenRouter model catalog on PRICE_SNAPSHOT_DATE.  Cached rates are left unset
# where the catalog did not expose a distinct rate; estimation then
# conservatively charges cached tokens at the normal input rate.
MODEL_PRICE_SNAPSHOT: Mapping[str, Mapping[str, Optional[float]]] = {
    "google/gemini-2.5-flash": {
        "input_per_million": 0.30,
        "cached_input_per_million": 0.03,
        "output_per_million": 2.50,
    },
    "gemini-2.5-flash": {
        "input_per_million": 0.30,
        "cached_input_per_million": 0.03,
        "output_per_million": 2.50,
    },
    "google/gemini-2.5-pro": {
        "input_per_million": 1.25,
        "cached_input_per_million": 0.125,
        "output_per_million": 10.00,
    },
    "gemini-2.5-pro": {
        "input_per_million": 1.25,
        "cached_input_per_million": 0.125,
        "output_per_million": 10.00,
    },
    "openai/gpt-5.6-luna": {
        "input_per_million": 1.00,
        "cached_input_per_million": None,
        "output_per_million": 6.00,
    },
    "openai/gpt-5.6-terra": {
        "input_per_million": 2.50,
        "cached_input_per_million": None,
        "output_per_million": 15.00,
    },
}


@dataclass(frozen=True)
class LLMResult:
    """Text plus experiment-grade metadata for one logical LLM call.

    Token fields follow provider conventions: ``cached_tokens`` is a subset of
    ``input_tokens`` and ``reasoning_tokens`` is a subset of ``output_tokens``.
    """

    text: str
    requested_model: str
    resolved_model: str
    backend: str
    input_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    provider_cost_usd: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
    retry_count: int = 0
    status: str = "ok"
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def effective_cost_usd(self) -> Optional[float]:
        """Return provider-reported cost, falling back to the estimate."""

        if self.provider_cost_usd is not None:
            return self.provider_cost_usd
        return self.estimated_cost_usd

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""

        result = asdict(self)
        result["effective_cost_usd"] = self.effective_cost_usd
        return result


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider_cost_usd: Optional[float] = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return default


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def parse_openrouter_usage(data: Mapping[str, Any]) -> TokenUsage:
    """Parse OpenAI-compatible/OpenRouter usage without assuming all fields."""

    usage = _mapping(data.get("usage"))
    input_tokens = _safe_int(_first(usage, "prompt_tokens", "input_tokens"))
    completion_total = _safe_int(
        _first(usage, "completion_tokens", "output_tokens")
    )
    input_details = _mapping(
        _first(usage, "prompt_tokens_details", "input_tokens_details", default={})
    )
    output_details = _mapping(
        _first(
            usage,
            "completion_tokens_details",
            "output_tokens_details",
            default={},
        )
    )
    cached_tokens = _safe_int(
        _first(
            input_details,
            "cached_tokens",
            "cache_read_tokens",
            default=_first(usage, "cached_tokens", "cache_read_tokens", default=0),
        )
    )
    reasoning_tokens = _safe_int(
        _first(
            output_details,
            "reasoning_tokens",
            default=_first(usage, "reasoning_tokens", default=0),
        )
    )
    # OpenAI-compatible APIs include reasoning inside completion tokens.
    output_tokens = completion_total
    reported_total = _safe_int(_first(usage, "total_tokens"))
    # Reasoning is already a subset of completion/output tokens.
    total_tokens = reported_total or input_tokens + output_tokens

    cost_details = _mapping(usage.get("cost_details"))
    provider_cost = _safe_float(
        _first(
            usage,
            "cost",
            "total_cost",
            default=_first(
                cost_details,
                "upstream_inference_cost",
                "total_cost",
                default=data.get("cost"),
            ),
        )
    )
    return TokenUsage(
        input_tokens=input_tokens,
        cached_tokens=min(cached_tokens, input_tokens),
        reasoning_tokens=reasoning_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider_cost_usd=provider_cost,
    )


def _attribute_or_key(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and value.get(name) is not None:
            return value[name]
        candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate
    return default


def parse_gemini_usage(response: Any) -> TokenUsage:
    """Parse usage from google-genai responses and dictionary fixtures."""

    metadata = _attribute_or_key(response, "usage_metadata", "usageMetadata", default={})
    input_tokens = _safe_int(
        _attribute_or_key(metadata, "prompt_token_count", "promptTokenCount")
    )
    cached_tokens = _safe_int(
        _attribute_or_key(
            metadata, "cached_content_token_count", "cachedContentTokenCount"
        )
    )
    reasoning_tokens = _safe_int(
        _attribute_or_key(metadata, "thoughts_token_count", "thoughtsTokenCount")
    )
    visible_output_tokens = _safe_int(
        _attribute_or_key(metadata, "candidates_token_count", "candidatesTokenCount")
    )
    # Normalize Google usage to the OpenAI convention: thoughts are a subset
    # of all generated/output tokens.
    output_tokens = visible_output_tokens + reasoning_tokens
    total_tokens = _safe_int(
        _attribute_or_key(metadata, "total_token_count", "totalTokenCount")
    ) or input_tokens + output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        cached_tokens=min(cached_tokens, input_tokens),
        reasoning_tokens=reasoning_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def estimate_cost_usd(model_id: str, usage: TokenUsage) -> Optional[float]:
    """Estimate cost from the frozen price snapshot, if the model is known."""

    price = MODEL_PRICE_SNAPSHOT.get(model_id)
    if price is None:
        return None
    input_rate = price.get("input_per_million")
    output_rate = price.get("output_per_million")
    if input_rate is None or output_rate is None:
        return None
    cached_rate = price.get("cached_input_per_million")
    if cached_rate is None:
        cached_rate = input_rate
    cached = min(usage.cached_tokens, usage.input_tokens)
    uncached = max(0, usage.input_tokens - cached)
    billable_output = usage.output_tokens
    return (
        uncached * input_rate + cached * cached_rate + billable_output * output_rate
    ) / 1_000_000

"""
Shared LLM module for Nexus experiments.

Supports two backends:
  - "openrouter" (default): Uses OpenRouter API (OpenAI-compatible) for higher rate limits
  - "gemini": Uses Google Generative AI (original backend)

Usage:
    from src.shared.llm import llm, llm_judge_answer

    # Uses OPENROUTER_API_KEY from .env by default
    response = llm("What is 2+2?", stop=["\\n"])

Configuration via environment variables:
    LLM_BACKEND       = "openrouter" | "gemini"   (default: "openrouter")
    LLM_MODEL          = model name               (default: auto per backend)
    OPENROUTER_API_KEY = your key                  (for openrouter backend)
    GEMINI_API_KEY     = your key                  (for gemini backend)
"""

import os
import random
import time
import requests as req
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Union, overload
from dotenv import load_dotenv

from src.shared.llm_telemetry import (
    LLMResult,
    estimate_cost_usd,
    parse_gemini_usage,
    parse_openrouter_usage,
)

load_dotenv()

# --- Configuration ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "openrouter")
LLM_MODEL = os.getenv("LLM_MODEL", None)
LLM_DELAY = float(os.getenv("LLM_DELAY", "0.1"))  # seconds between calls
DEFAULT_MAX_ATTEMPTS = 5  # Frozen finance_icaif26_v2 retry policy.

# Default models per backend
_DEFAULT_MODELS = {
    "openrouter": "google/gemini-2.5-flash",
    "gemini": "gemini-2.5-flash",
}

def _get_model(model_id: Optional[str] = None, backend: Optional[str] = None) -> str:
    """Resolve a per-call model before falling back to process configuration."""

    if model_id:
        return model_id
    if LLM_MODEL:
        return LLM_MODEL
    selected_backend = backend or LLM_BACKEND
    return _DEFAULT_MODELS.get(selected_backend, "google/gemini-2.5-flash")


# --- OpenRouter Backend ---
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_openrouter_model_snapshot(
    model_ids: Iterable[str], timeout: float = 30.0
) -> Dict[str, Any]:
    """Fetch selected public catalog entries once for a reproducible run.

    The returned snapshot always identifies missing slugs; the experiment
    runner should persist it and fail closed when ``missing_model_ids`` is not
    empty.
    """

    requested = sorted(set(model_ids))
    response = req.get(_OPENROUTER_MODELS_URL, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, Mapping) else []
    by_id = {
        str(row["id"]): dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("id")
    }
    selected = {model_id: by_id[model_id] for model_id in requested if model_id in by_id}
    missing = [model_id for model_id in requested if model_id not in by_id]
    return {
        "source": _OPENROUTER_MODELS_URL,
        "queried_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_model_ids": requested,
        "models": selected,
        "missing_model_ids": missing,
    }

def _build_openrouter_body(
    prompt: str,
    stop: List[str],
    temperature: float,
    max_tokens: int,
    model_id: str,
) -> Dict[str, Any]:
    """Construct a provider-compatible request without reading global model state."""

    body: Dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }

    if model_id == "openai/gpt-5.6-luna":
        # GPT-5.6 does not accept sampling parameters when reasoning is set.
        body["reasoning_effort"] = "none"
    else:
        body["temperature"] = (
            0.0 if model_id == "google/gemini-2.5-flash" else temperature
        )
        body["top_p"] = 1.0

    if model_id == "google/gemini-2.5-flash":
        # The primary experiment protocol disables model-internal thinking.
        body["reasoning"] = {"max_tokens": 0}
    if model_id == "openai/gpt-4o-mini-2024-07-18":
        # Bind the replication request to OpenAI's exact model provider and
        # fail closed rather than silently routing to a fallback provider.
        body["provider"] = {
            "only": ["OpenAI"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        }
    if stop:
        body["stop"] = stop
    return body


def _call_openrouter(
    prompt: str,
    stop: List[str],
    temperature: float,
    max_tokens: int,
    model_id: str,
) -> Mapping[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set in environment")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = _build_openrouter_body(prompt, stop, temperature, max_tokens, model_id)

    resp = req.post(_OPENROUTER_URL, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


# --- Gemini Backend ---
_gemini_client = None

def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client()
    return _gemini_client

def _call_gemini(
    prompt: str,
    stop: List[str],
    temperature: float,
    max_tokens: int,
    model_id: str,
) -> Any:
    from google.genai import types
    client = _get_gemini_client()
    response = client.models.generate_content(
        model=model_id.removeprefix("google/"),
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            stop_sequences=stop,
            temperature=temperature,
            max_output_tokens=max_tokens,
            top_p=1.0
        )
    )
    return response


# --- Public API ---

def _extract_openrouter_text(data: Mapping[str, Any]) -> str:
    choices = data.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    message = first.get("message", {})
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content", "")
    return content.strip() if isinstance(content, str) else ""


def _extract_gemini_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, Mapping):
        value = response.get("text", "")
    else:
        value = getattr(response, "text", "")
    return value.strip() if isinstance(value, str) else ""


def _status_code(exc: BaseException) -> Optional[int]:
    """Extract an HTTP-like status from requests and common SDK errors."""

    response = getattr(exc, "response", None)
    candidates = [
        getattr(response, "status_code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
    ]
    for value in candidates:
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if hasattr(value, "value"):
            value = value.value
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _classify_error(exc: BaseException) -> tuple[str, bool]:
    """Return ``(status, retryable)`` for a failed provider attempt."""

    code = _status_code(exc)
    if isinstance(exc, (req.Timeout, req.ConnectionError, TimeoutError, ConnectionError)):
        return "infrastructure_error", True
    if code in {408, 409, 429} or (code is not None and 500 <= code <= 599):
        return "infrastructure_error", True
    if code is not None and 400 <= code <= 499:
        return "client_error", False
    if isinstance(exc, ValueError):
        return "configuration_error", False
    return "model_error", False


def _failure_result(
    *,
    requested_model: str,
    backend: str,
    started: float,
    retry_count: int,
    status: str,
    error_type: str,
    error_message: str,
) -> LLMResult:
    return LLMResult(
        text="",
        requested_model=requested_model,
        resolved_model=requested_model,
        backend=backend,
        latency_ms=(time.perf_counter() - started) * 1000,
        retry_count=retry_count,
        status=status,
        error_type=error_type,
        error_message=error_message[:500],
    )


def llm_with_metadata(
    prompt: str,
    stop: Optional[List[str]] = None,
    temperature: Optional[float] = None,
    num_traces: int = 1,
    max_tokens: int = 512,
    model_id: Optional[str] = None,
    backend: Optional[str] = None,
    max_retries: int = DEFAULT_MAX_ATTEMPTS,
) -> LLMResult:
    """Call a model and return text, usage, latency, cost, and retry metadata.

    ``max_retries`` is retained as a backward-compatible parameter name but
    denotes total attempts.  ``LLMResult.retry_count`` counts attempts after
    the first, so exhausting the default five attempts yields four retries.
    """

    selected_backend = backend or LLM_BACKEND
    requested_model = _get_model(model_id=model_id, backend=selected_backend)
    stop_sequences = ["\n"] if stop is None else stop
    temp = (0.0 if num_traces == 1 else 0.7) if temperature is None else temperature
    retries = max(1, max_retries)
    started = time.perf_counter()
    if LLM_DELAY > 0:
        time.sleep(LLM_DELAY)

    for attempt in range(retries):
        try:
            if selected_backend == "openrouter":
                raw = _call_openrouter(
                    prompt, stop_sequences, temp, max_tokens, requested_model
                )
                text = _extract_openrouter_text(raw)
                usage = parse_openrouter_usage(raw)
                resolved_model = str(raw.get("model") or requested_model)
            elif selected_backend == "gemini":
                raw = _call_gemini(
                    prompt, stop_sequences, temp, max_tokens, requested_model
                )
                text = _extract_gemini_text(raw)
                usage = parse_gemini_usage(raw)
                if isinstance(raw, Mapping):
                    raw_model = raw.get("model_version") or raw.get("modelVersion")
                else:
                    raw_model = getattr(raw, "model_version", None)
                resolved_model = str(raw_model or requested_model)
            else:
                raise ValueError(f"Unsupported LLM backend: {selected_backend}")

            latency_ms = (time.perf_counter() - started) * 1000
            estimated_cost = estimate_cost_usd(resolved_model, usage)
            if estimated_cost is None:
                estimated_cost = estimate_cost_usd(requested_model, usage)
            if not text:
                return LLMResult(
                    text="",
                    requested_model=requested_model,
                    resolved_model=resolved_model,
                    backend=selected_backend,
                    input_tokens=usage.input_tokens,
                    cached_tokens=usage.cached_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    latency_ms=latency_ms,
                    provider_cost_usd=usage.provider_cost_usd,
                    estimated_cost_usd=estimated_cost,
                    retry_count=attempt,
                    status="empty_response",
                    error_type="empty_response",
                    error_message="Provider returned no text content",
                )
            return LLMResult(
                text=text,
                requested_model=requested_model,
                resolved_model=resolved_model,
                backend=selected_backend,
                input_tokens=usage.input_tokens,
                cached_tokens=usage.cached_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                latency_ms=latency_ms,
                provider_cost_usd=usage.provider_cost_usd,
                estimated_cost_usd=estimated_cost,
                retry_count=attempt,
                status="ok",
            )
        except Exception as exc:
            status, retryable = _classify_error(exc)
            print(
                f"[LLM] {selected_backend} call failed "
                f"(attempt {attempt + 1}/{retries}, {status}): {exc}"
            )
            if not retryable or attempt == retries - 1:
                return _failure_result(
                    requested_model=requested_model,
                    backend=selected_backend,
                    started=started,
                    retry_count=attempt,
                    status=status,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            # Exponential backoff with bounded additive jitter.  ``attempt`` is
            # zero-based, so the first retry waits about one second.
            time.sleep((2 ** attempt) + random.uniform(0.0, 0.25))

    # The loop always returns, but keep a fail-closed guard for static checkers.
    return _failure_result(
        requested_model=requested_model,
        backend=selected_backend,
        started=started,
        retry_count=max(0, retries - 1),
        status="model_error",
        error_type="unexpected_retry_state",
        error_message="LLM retry loop exited unexpectedly",
    )


@overload
def llm(
    prompt: str,
    stop: Optional[List[str]] = None,
    temperature: Optional[float] = None,
    num_traces: int = 1,
    max_tokens: int = 512,
    model_id: Optional[str] = None,
    return_metadata: Literal[False] = False,
    backend: Optional[str] = None,
) -> str: ...


@overload
def llm(
    prompt: str,
    stop: Optional[List[str]] = None,
    temperature: Optional[float] = None,
    num_traces: int = 1,
    max_tokens: int = 512,
    model_id: Optional[str] = None,
    return_metadata: Literal[True] = True,
    backend: Optional[str] = None,
) -> LLMResult: ...


def llm(
    prompt: str,
    stop: Optional[List[str]] = None,
    temperature: Optional[float] = None,
    num_traces: int = 1,
    max_tokens: int = 512,
    model_id: Optional[str] = None,
    return_metadata: bool = False,
    backend: Optional[str] = None,
) -> Union[str, LLMResult]:
    """
    Call the language model. Drop-in replacement for all per-agent llm() functions.

    Args:
        prompt: Input prompt string
        stop: Stop sequences
        temperature: Override temperature (None = 0.0 for single trace, 0.7 for multi)
        num_traces: Affects default temperature
        max_tokens: Maximum output tokens
        model_id: Explicit per-call model; overrides ``LLM_MODEL``.
        return_metadata: Return :class:`LLMResult` instead of a legacy string.
        backend: Explicit per-call backend; overrides ``LLM_BACKEND``.

    Returns:
        Response text string by default, or ``LLMResult`` when requested.
    """
    result = llm_with_metadata(
        prompt=prompt,
        stop=stop,
        temperature=temperature,
        num_traces=num_traces,
        max_tokens=max_tokens,
        model_id=model_id,
        backend=backend,
    )
    if return_metadata:
        return result
    if result.status == "ok":
        return result.text
    return "I need to finish now.\nFinish[Unable to proceed due to API error]"


def llm_judge_answer(question: str, prediction: str, ground_truth: str) -> dict:
    """
    Use LLM as a judge to evaluate semantic equivalence.
    Shared implementation so all agents use the same evaluation.
    """
    prompt = f"""You are an expert evaluator for a Question Answering system.

Question: {question}
Ground Truth Answer: {ground_truth}
Predicted Answer: {prediction}

Task: Determine if the "Predicted Answer" is semantically equivalent to the "Ground Truth Answer".

Guidelines:
- Ignore minor formatting differences (punctuation, capitalization)
- Allow for synonyms or different entity aliases (e.g., "JFK" = "John F. Kennedy")
- If the prediction adds extra correct context, it is ACCEPTABLE
- If the prediction is vague or missing key information, it is INCORRECT

Output:
Explanation: [Brief reasoning]
Label: [CORRECT or INCORRECT]"""

    response = llm(prompt, stop=[], num_traces=1)

    is_correct = "CORRECT" in response.upper() and "INCORRECT" not in response.upper()

    explanation = response.strip()
    if "Explanation:" in response:
        parts = response.split("Label:")
        explanation = parts[0].replace("Explanation:", "").strip() if parts else response.strip()

    return {
        'llm_correct': is_correct,
        'llm_explanation': explanation
    }

"""Comparable finance-QA methods for the ICAIF 2026 evaluation.

Runner-facing functions share the contract::

    run_<framework>(idx: int, model_id: str, to_print: bool = False, **deps)
        -> (reward: float, result: dict)

The optional dependency keywords are for testing and orchestration. Production
calls resolve the active finance environment and the shared metadata LLM lazily,
which keeps ``model_id`` a real per-call binding rather than a result label.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # Package import in the experiment runner.
    from .method_prompts import COT_PROMPT, DIRECT_PROMPT, NEXUS_PROMPT, REACT_PROMPT
    from .selective_router import (
        RouterDecision,
        SelectiveRouter,
        extract_router_features,
    )
except ImportError:  # Script-style import used by legacy finance entrypoints.
    from method_prompts import COT_PROMPT, DIRECT_PROMPT, NEXUS_PROMPT, REACT_PROMPT
    from selective_router import RouterDecision, SelectiveRouter, extract_router_features


DEFAULT_EVIDENCE_TOKEN_BUDGET = 4096
DEFAULT_MAX_REACT_STEPS = 7
_CONFIGURED_ROUTER: Optional[SelectiveRouter] = None


class FinanceMethodLLMError(RuntimeError):
    """Typed fail-closed error for a non-successful model call."""

    def __init__(self, metadata: Mapping[str, Any]):
        self.metadata = dict(metadata)
        self.status = str(self.metadata.get("status") or "model_error")
        self.failure_type = (
            "infrastructure_failure"
            if self.status == "infrastructure_error"
            else "model_failure"
        )
        error_type = self.metadata.get("error_type") or self.status
        error_message = self.metadata.get("error_message") or "LLM call returned no usable output"
        super().__init__(f"{self.failure_type}: {error_type}: {error_message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_type": self.failure_type,
            "status": self.status,
            "llm_metadata": dict(self.metadata),
        }


def _default_env():
    try:
        from .finance_utils import get_finance_env
    except ImportError:
        from finance_utils import get_finance_env
    return get_finance_env()


def _default_llm():
    from src.shared.llm import llm

    return llm


def _sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _truncate_tokens(text: str, budget: int) -> Tuple[str, bool, int]:
    if budget <= 0:
        raise ValueError("evidence_token_budget must be positive")
    pieces = str(text or "").split()
    truncated = len(pieces) > budget
    return " ".join(pieces[:budget]), truncated, min(len(pieces), budget)


def _model_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        return str(response.get("text", ""))
    return str(getattr(response, "text", ""))


def _model_metadata(response: Any, model_id: str) -> Dict[str, Any]:
    if isinstance(response, str):
        return {
            "requested_model": model_id,
            "resolved_model": model_id,
            "status": "ok" if response else "empty_response",
        }
    if hasattr(response, "to_dict"):
        metadata = dict(response.to_dict())
    elif is_dataclass(response):
        metadata = asdict(response)
    elif isinstance(response, Mapping):
        metadata = dict(response)
    else:
        names = (
            "requested_model", "resolved_model", "backend", "input_tokens",
            "cached_tokens", "reasoning_tokens", "output_tokens", "total_tokens",
            "latency_ms", "provider_cost_usd", "estimated_cost_usd", "retry_count",
            "status",
        )
        metadata = {name: getattr(response, name) for name in names if hasattr(response, name)}
    metadata.pop("text", None)
    metadata.setdefault("requested_model", model_id)
    metadata.setdefault("resolved_model", model_id)
    metadata.setdefault("status", "ok" if _model_text(response) else "empty_response")
    return metadata


def _invoke_llm(
    llm_func: Callable[..., Any],
    prompt: str,
    model_id: str,
    *,
    stop: Optional[List[str]] = None,
    max_tokens: int = 512,
) -> Tuple[str, Dict[str, Any]]:
    """Invoke a real or mock model while always binding the requested model."""

    kwargs = {
        "stop": [] if stop is None else stop,
        "num_traces": 1,
        "max_tokens": max_tokens,
        "model_id": model_id,
        "return_metadata": True,
    }
    # Simple mocks often do not expose every production keyword.  Filter only
    # when their signature is inspectable and has no **kwargs; model_id remains
    # mandatory to guard against label-only experiment configuration.
    try:
        signature = inspect.signature(llm_func)
    except (TypeError, ValueError):
        signature = None
    if signature is not None and not any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        if "model_id" not in kwargs:
            raise TypeError("LLM callable must accept model_id for a controlled experiment")
    response = llm_func(prompt, **kwargs)
    text = _model_text(response)
    metadata = _model_metadata(response, model_id)
    if metadata.get("status") != "ok" or not text.strip():
        if metadata.get("status") == "ok":
            metadata["status"] = "empty_response"
            metadata.setdefault("error_type", "empty_response")
            metadata.setdefault("error_message", "Model returned no usable text")
        raise FinanceMethodLLMError(metadata)
    return text, metadata


def _parse_answer(output: str) -> str:
    matches = re.findall(r"^\s*Answer\s*:\s*(.+?)\s*$", str(output), re.I | re.M)
    if matches:
        return matches[-1].strip()
    finishes = re.findall(r"Finish\[(.*?)\]", str(output), re.I | re.S)
    if finishes:
        return finishes[-1].strip()
    lines = [line.strip() for line in str(output).splitlines() if line.strip()]
    return lines[-1] if lines else "UNKNOWN"


def _env_step(env: Any, action: str) -> Tuple[str, float, bool, Dict[str, Any]]:
    observation, reward, done, info = env.step(action)
    return str(observation), float(reward or 0.0), bool(done), dict(info or {})


def _search(env: Any, query: str) -> Tuple[str, Dict[str, Any]]:
    observation, _, _, info = _env_step(env, f"Search[{query}]")
    return observation, dict(info.get("evidence_stats") or {})


def _summarize_telemetry(calls: Sequence[Mapping[str, Any]], model_id: str) -> Dict[str, Any]:
    def total(name: str) -> Optional[float]:
        values = [call.get(name) for call in calls if call.get(name) is not None]
        return sum(float(value) for value in values) if values else None

    resolved = [str(call["resolved_model"]) for call in calls if call.get("resolved_model")]
    backends = [str(call["backend"]) for call in calls if call.get("backend")]
    statuses = [str(call.get("status", "")) for call in calls]
    return {
        "requested_model": model_id,
        "resolved_model": resolved[-1] if resolved else model_id,
        "backend": backends[-1] if backends else None,
        "input_tokens": total("input_tokens"),
        "cached_tokens": total("cached_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "output_tokens": total("output_tokens"),
        "total_tokens": total("total_tokens"),
        "latency_ms": total("latency_ms"),
        "provider_cost_usd": total("provider_cost_usd"),
        "estimated_cost_usd": total("estimated_cost_usd"),
        "retry_count": int(total("retry_count") or 0),
        "llm_status": "ok" if calls and all(status == "ok" for status in statuses) else "error",
        "llm_telemetry": [dict(call) for call in calls],
    }


def _finish_result(
    *,
    env: Any,
    idx: int,
    question: str,
    answer: str,
    framework: str,
    model_id: str,
    dossier: str,
    prompt: str,
    trace: str,
    telemetry: Sequence[Mapping[str, Any]],
    retrieval_calls: int,
    evidence_stats: Optional[Mapping[str, Any]],
    dossier_truncated: bool,
    dossier_token_count: int,
    extra: Optional[Mapping[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    observation, reward, _, info = _env_step(env, f"Finish[{answer}]")
    result: Dict[str, Any] = {
        **info,
        "question_idx": idx,
        "question_text": question,
        "answer": answer,
        "reward": reward,
        "framework": framework,
        "n_calls": len(telemetry),
        "n_badcalls": 0,
        "retrieval_calls": retrieval_calls,
        "raw_trace": trace,
        "traj": trace,
        "dossier": dossier,
        "dossier_token_count": dossier_token_count,
        "dossier_truncated": dossier_truncated,
        "evidence_stats": dict(evidence_stats or {}),
        "evidence_hash": _sha256(dossier),
        "prompt_hash": _sha256(prompt),
        "finish_observation": observation,
        **_summarize_telemetry(telemetry, model_id),
    }
    if extra:
        result.update(extra)
    return reward, result


def build_structured_queries(question: str, max_queries: int = 3) -> List[str]:
    """Create deterministic finance search queries without model calls."""

    question = re.sub(r"\s+", " ", str(question or "")).strip()
    if not question:
        return [""]
    periods = re.findall(
        r"\b(?:FY\s*)?(?:19|20)\d{2}\b|\bQ[1-4]\s*(?:19|20)?\d{0,4}\b",
        question,
        re.I,
    )
    entities = re.findall(
        r"\b(?:[A-Z][A-Za-z&.-]*(?:\s+[A-Z][A-Za-z&.-]*)+|[A-Z]{2,6})\b",
        question,
    )
    metrics = re.findall(
        r"\b(?:revenue|sales|net income|operating income|cash flow|free cash flow|"
        r"capital expenditure|assets|liabilities|equity|margin|tax rate|earnings|"
        r"expense|cost|debt|customers?|production|inventory|receivables?|payables?)\b",
        question,
        re.I,
    )
    candidates = [question]
    entity = entities[0] if entities else ""
    period_text = " ".join(dict.fromkeys(periods))
    metric_text = " ".join(dict.fromkeys(metric.lower() for metric in metrics))
    if entity or period_text or metric_text:
        candidates.append(" ".join(part for part in (entity, period_text, metric_text) if part))
    # A calculation-focused query strips interrogative scaffolding while
    # retaining all numbers and finance concepts.
    content = re.sub(
        r"\b(?:what|which|who|when|where|why|how|much|many|did|does|do|was|were|is|are|the|a|an)\b",
        " ",
        question,
        flags=re.I,
    )
    content = re.sub(r"\s+", " ", content).strip(" ?. ")
    if content:
        candidates.append(content)
    unique: List[str] = []
    for candidate in candidates:
        if candidate and candidate.lower() not in {item.lower() for item in unique}:
            unique.append(candidate)
    return unique[:max_queries]


def _run_one_call_method(
    idx: int,
    model_id: str,
    framework: str,
    prompt_template: str,
    *,
    to_print: bool = False,
    env: Any = None,
    llm_func: Optional[Callable[..., Any]] = None,
    evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
    structured: bool = False,
    prepared: Optional[Tuple[str, str, Mapping[str, Any]]] = None,
) -> Tuple[float, Dict[str, Any]]:
    env = env or _default_env()
    llm_func = llm_func or _default_llm()
    if prepared is None:
        question = str(env.reset(idx=idx))
        initial_observation = None
        initial_stats: Mapping[str, Any] = {}
    else:
        question, initial_observation, initial_stats = prepared
    queries = build_structured_queries(question) if structured else [question]
    dossier_parts: List[str] = []
    retrieval_stats: Mapping[str, Any] = initial_stats
    retrieval_calls = 0
    start_at = 0
    if initial_observation is not None:
        dossier_parts.append(f"[Search: {question}]\n{initial_observation}")
        retrieval_calls = 1
        if queries and queries[0] == question:
            start_at = 1
    for query in queries[start_at:]:
        observation, stats = _search(env, query)
        dossier_parts.append(f"[Search: {query}]\n{observation}")
        retrieval_stats = stats or retrieval_stats
        retrieval_calls += 1
    raw_dossier = "\n\n".join(dossier_parts)
    dossier, truncated, token_count = _truncate_tokens(raw_dossier, evidence_token_budget)
    prompt = prompt_template.format(question=question, dossier=dossier)
    output, metadata = _invoke_llm(llm_func, prompt, model_id, stop=[], max_tokens=768)
    answer = _parse_answer(output)
    trace = (
        f"Question: {question}\nQueries: {queries}\n\nDossier:\n{dossier}\n\n"
        f"Model output:\n{output}"
    )
    if to_print:
        print(f"[{framework.upper()}] {question}\nAnswer: {answer}")
    return _finish_result(
        env=env,
        idx=idx,
        question=question,
        answer=answer,
        framework=framework,
        model_id=model_id,
        dossier=dossier,
        prompt=prompt,
        trace=trace,
        telemetry=[metadata],
        retrieval_calls=retrieval_calls,
        evidence_stats=retrieval_stats,
        dossier_truncated=truncated,
        dossier_token_count=token_count,
        extra={"search_queries": queries, "method_version": "icaif26_v2"},
    )


def run_direct(
    idx: int,
    model_id: str,
    to_print: bool = False,
    **kwargs: Any,
) -> Tuple[float, Dict[str, Any]]:
    """Single Search[question], followed by one concise answer call."""

    return _run_one_call_method(
        idx, model_id, "direct", DIRECT_PROMPT, to_print=to_print, structured=False, **kwargs
    )


def run_cot(
    idx: int,
    model_id: str,
    to_print: bool = False,
    **kwargs: Any,
) -> Tuple[float, Dict[str, Any]]:
    """Single Search[question], followed by one chain/program-of-thought call."""

    return _run_one_call_method(
        idx, model_id, "cot", COT_PROMPT, to_print=to_print, structured=False, **kwargs
    )


def run_nexus(
    idx: int,
    model_id: str,
    to_print: bool = False,
    **kwargs: Any,
) -> Tuple[float, Dict[str, Any]]:
    """Static deterministic structured retrieval plus one adjudication call."""

    return _run_one_call_method(
        idx, model_id, "nexus", NEXUS_PROMPT, to_print=to_print, structured=True, **kwargs
    )


def _parse_react_action(output: str, step_number: int) -> Tuple[str, str]:
    thought_match = re.search(
        rf"(?:^|\n)\s*Thought\s*{step_number}\s*:\s*(.*?)(?=\n\s*Action\s*{step_number}\s*:|$)",
        output,
        re.I | re.S,
    )
    action_match = re.search(
        r"\b(Search|Lookup|Finish)\s*\[(.*?)\]",
        output,
        re.I | re.S,
    )
    thought = thought_match.group(1).strip() if thought_match else output.strip().splitlines()[0]
    if not action_match:
        return thought, "Finish[UNKNOWN]"
    kind = action_match.group(1).title()
    argument = re.sub(r"\s+", " ", action_match.group(2)).strip()
    return thought, f"{kind}[{argument}]"


def run_react(
    idx: int,
    model_id: str,
    to_print: bool = False,
    *,
    env: Any = None,
    llm_func: Optional[Callable[..., Any]] = None,
    max_steps: int = DEFAULT_MAX_REACT_STEPS,
    evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
) -> Tuple[float, Dict[str, Any]]:
    """Seven-step ReAct adapter over the shared finance action interface."""

    env = env or _default_env()
    llm_func = llm_func or _default_llm()
    question = str(env.reset(idx=idx))
    base_prompt = REACT_PROMPT.format(question=question, max_steps=max_steps)
    transcript = base_prompt
    telemetry: List[Mapping[str, Any]] = []
    dossier_parts: List[str] = []
    retrieval_calls = 0
    badcalls = 0
    evidence_stats: Mapping[str, Any] = {}
    answer = "UNKNOWN"
    reward = 0.0
    finish_info: Dict[str, Any] = {}
    finish_observation = ""

    for step_number in range(1, max_steps + 1):
        output, metadata = _invoke_llm(
            llm_func,
            transcript + f"\nThought {step_number}:",
            model_id,
            stop=[f"\nObservation {step_number}:"],
            max_tokens=512,
        )
        telemetry.append(metadata)
        thought, action = _parse_react_action(output, step_number)
        if action == "Finish[UNKNOWN]" and not re.search(r"\bFinish\s*\[", output, re.I):
            badcalls += 1
        observation, step_reward, done, info = _env_step(env, action)
        if action.lower().startswith(("search[", "lookup[")):
            retrieval_calls += 1
            dossier_parts.append(f"[{action}]\n{observation}")
            evidence_stats = dict(info.get("evidence_stats") or evidence_stats)
        transcript += (
            f"\nThought {step_number}: {thought}\nAction {step_number}: {action}"
            f"\nObservation {step_number}: {observation}\n"
        )
        if to_print:
            print(f"Thought {step_number}: {thought}\nAction {step_number}: {action}\nObservation: {observation}")
        if done:
            answer = str(info.get("answer", _parse_answer(action)))
            reward = step_reward
            finish_info = info
            finish_observation = observation
            break

    if not finish_info:
        finish_observation, reward, _, finish_info = _env_step(env, "Finish[UNKNOWN]")
        answer = str(finish_info.get("answer", "UNKNOWN"))
        transcript += f"\nAction {max_steps + 1}: Finish[UNKNOWN]\nObservation: {finish_observation}\n"

    raw_dossier = "\n\n".join(dossier_parts)
    dossier, truncated, token_count = _truncate_tokens(raw_dossier, evidence_token_budget)
    result: Dict[str, Any] = {
        **finish_info,
        "question_idx": idx,
        "question_text": question,
        "answer": answer,
        "reward": reward,
        "framework": "react",
        "n_calls": len(telemetry),
        "n_badcalls": badcalls,
        "retrieval_calls": retrieval_calls,
        "raw_trace": transcript,
        "traj": transcript,
        "dossier": dossier,
        "dossier_token_count": token_count,
        "dossier_truncated": truncated,
        "evidence_stats": dict(evidence_stats),
        "evidence_hash": _sha256(dossier),
        "prompt_hash": _sha256(base_prompt),
        "finish_observation": finish_observation,
        "method_version": "icaif26_v2",
        **_summarize_telemetry(telemetry, model_id),
    }
    return reward, result


def configure_selective_router(router: Optional[SelectiveRouter]) -> None:
    """Set the frozen router used by the three-argument runner callable."""

    global _CONFIGURED_ROUTER
    _CONFIGURED_ROUTER = router


def _resolve_router(router: Optional[SelectiveRouter]) -> SelectiveRouter:
    if router is not None:
        return router
    if _CONFIGURED_ROUTER is not None:
        return _CONFIGURED_ROUTER
    path = os.getenv("FINANCE_ROUTER_PATH")
    if path:
        return SelectiveRouter.load(Path(path))
    raise RuntimeError(
        "Selective Nexus requires a frozen router. Call configure_selective_router() "
        "or set FINANCE_ROUTER_PATH before running the selective framework."
    )


def run_selective(
    idx: int,
    model_id: str,
    to_print: bool = False,
    *,
    env: Any = None,
    llm_func: Optional[Callable[..., Any]] = None,
    router: Optional[SelectiveRouter] = None,
    evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
    max_steps: int = DEFAULT_MAX_REACT_STEPS,
) -> Tuple[float, Dict[str, Any]]:
    """Route to static Nexus or ReAct using retrieval-only pre-answer features."""

    env = env or _default_env()
    llm_func = llm_func or _default_llm()
    router = _resolve_router(router)
    question = str(env.reset(idx=idx))
    initial_observation, evidence_stats = _search(env, question)
    features = extract_router_features(
        question,
        [initial_observation],
        evidence_stats=evidence_stats,
    )
    decision = router.decide(features)
    if decision.route == "nexus":
        reward, result = _run_one_call_method(
            idx,
            model_id,
            "nexus",
            NEXUS_PROMPT,
            to_print=to_print,
            env=env,
            llm_func=llm_func,
            evidence_token_budget=evidence_token_budget,
            structured=True,
            prepared=(question, initial_observation, evidence_stats),
        )
    else:
        # ReAct starts from a clean episode. The deterministic routing search is
        # still counted as a retrieval operation in the selective result.
        reward, result = run_react(
            idx,
            model_id,
            to_print=to_print,
            env=env,
            llm_func=llm_func,
            max_steps=max_steps,
            evidence_token_budget=evidence_token_budget,
        )
        result["retrieval_calls"] = int(result.get("retrieval_calls", 0)) + 1

    result.update(
        {
            "framework": "selective",
            "selected_framework": decision.route,
            "route_selected": decision.route,
            "router_mode": decision.mode,
            "router_threshold": decision.threshold,
            "router_benefit_probability": decision.benefit_probability,
            "router_reasons": list(decision.reasons),
            "router_features": features,
            "router_retrieval_calls": 1,
        }
    )
    return reward, result


def _result_correct(result: Mapping[str, Any]) -> bool:
    native_scores = result.get("native_scores")
    if isinstance(native_scores, Mapping):
        for key in ("execution_accuracy", "exact", "em", "correct"):
            if key in native_scores:
                return float(native_scores[key]) > 0.0
    for key in ("reward", "em", "correct"):
        if key in result:
            return float(result[key]) > 0.0
    raise ValueError("Oracle inputs require a native correctness score")


def _result_cost(result: Mapping[str, Any]) -> float:
    for key in ("provider_cost_usd", "estimated_cost_usd"):
        if result.get(key) is not None:
            return float(result[key])
    return float(result.get("n_calls", 0))


def offline_oracle(
    static_result: Mapping[str, Any],
    react_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compute unattainable routing headroom from already saved outcomes.

    This function never calls a model and is intentionally absent from the
    deployable framework registry.
    """

    static_correct = _result_correct(static_result)
    react_correct = _result_correct(react_result)
    if static_correct and not react_correct:
        route = "nexus"
    elif react_correct and not static_correct:
        route = "react"
    else:
        route = "nexus" if _result_cost(static_result) <= _result_cost(react_result) else "react"
    selected = dict(static_result if route == "nexus" else react_result)
    selected.update(
        {
            "framework": "oracle",
            "selected_framework": route,
            "route_selected": route,
            "oracle_only": True,
            "oracle_static_correct": static_correct,
            "oracle_react_correct": react_correct,
        }
    )
    return selected


# Descriptive aliases for analysis code; the runner uses the short protocol
# names in ``FRAMEWORKS`` below.
run_cot_pot = run_cot
run_static_nexus = run_nexus
run_react_adapter = run_react


FRAMEWORKS: Dict[str, Callable[..., Tuple[float, Dict[str, Any]]]] = {
    "direct": run_direct,
    "cot": run_cot,
    "react": run_react,
    "nexus": run_nexus,
    "selective": run_selective,
}
FRAMEWORK_MAP = FRAMEWORKS

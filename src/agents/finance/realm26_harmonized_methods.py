"""Prompt/context-harmonized Static and bounded-ReAct finance methods.

Both arms use the same strict JSON finish schema, the same UNKNOWN fallback,
the same cumulative evidence-word ceiling, the same retrieval-operation
ceiling, the same per-call prompt-word ceiling, and the same output ceiling.
The treatment difference is intentionally retained: Static makes one model
call after deterministic retrieval, while ReAct may make bounded iterative
calls and choose its evidence actions adaptively.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .finance_methods import (
    FinanceMethodLLMError,
    _env_step,
    _invoke_llm,
    _summarize_telemetry,
    build_structured_queries,
)
from .realm26_harmonized_prompts import ANSWER_CONTRACT, REACT_PROMPT, STATIC_PROMPT


UNKNOWN = "UNKNOWN"
FRAMEWORKS = ("static", "react")


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _words(text: str) -> List[str]:
    return str(text or "").split()


def word_count(text: str) -> int:
    return len(_words(text))


def take_words(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    return " ".join(_words(text)[:limit])


def strict_action(output: str, *, static: bool = False) -> Dict[str, str]:
    """Parse the one shared action contract; malformed output always finishes UNKNOWN."""

    fallback = {
        "thought": "Malformed model output.",
        "action": "Finish",
        "answer": UNKNOWN,
        "parse_status": "malformed_fallback",
    }
    try:
        value = json.loads(str(output).strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    if not isinstance(value, Mapping):
        return fallback
    action = value.get("action")
    thought = value.get("thought")
    if not isinstance(action, str) or not isinstance(thought, str):
        return fallback
    action = action.strip().title()
    if static and action != "Finish":
        return fallback
    if action == "Finish":
        answer = value.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return fallback
        return {
            "thought": thought.strip(),
            "action": "Finish",
            "answer": " ".join(answer.split()),
            "parse_status": "ok",
        }
    if action in {"Search", "Lookup"}:
        argument = value.get("argument")
        if not isinstance(argument, str) or not argument.strip():
            return fallback
        return {
            "thought": thought.strip(),
            "action": action,
            "argument": " ".join(argument.split()),
            "parse_status": "ok",
        }
    return fallback


def _fit_prompt(
    template: str,
    *,
    context_word_budget: int,
    evidence_word_budget: int,
    evidence: str,
    history: str = "(none)",
    **fields: Any,
) -> Tuple[str, str, str]:
    """Fit evidence first and then recent history under one deterministic ceiling."""

    empty = template.format(evidence="", history="", **fields)
    fixed = word_count(empty)
    if fixed >= context_word_budget:
        raise ValueError("context_word_budget is too small for frozen instructions")
    available = context_word_budget - fixed
    evidence_text = take_words(evidence, min(evidence_word_budget, available))
    available -= word_count(evidence_text)
    history_words = _words(history)
    history_text = " ".join(history_words[-available:]) if available > 0 else ""
    prompt = template.format(evidence=evidence_text or "(none)", history=history_text or "(none)", **fields)
    if word_count(prompt) > context_word_budget:
        # The two placeholder sentinel words can make the empty estimate one
        # word short. Trim history first, then evidence, deterministically.
        overflow = word_count(prompt) - context_word_budget
        if overflow and history_text:
            history_text = " ".join(_words(history_text)[overflow:])
        prompt = template.format(evidence=evidence_text or "(none)", history=history_text or "(none)", **fields)
        overflow = word_count(prompt) - context_word_budget
        if overflow:
            evidence_text = take_words(evidence_text, max(0, word_count(evidence_text) - overflow))
            prompt = template.format(evidence=evidence_text or "(none)", history=history_text or "(none)", **fields)
    if word_count(prompt) > context_word_budget:
        raise AssertionError("prompt context ceiling was not enforced")
    return prompt, evidence_text, history_text


def _common_result(
    *,
    info: Mapping[str, Any],
    idx: int,
    question: str,
    answer: str,
    framework: str,
    telemetry: Sequence[Mapping[str, Any]],
    prompt_records: Sequence[Mapping[str, Any]],
    evidence: str,
    evidence_word_budget: int,
    context_word_budget: int,
    retrieval_operations: int,
    parse_status: str,
    trace: str,
    episode_wall_ms: float,
) -> Dict[str, Any]:
    result = {
        **dict(info),
        "question_idx": idx,
        "question_text": question,
        "answer": answer,
        "framework": framework,
        "n_calls": len(telemetry),
        "n_badcalls": int(parse_status != "ok"),
        "retrieval_calls": retrieval_operations,
        "retrieval_operation_count": retrieval_operations,
        "raw_trace": trace,
        "traj": trace,
        "evidence_observed": evidence,
        "evidence_word_count": word_count(evidence),
        "evidence_word_budget": evidence_word_budget,
        "context_word_budget": context_word_budget,
        "max_prompt_word_count": max((int(row["word_count"]) for row in prompt_records), default=0),
        "prompt_records": [dict(row) for row in prompt_records],
        "prompt_hash": _sha256("\n".join(str(row["sha256"]) for row in prompt_records)),
        "evidence_hash": _sha256(evidence),
        "parse_status": parse_status,
        "malformed_fallback": parse_status != "ok",
        "episode_wall_ms": episode_wall_ms,
        "method_version": "realm26_harmonized_v1",
        **_summarize_telemetry(telemetry, str(telemetry[-1].get("requested_model")) if telemetry else ""),
    }
    return result


def run_static(
    idx: int,
    model_id: str,
    to_print: bool = False,
    *,
    env: Any,
    llm_func: Callable[..., Any],
    evidence_word_budget: int,
    context_word_budget: int,
    max_retrieval_operations: int,
    max_output_tokens: int,
    **_: Any,
) -> Tuple[float, Dict[str, Any]]:
    started = time.perf_counter()
    question = str(env.reset(idx=idx))
    observations: List[str] = []
    used = 0
    queries = build_structured_queries(question, max_queries=max_retrieval_operations)
    for query in queries:
        observation, _, _, _ = _env_step(env, f"Search[{query}]")
        remaining = max(0, evidence_word_budget - used)
        visible = take_words(observation, remaining)
        used += word_count(visible)
        observations.append(f"[Search: {query}]\n{visible}")
    evidence = "\n\n".join(observations)
    prompt, visible_evidence, _ = _fit_prompt(
        STATIC_PROMPT,
        context_word_budget=context_word_budget,
        evidence_word_budget=evidence_word_budget,
        evidence=evidence,
        question=question,
        answer_contract=ANSWER_CONTRACT,
    )
    output, metadata = _invoke_llm(
        llm_func, prompt, model_id, stop=[], max_tokens=max_output_tokens
    )
    parsed = strict_action(output, static=True)
    answer = parsed.get("answer", UNKNOWN)
    observation, reward, _, info = _env_step(env, f"Finish[{answer}]")
    prompt_records = [{
        "call_index": 1,
        "sha256": _sha256(prompt),
        "utf8_bytes": len(prompt.encode("utf-8")),
        "word_count": word_count(prompt),
    }]
    trace = json.dumps(
        {"queries": queries, "model_output": output, "parsed": parsed, "finish_observation": observation},
        ensure_ascii=False,
        sort_keys=True,
    )
    result = _common_result(
        info=info,
        idx=idx,
        question=question,
        answer=answer,
        framework="static",
        telemetry=[metadata],
        prompt_records=prompt_records,
        evidence=visible_evidence,
        evidence_word_budget=evidence_word_budget,
        context_word_budget=context_word_budget,
        retrieval_operations=len(queries),
        parse_status=str(parsed["parse_status"]),
        trace=trace,
        episode_wall_ms=(time.perf_counter() - started) * 1000,
    )
    if to_print:
        print(f"[STATIC] {question}\nAnswer: {answer}")
    return reward, result


def run_react(
    idx: int,
    model_id: str,
    to_print: bool = False,
    *,
    env: Any,
    llm_func: Callable[..., Any],
    evidence_word_budget: int,
    context_word_budget: int,
    max_retrieval_operations: int,
    max_output_tokens: int,
    max_steps: int,
    **_: Any,
) -> Tuple[float, Dict[str, Any]]:
    started = time.perf_counter()
    question = str(env.reset(idx=idx))
    telemetry: List[Mapping[str, Any]] = []
    prompt_records: List[Mapping[str, Any]] = []
    evidence_parts: List[str] = []
    history: List[str] = []
    retrieval_operations = 0
    answer = UNKNOWN
    parse_status = "step_exhaustion_fallback"
    reward = 0.0
    finish_info: Mapping[str, Any] = {}
    finish_observation = ""

    for step in range(1, max_steps + 1):
        evidence = "\n\n".join(evidence_parts)
        prompt, visible_evidence, visible_history = _fit_prompt(
            REACT_PROMPT,
            context_word_budget=context_word_budget,
            evidence_word_budget=evidence_word_budget,
            evidence=evidence,
            history="\n".join(history),
            question=question,
            max_steps=max_steps,
            max_retrieval_operations=max_retrieval_operations,
            answer_contract=ANSWER_CONTRACT,
        )
        output, metadata = _invoke_llm(
            llm_func, prompt, model_id, stop=[], max_tokens=max_output_tokens
        )
        telemetry.append(metadata)
        prompt_records.append({
            "call_index": step,
            "sha256": _sha256(prompt),
            "utf8_bytes": len(prompt.encode("utf-8")),
            "word_count": word_count(prompt),
        })
        parsed = strict_action(output)
        parse_status = str(parsed["parse_status"])
        history.append(json.dumps({"step": step, "output": parsed}, sort_keys=True))
        action = parsed["action"]
        if action == "Finish":
            answer = parsed.get("answer", UNKNOWN)
            finish_observation, reward, _, finish_info = _env_step(env, f"Finish[{answer}]")
            break
        if retrieval_operations >= max_retrieval_operations:
            history.append("Observation: evidence-operation budget exhausted; submit Finish.")
            continue
        argument = parsed["argument"]
        observation, _, _, _ = _env_step(env, f"{action}[{argument}]")
        retrieval_operations += 1
        remaining = max(0, evidence_word_budget - word_count("\n\n".join(evidence_parts)))
        visible = take_words(observation, remaining)
        evidence_parts.append(f"[{action}: {argument}]\n{visible}")
        history.append(f"Observation {step}: evidence recorded in the evidence section.")
        if to_print:
            print(f"Step {step}: {parsed}")

    if not finish_info:
        answer = UNKNOWN
        finish_observation, reward, _, finish_info = _env_step(env, "Finish[UNKNOWN]")
    evidence = take_words("\n\n".join(evidence_parts), evidence_word_budget)
    trace = json.dumps(
        {"history": history, "answer": answer, "finish_observation": finish_observation},
        ensure_ascii=False,
        sort_keys=True,
    )
    result = _common_result(
        info=finish_info,
        idx=idx,
        question=question,
        answer=answer,
        framework="react",
        telemetry=telemetry,
        prompt_records=prompt_records,
        evidence=evidence,
        evidence_word_budget=evidence_word_budget,
        context_word_budget=context_word_budget,
        retrieval_operations=retrieval_operations,
        parse_status=parse_status,
        trace=trace,
        episode_wall_ms=(time.perf_counter() - started) * 1000,
    )
    return reward, result


METHODS = {"static": run_static, "react": run_react}

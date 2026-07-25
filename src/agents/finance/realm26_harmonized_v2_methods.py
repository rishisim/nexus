"""Prospectively frozen methods for the harmonized Static-vs-ReAct v2 study.

Static is behavior-identical to v1. ReAct adds the predeclared treatment-
integrity rule that its first model action must be Search. This prevents an
empty-context abstention from being misclassified as an iterative ReAct run.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

from .finance_methods import _env_step, _invoke_llm
from .realm26_harmonized_methods import (
    UNKNOWN,
    _common_result,
    _fit_prompt,
    _sha256,
    run_static,
    strict_action,
    take_words,
    word_count,
)
from .realm26_harmonized_v2_prompts import ANSWER_CONTRACT, REACT_V2_PROMPT


FRAMEWORKS = ("static", "react")
REACT_ACTION_POLICY = "first_model_action_must_be_search_v2"


class ReActPolicyViolation(RuntimeError):
    """The model did not enact the prospectively frozen ReAct treatment."""


def run_static_v2(*args: Any, **kwargs: Any) -> Tuple[float, Dict[str, Any]]:
    """Run the frozen v1 Static arm unchanged and label the v2 study version."""

    reward, result = run_static(*args, **kwargs)
    result["method_version"] = "realm26_harmonized_v2"
    result["react_action_policy"] = None
    return reward, result


def run_react_v2(
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
    model_actions: List[str] = []
    retrieval_operations = 0
    answer = UNKNOWN
    parse_status = "step_exhaustion_fallback"
    reward = 0.0
    finish_info: Mapping[str, Any] = {}
    finish_observation = ""

    for step in range(1, max_steps + 1):
        evidence = "\n\n".join(evidence_parts)
        prompt, _, _ = _fit_prompt(
            REACT_V2_PROMPT,
            context_word_budget=context_word_budget,
            evidence_word_budget=evidence_word_budget,
            evidence=evidence,
            history="\n".join(history),
            question=question,
            step=step,
            max_steps=max_steps,
            evidence_action_count=retrieval_operations,
            max_retrieval_operations=max_retrieval_operations,
            remaining_evidence_actions=max(0, max_retrieval_operations - retrieval_operations),
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
        action = str(parsed["action"])
        model_actions.append(action)
        history.append(json.dumps({"step": step, "output": parsed}, sort_keys=True))

        if step == 1 and action != "Search":
            raise ReActPolicyViolation(
                f"First model action was {action!r}; frozen v2 requires Search"
            )
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
        if step == 1 and not visible:
            raise ReActPolicyViolation("The mandatory first Search yielded no visible evidence")
        evidence_parts.append(f"[{action}: {argument}]\n{visible}")
        history.append(f"Observation {step}: evidence recorded in the evidence section.")
        if to_print:
            print(f"Step {step}: {parsed}")

    if not finish_info:
        answer = UNKNOWN
        finish_observation, reward, _, finish_info = _env_step(env, "Finish[UNKNOWN]")
    evidence = take_words("\n\n".join(evidence_parts), evidence_word_budget)
    trace = json.dumps(
        {
            "answer": answer,
            "finish_observation": finish_observation,
            "history": history,
            "model_actions": model_actions,
        },
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
    result.update({
        "first_model_action": model_actions[0] if model_actions else None,
        "method_version": "realm26_harmonized_v2",
        "model_actions": model_actions,
        "react_action_policy": REACT_ACTION_POLICY,
        "react_process_integrity": (
            bool(model_actions)
            and model_actions[0] == "Search"
            and retrieval_operations >= 1
            and word_count(evidence) > 0
            and len(telemetry) >= 2
            and parse_status == "ok"
        ),
    })
    return reward, result


METHODS = {"static": run_static_v2, "react": run_react_v2}

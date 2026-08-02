"""Compact, fail-closed method adapter for the REALM capability study."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Mapping, Tuple

from . import realm26_harmonized_v2_methods as v2
from . import realm26_harmonized_methods as shared


ARGUMENT_MAX_LENGTH = 1024
ANSWER_MAX_LENGTH = 1024
PROMPT_UTF8_BYTE_LIMIT = 8192

CAPABILITY_ANSWER_CONTRACT = (
    'Return exactly one JSON object with exactly the keys "action", "argument", '
    'and "answer". For Finish, use '
    '{"action":"Finish","argument":"","answer":"short answer"}. '
    'For Search or Lookup, put the query in "argument" and set "answer" to "". '
    'Do not return reasoning, extra fields, markdown, trailing text, or a second object. '
    f'Argument and answer strings must each be at most {ARGUMENT_MAX_LENGTH} characters. '
    'If the evidence is insufficient at Finish, set answer to "UNKNOWN".'
)

CAPABILITY_STATIC_PROMPT = """You are the one-call Static financial-QA system.
Use only the evidence shown below. Preserve the requested period, sign, unit,
scale, and currency. Perform any calculation internally and return only the
compact action object.

Question: {question}

Evidence observed within the shared budget:
{evidence}

{answer_contract}
"""

CAPABILITY_REACT_PROMPT = """You are the bounded iterative ReAct financial-QA system.
Use only the controlled evidence packet through exactly one action per model turn:
- Search: {{"action":"Search","argument":"query","answer":""}}
- Lookup: {{"action":"Lookup","argument":"keyword","answer":""}}
- Finish: {{"action":"Finish","argument":"","answer":"short answer"}}

Treatment-integrity rule: your first model action MUST be Search. Before one
evidence action has completed, Lookup and Finish are invalid. After evidence is
observed, adaptively choose Search, Lookup, or Finish. Do not answer from prior
knowledge and do not return reasoning or a second action object.

Preserve the requested period, sign, unit, scale, and currency. You are at model
step {step} of at most {max_steps}. You have completed {evidence_action_count}
of at most {max_retrieval_operations} evidence actions, leaving
{remaining_evidence_actions}.

Question: {question}

Evidence observed within the shared budget:
{evidence}

Recent interaction log:
{history}

{answer_contract}
"""


def _fallback(reason: str) -> Dict[str, str]:
    return {
        "action": "Finish",
        "argument": "",
        "answer": shared.UNKNOWN,
        "parse_error": reason,
        "parse_status": "malformed_fallback",
    }


def parse_capability_action(
    output: str,
    *,
    action_schema: str = "react",
    argument_max_length: int = ARGUMENT_MAX_LENGTH,
    answer_max_length: int = ANSWER_MAX_LENGTH,
) -> Dict[str, str]:
    """Parse exactly one complete compact object; never salvage a prefix."""

    allowed = {
        "finish": {"Finish"},
        "search": {"Search"},
        "react": {"Search", "Lookup", "Finish"},
    }
    if action_schema not in allowed:
        raise ValueError(f"unknown action schema: {action_schema}")
    try:
        value = json.loads(str(output).strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return _fallback("not_exactly_one_json_value")
    if not isinstance(value, Mapping) or set(value) != {"action", "argument", "answer"}:
        return _fallback("object_keys_or_type")
    action, argument, answer = value["action"], value["argument"], value["answer"]
    if not all(isinstance(item, str) for item in (action, argument, answer)):
        return _fallback("non_string_field")
    if action not in allowed[action_schema]:
        return _fallback("action_not_allowed_for_step")
    argument = " ".join(argument.split())
    answer = " ".join(answer.split())
    if len(argument) > argument_max_length or len(answer) > answer_max_length:
        return _fallback("string_length_bound")
    if action == "Finish":
        if argument or not answer:
            return _fallback("finish_field_semantics")
    elif not argument or answer:
        return _fallback("retrieval_field_semantics")
    return {
        "action": action,
        "argument": argument,
        "answer": answer,
        "parse_status": "ok",
    }


def _bounded_fit_prompt(
    original: Callable[..., Tuple[str, str, str]], *args: Any, **kwargs: Any
) -> Tuple[str, str, str]:
    """Retain the word ceiling and additionally fail-close above 8192 bytes."""

    prompt, evidence, history = original(*args, **kwargs)
    if len(prompt.encode("utf-8")) <= PROMPT_UTF8_BYTE_LIMIT:
        return prompt, evidence, history
    maximum_words = int(kwargs["context_word_budget"])
    best: Tuple[str, str, str] | None = None
    low, high = 1, maximum_words - 1
    while low <= high:
        midpoint = (low + high) // 2
        candidate_kwargs = dict(kwargs)
        candidate_kwargs["context_word_budget"] = midpoint
        try:
            candidate = original(*args, **candidate_kwargs)
        except ValueError:
            low = midpoint + 1
            continue
        if len(candidate[0].encode("utf-8")) <= PROMPT_UTF8_BYTE_LIMIT:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    if best is None:
        raise ValueError("fixed capability prompt exceeds the 8192-byte shared ceiling")
    return best


def _run_with_adapter(method: Callable[..., Any], *, static: bool, kwargs: Dict[str, Any]):
    shared_prompt = shared.STATIC_PROMPT
    shared_contract = shared.ANSWER_CONTRACT
    shared_parser = shared.strict_action
    shared_fit = shared._fit_prompt
    v2_prompt = v2.REACT_V2_PROMPT
    v2_contract = v2.ANSWER_CONTRACT
    v2_parser = v2.strict_action
    v2_fit = v2._fit_prompt
    shared.STATIC_PROMPT = CAPABILITY_STATIC_PROMPT
    shared.ANSWER_CONTRACT = CAPABILITY_ANSWER_CONTRACT
    shared.strict_action = lambda output, **_: parse_capability_action(output, action_schema="finish")
    shared._fit_prompt = lambda *args, **fit_kwargs: _bounded_fit_prompt(shared_fit, *args, **fit_kwargs)
    v2.REACT_V2_PROMPT = CAPABILITY_REACT_PROMPT
    v2.ANSWER_CONTRACT = CAPABILITY_ANSWER_CONTRACT
    v2.strict_action = lambda output, **_: parse_capability_action(output, action_schema="react")
    v2._fit_prompt = lambda *args, **fit_kwargs: _bounded_fit_prompt(v2_fit, *args, **fit_kwargs)
    try:
        return method(**kwargs)
    finally:
        shared.STATIC_PROMPT = shared_prompt
        shared.ANSWER_CONTRACT = shared_contract
        shared.strict_action = shared_parser
        shared._fit_prompt = shared_fit
        v2.REACT_V2_PROMPT = v2_prompt
        v2.ANSWER_CONTRACT = v2_contract
        v2.strict_action = v2_parser
        v2._fit_prompt = v2_fit


def run_react_capability(**kwargs: Any):
    return _run_with_adapter(v2.run_react_v2, static=False, kwargs=kwargs)


def run_static_capability(**kwargs: Any):
    return _run_with_adapter(v2.run_static_v2, static=True, kwargs=kwargs)


METHODS = {"static": run_static_capability, "react": run_react_capability}

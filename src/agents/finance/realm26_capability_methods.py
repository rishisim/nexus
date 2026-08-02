"""Capability-study method adapter for one-action-per-turn ReAct output."""

from __future__ import annotations

import json
from typing import Any

from . import realm26_harmonized_v2_methods as v2
from . import realm26_harmonized_methods as shared


SHARED_STRICT_ACTION = v2.strict_action

CAPABILITY_REACT_PROMPT = v2.REACT_V2_PROMPT.replace(
    "Treatment-integrity rule: your first model action MUST be Search.",
    "Return exactly one JSON action object for this model turn and then stop; "
    "do not emit a second action in the same response.\n\n"
    "Treatment-integrity rule: your first model action MUST be Search.",
)


def first_json_action(output: str, *, static: bool = False):
    """Parse the first complete JSON action and ignore trailing model text."""

    try:
        value, _ = json.JSONDecoder().raw_decode(str(output).lstrip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return SHARED_STRICT_ACTION(output, static=static)
    return SHARED_STRICT_ACTION(json.dumps(value), static=static)


def run_react_capability(**kwargs: Any):
    """Run v2 ReAct with the prospectively frozen single-action clarification."""

    original = v2.REACT_V2_PROMPT
    original_parser = v2.strict_action
    if original == CAPABILITY_REACT_PROMPT:
        raise RuntimeError("Capability prompt adapter was applied twice")
    v2.REACT_V2_PROMPT = CAPABILITY_REACT_PROMPT
    v2.strict_action = first_json_action
    try:
        return v2.run_react_v2(**kwargs)
    finally:
        v2.REACT_V2_PROMPT = original
        v2.strict_action = original_parser


def run_static_capability(**kwargs: Any):
    """Run v2 Static with the same first-object output normalization."""

    original_parser = shared.strict_action
    shared.strict_action = first_json_action
    try:
        return v2.run_static_v2(**kwargs)
    finally:
        shared.strict_action = original_parser


METHODS = {"static": run_static_capability, "react": run_react_capability}

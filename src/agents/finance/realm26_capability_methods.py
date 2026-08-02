"""Capability-study method adapter for one-action-per-turn ReAct output."""

from __future__ import annotations

from typing import Any

from . import realm26_harmonized_v2_methods as v2


CAPABILITY_REACT_PROMPT = v2.REACT_V2_PROMPT.replace(
    "Treatment-integrity rule: your first model action MUST be Search.",
    "Return exactly one JSON action object for this model turn and then stop; "
    "do not emit a second action in the same response.\n\n"
    "Treatment-integrity rule: your first model action MUST be Search.",
)


def run_react_capability(**kwargs: Any):
    """Run v2 ReAct with the prospectively frozen single-action clarification."""

    original = v2.REACT_V2_PROMPT
    if original == CAPABILITY_REACT_PROMPT:
        raise RuntimeError("Capability prompt adapter was applied twice")
    v2.REACT_V2_PROMPT = CAPABILITY_REACT_PROMPT
    try:
        return v2.run_react_v2(**kwargs)
    finally:
        v2.REACT_V2_PROMPT = original


METHODS = {"static": v2.run_static_v2, "react": run_react_capability}


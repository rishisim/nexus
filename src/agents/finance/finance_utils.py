"""Shared utilities for finance agents."""

import os
import re
import sys
from typing import Dict

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
SHARED_DIR = os.path.join(PROJECT_ROOT, "src", "shared")
if SHARED_DIR not in sys.path:
    sys.path.append(SHARED_DIR)

from src.shared.experiment_utils import step, EnvWrapper  # noqa: E402
from src.shared.llm import llm  # noqa: E402
try:  # Package imports for the protocol runner and tests.
    from .finance_env import exact_or_numeric_match, make_finance_env, token_f1  # noqa: E402
    from .finance_prompts import FINANCE_REACT_PROMPT_TEMPLATE  # noqa: E402
except ImportError:  # Backward-compatible direct script execution.
    from finance_env import exact_or_numeric_match, make_finance_env, token_f1  # noqa: E402
    from finance_prompts import FINANCE_REACT_PROMPT_TEMPLATE  # noqa: E402


_ACTIVE_DATASET_ID = "financebench"
_FINANCE_ENVS = {}


def set_active_dataset(dataset_id: str):
    """Set the dataset used by finance ReAct and Nexus wrappers."""
    global _ACTIVE_DATASET_ID
    _ACTIVE_DATASET_ID = dataset_id


def get_finance_env(dataset_id: str = None):
    """Get or initialize a finance environment by dataset id."""
    dataset_id = dataset_id or _ACTIVE_DATASET_ID
    if dataset_id not in _FINANCE_ENVS:
        _FINANCE_ENVS[dataset_id] = make_finance_env(dataset_id)
    return _FINANCE_ENVS[dataset_id]


def get_financebench_env():
    """Backward-compatible helper for the public FinanceBench environment."""
    return get_finance_env("financebench")


def extract_final_answer_from_trace(trace: str):
    pattern = re.compile(r"^Action \d+:\s*Finish\[(.*?)\]\s*$", re.MULTILINE)
    matches = pattern.findall(trace or "")
    return matches[-1].strip() if matches else None


def run_single_trace(idx: int, initial_prompt_template: str = None,
                     to_print: bool = True, max_steps: int = 7) -> Dict:
    """Execute a single ReAct trace for the active finance dataset."""
    env = get_finance_env()
    question = env.reset(idx=idx)
    prompt_template = initial_prompt_template or FINANCE_REACT_PROMPT_TEMPLATE
    current_prompt = prompt_template.format(question=question)

    if to_print:
        print(f"[TRACE] Finance index: {idx}")
        print(f"[QUESTION] {question}")

    n_calls = 0
    n_badcalls = 0
    current_trace_steps = []
    done = False
    info = {}

    for i in range(1, max_steps + 1):
        n_calls += 1
        thought_action = llm(
            current_prompt + f"\nThought {i}:",
            stop=[f"\nObservation {i}:"],
            num_traces=1,
            max_tokens=512,
        )

        try:
            thought, action = thought_action.strip().split(f"\nAction {i}: ", 1)
        except ValueError:
            n_badcalls += 1
            thought = thought_action.strip().split("\n")[0] if thought_action else "Need to answer from evidence."
            action_prompt = current_prompt + f"\nThought {i}: {thought}\nAction {i}:"
            action = llm(action_prompt, stop=["\n"], num_traces=1, max_tokens=128).strip()
            if not action or not any(kind in action for kind in ("Search[", "Lookup[", "Finish[")):
                action = "Finish[UNKNOWN]"

        obs, reward, done, info = step(env, action)
        obs = obs.replace("\\n", "") if isinstance(obs, str) else str(obs)
        step_str = f"Thought {i}: {thought}\nAction {i}: {action}\nObservation {i}: {obs}\n"
        current_trace_steps.append(step_str)
        current_prompt += "\n" + step_str

        if to_print:
            print(step_str)
        if done:
            break

    if not done:
        obs, reward, done, info = step(env, "Finish[UNKNOWN]")
        current_trace_steps.append(
            f"Thought {max_steps + 1}: Agent did not finish within step budget.\n"
            f"Action {max_steps + 1}: Finish[UNKNOWN]\n"
            f"Observation {max_steps + 1}: {obs}\n"
        )

    answer = info.get("answer", "")
    gt_answer = info.get("gt_answer", "")
    trace = current_prompt + "\n".join(current_trace_steps)

    return {
        **info,
        "question_idx": idx,
        "question_text": question,
        "answer": answer,
        "gt_answer": gt_answer,
        "em": exact_or_numeric_match(answer, gt_answer),
        "f1": token_f1(answer, gt_answer),
        "reward": reward,
        "n_calls": n_calls,
        "n_badcalls": n_badcalls,
        "traj": trace,
        "framework": "react",
    }

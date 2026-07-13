"""ReAct baseline for FinanceBench."""

from finance_prompts import FINANCE_REACT_PROMPT_TEMPLATE
from finance_utils import run_single_trace


def run_react(idx, prompt_template=None, to_print=True):
    """Run standard single-trace ReAct on a FinanceBench question."""
    trace_info = run_single_trace(
        idx=idx,
        initial_prompt_template=prompt_template or FINANCE_REACT_PROMPT_TEMPLATE,
        to_print=to_print,
    )
    return trace_info.get("reward", 0.0), trace_info


if __name__ == "__main__":
    reward, info = run_react(idx=0, to_print=True)
    print(f"\n[TEST RESULT] Reward: {reward}, Answer: {info['answer']}")

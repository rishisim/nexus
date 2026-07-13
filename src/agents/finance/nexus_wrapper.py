"""Nexus wrapper for FinanceBench."""

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agents.nexus.nexus_agent import NexusAgent  # noqa: E402
from src.shared.experiment_utils import EnvWrapper  # noqa: E402
from finance_prompts import (  # noqa: E402
    FINANCE_ADJUDICATOR_PROMPT,
    FINANCE_ARCHITECT_PROMPT,
    FINANCE_NARRATIVE_ADJUDICATOR_PROMPT,
    FINANCE_NUMERIC_ADJUDICATOR_PROMPT,
    FINANCE_SCOUT_PROMPT,
)
from finance_utils import get_finance_env, llm  # noqa: E402


def _parse_answer(llm_output: str) -> str:
    match = re.search(r"^Answer:\s*(.+)$", llm_output, re.MULTILINE | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    lines = [line.strip() for line in llm_output.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "UNKNOWN"


def _finance_scout_queries(question: str):
    """Deterministic finance Scout for evidence-packet QA."""
    queries = [question]
    metric_patterns = [
        r"FY\d{4}[A-Z0-9]*\s+[^?.,;:]+",
        r"(capital expenditure|free cash flow|effective tax rate|primary customers|production rate|net income|operating margin|DPO|PPNE)",
    ]
    for pattern in metric_patterns:
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            query = match.group(0).strip()
            if query and query.lower() not in {q.lower() for q in queries}:
                queries.append(query)
    return queries[:3]


def _adjudicator_prompt_for_dataset(dataset_id: str) -> str:
    if dataset_id == "finder":
        return FINANCE_NARRATIVE_ADJUDICATOR_PROMPT
    if dataset_id in {"finqa", "tatqa", "convfinqa"}:
        return FINANCE_NUMERIC_ADJUDICATOR_PROMPT
    return FINANCE_ADJUDICATOR_PROMPT


def run_nexus(idx, prompt_template=None, to_print=True):
    """
    Run finance-specialized Nexus on a FinanceBench question.

    This keeps the Nexus phases but makes Scout and Architect deterministic for
    FinanceBench evidence packets. Only the Adjudicator is an LLM call, which is
    the finance-lane hypothesis for reducing cost.
    """
    env = get_finance_env()
    wrapped_env = EnvWrapper(env)
    question = wrapped_env.reset(idx=idx)

    if to_print:
        print("=" * 60)
        print("[FRAMEWORK] Finance Nexus (deterministic Scout/Architect -> Adjudicator)")
        print("=" * 60)
        print(f"[EX] Index: {idx}")
        print(f"[QUESTION] {question}")

    trace = f"Question: {question}\n\n[Phase 1: Deterministic Scout]\n"
    dossier_parts = []
    scout_queries = _finance_scout_queries(question)
    for query in scout_queries:
        obs, _, _, _ = wrapped_env.step(f"Search[{query}]")
        trace += f"Scout Search[{query}] -> OK\n"
        dossier_parts.append(f"[Scout evidence: {query}]\n{obs}")

    trace += "\n[Phase 2: Deterministic Architect]\n"
    bridge_keywords = [
        "total",
        "change",
        "cash flow",
        "statement",
        "revenue",
        "expense",
        "customers",
        "production",
    ]
    for keyword in bridge_keywords:
        if keyword in question.lower():
            obs, _, _, _ = wrapped_env.step(f"Lookup[{keyword}]")
            if not str(obs).startswith("No passages containing"):
                trace += f"Architect Lookup[{keyword}] -> OK\n"
                dossier_parts.append(f"[Bridge evidence: {keyword}]\n{obs}")

    dossier = "\n\n".join(dossier_parts)
    dataset_id = getattr(env, "dataset_id", "financebench")
    prompt_template = _adjudicator_prompt_for_dataset(dataset_id)
    prompt = prompt_template.format(question=question, dossier=dossier)
    max_tokens = 768 if dataset_id == "finder" else 512
    llm_output = llm(prompt, stop=[], num_traces=1, max_tokens=max_tokens)
    answer = _parse_answer(llm_output)
    trace += f"\n[Phase 3: Adjudicator]\n{llm_output}"

    obs, reward, done, info = wrapped_env.step(f"Finish[{answer}]")
    result = {
        **info,
        "question_idx": idx,
        "question_text": question,
        "answer": answer,
        "gt_answer": info.get("gt_answer", ""),
        "reward": reward,
        "n_calls": 1,
        "n_badcalls": 0,
        "traj": trace,
        "dossier": dossier,
        "framework": "nexus",
        "nexus_mode": "finance_deterministic_scout_architect",
    }

    if to_print:
        print(f"[FINAL ACTION] Finish[{answer}]")
        print(f"[RESULT] Answer: {answer} | GT: {result['gt_answer']} | EM: {result.get('em', 0.0)}")

    return reward, result


def run_nexus_core(idx, prompt_template=None, to_print=True):
    """Run the original 3-call shared Nexus agent on a FinanceBench question."""
    env = get_finance_env()
    wrapped_env = EnvWrapper(env)
    question = wrapped_env.reset(idx=idx)

    if to_print:
        print("=" * 60)
        print("[FRAMEWORK] Nexus Finance (Scout -> Architect -> Adjudicator)")
        print("=" * 60)
        print(f"[EX] Index: {idx}")
        print(f"[QUESTION] {question}")

    agent = NexusAgent(
        llm_func=llm,
        env=wrapped_env,
        task_type="finance_qa",
        scout_prompt=FINANCE_SCOUT_PROMPT,
        architect_prompt=FINANCE_ARCHITECT_PROMPT,
        adjudicator_prompt=FINANCE_ADJUDICATOR_PROMPT,
    )

    try:
        answer, debug_info = agent.solve(question)
    except Exception as exc:
        answer = "UNKNOWN"
        debug_info = {"traj": f"Error: {exc}", "dossier": ""}

    obs, reward, done, info = wrapped_env.step(f"Finish[{answer}]")
    result = {
        **info,
        "question_idx": idx,
        "question_text": question,
        "answer": answer,
        "gt_answer": info.get("gt_answer", ""),
        "reward": reward,
        "n_calls": agent.n_calls,
        "n_badcalls": 0,
        "traj": debug_info.get("traj", ""),
        "dossier": debug_info.get("dossier", ""),
        "framework": "nexus",
    }

    if to_print:
        print(f"[FINAL ACTION] Finish[{answer}]")
        print(f"[RESULT] Answer: {answer} | GT: {result['gt_answer']} | EM: {result.get('em', 0.0)}")

    return reward, result


if __name__ == "__main__":
    reward, info = run_nexus(idx=0, to_print=True)
    print(f"\n[TEST RESULT] Reward: {reward}, Answer: {info['answer']}")

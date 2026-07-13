"""Audit and aggregate paired finance experiment results."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from finance_env import exact_or_numeric_match, token_f1  # noqa: E402


DATASETS = ["financebench", "finder", "finqa", "tatqa", "convfinqa"]


def run_name(seed: int, model: str, results_tag: str) -> str:
    name = f"seed{seed}_{model.replace('/', '-')}"
    return f"{name}_{results_tag}" if results_tag else name


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def successful_by_idx(rows: List[Dict]) -> Dict[int, Dict]:
    return {
        int(row["question_idx"]): row
        for row in rows
        if row.get("status") == "success" and "question_idx" in row
    }


def score(row: Dict) -> Tuple[float, float]:
    answer = row.get("answer", "")
    gt_answer = row.get("gt_answer", "")
    return exact_or_numeric_match(answer, gt_answer), token_f1(answer, gt_answer)


def framework_stats(rows: List[Dict]) -> Dict:
    valid = [row for row in rows if row.get("status") == "success"]
    if not valid:
        return {
            "valid_examples": 0,
            "correct": 0.0,
            "accuracy_em": None,
            "accuracy_f1": None,
            "total_llm_calls": 0,
            "avg_calls_per_example": None,
            "correct_per_llm_call": None,
        }

    scored = [score(row) for row in valid]
    correct = sum(em for em, _ in scored)
    total_calls = sum(row.get("n_calls", 0) for row in valid)
    return {
        "valid_examples": len(valid),
        "correct": correct,
        "accuracy_em": round(correct / len(valid), 4),
        "accuracy_f1": round(sum(f1 for _, f1 in scored) / len(valid), 4),
        "total_llm_calls": total_calls,
        "avg_calls_per_example": round(total_calls / len(valid), 4),
        "correct_per_llm_call": round(correct / total_calls, 6) if total_calls else None,
    }


def audit_dataset(results_dir: Path, dataset: str) -> Dict:
    react_path = results_dir / "react.json"
    nexus_path = results_dir / "nexus.json"
    if not react_path.exists() or not nexus_path.exists():
        return {
            "dataset": dataset,
            "results_dir": str(results_dir),
            "status": "missing_results",
            "missing_files": [
                str(path) for path in (react_path, nexus_path) if not path.exists()
            ],
        }

    react_rows = load_json(react_path)
    nexus_rows = load_json(nexus_path)
    react_by_idx = successful_by_idx(react_rows)
    nexus_by_idx = successful_by_idx(nexus_rows)
    paired_indices = sorted(set(react_by_idx) & set(nexus_by_idx))

    disagreements = []
    counts = {
        "both_correct": 0,
        "react_only_correct": 0,
        "nexus_only_correct": 0,
        "both_wrong": 0,
    }
    for idx in paired_indices:
        react = react_by_idx[idx]
        nexus = nexus_by_idx[idx]
        react_em, react_f1 = score(react)
        nexus_em, nexus_f1 = score(nexus)

        if react_em and nexus_em:
            bucket = "both_correct"
        elif react_em:
            bucket = "react_only_correct"
        elif nexus_em:
            bucket = "nexus_only_correct"
        else:
            bucket = "both_wrong"
        counts[bucket] += 1

        if bucket != "both_correct":
            disagreements.append(
                {
                    "question_idx": idx,
                    "bucket": bucket,
                    "question": react.get("question_text") or nexus.get("question_text", ""),
                    "gt_answer": react.get("gt_answer") or nexus.get("gt_answer", ""),
                    "react": {
                        "answer": react.get("answer", ""),
                        "em": react_em,
                        "f1": round(react_f1, 4),
                        "n_calls": react.get("n_calls", 0),
                    },
                    "nexus": {
                        "answer": nexus.get("answer", ""),
                        "em": nexus_em,
                        "f1": round(nexus_f1, 4),
                        "n_calls": nexus.get("n_calls", 0),
                    },
                }
            )

    return {
        "dataset": dataset,
        "results_dir": str(results_dir),
        "status": "ok",
        "paired_examples": len(paired_indices),
        "react": framework_stats([react_by_idx[idx] for idx in paired_indices]),
        "nexus": framework_stats([nexus_by_idx[idx] for idx in paired_indices]),
        "audit_counts": counts,
        "disagreements": disagreements,
    }


def aggregate(dataset_reports: List[Dict]) -> Dict:
    ok_reports = [report for report in dataset_reports if report.get("status") == "ok"]
    totals = {
        "paired_examples": 0,
        "react_correct": 0.0,
        "nexus_correct": 0.0,
        "react_calls": 0,
        "nexus_calls": 0,
        "both_correct": 0,
        "react_only_correct": 0,
        "nexus_only_correct": 0,
        "both_wrong": 0,
    }
    for report in ok_reports:
        totals["paired_examples"] += report["paired_examples"]
        totals["react_correct"] += report["react"]["correct"]
        totals["nexus_correct"] += report["nexus"]["correct"]
        totals["react_calls"] += report["react"]["total_llm_calls"]
        totals["nexus_calls"] += report["nexus"]["total_llm_calls"]
        for key in ("both_correct", "react_only_correct", "nexus_only_correct", "both_wrong"):
            totals[key] += report["audit_counts"][key]

    n = totals["paired_examples"]
    return {
        **totals,
        "react_em": round(totals["react_correct"] / n, 4) if n else None,
        "nexus_em": round(totals["nexus_correct"] / n, 4) if n else None,
        "react_correct_per_call": (
            round(totals["react_correct"] / totals["react_calls"], 6)
            if totals["react_calls"]
            else None
        ),
        "nexus_correct_per_call": (
            round(totals["nexus_correct"] / totals["nexus_calls"], 6)
            if totals["nexus_calls"]
            else None
        ),
        "claim_status": (
            "supported_better_and_cheaper"
            if n
            and totals["nexus_correct"] > totals["react_correct"]
            and totals["nexus_calls"] < totals["react_calls"]
            else "not_supported_yet"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Audit finance paired-run results")
    parser.add_argument("--results-tag", default="all5-50-v1")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--datasets", nargs="+", default=DATASETS, choices=DATASETS)
    parser.add_argument("--results-base-dir", default="../../../results/finance")
    parser.add_argument("--protocol-id", default="finance_all5_50_v1")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    base_dir = (SCRIPT_DIR / args.results_base_dir).resolve()
    name = run_name(args.seed, args.model, args.results_tag)
    reports = [
        audit_dataset(base_dir / dataset / name, dataset)
        for dataset in args.datasets
    ]
    payload = {
        "protocol_id": args.protocol_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": args.model,
        "seed": args.seed,
        "results_tag": args.results_tag,
        "aggregate": aggregate(reports),
        "datasets": reports,
        "caveats": [
            "Cost is measured as answer-generation LLM calls, not provider tokens or dollars.",
            "Accuracy is rescored with the local finance-aware heuristic.",
            "Disagreements are candidates for manual scorer audit.",
        ],
    }

    output = Path(args.output) if args.output else base_dir / f"preliminary_all5_summary_50_{args.results_tag}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    print(json.dumps(payload["aggregate"], indent=2))
    print(f"[AUDIT] Wrote {output}")


if __name__ == "__main__":
    main()

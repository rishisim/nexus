"""Reproducible REALM 2026 fairness and trace-failure audit.

This script consumes only the saved ``finance_icaif26_v2`` development runs.
It never loads a dataset manifest or calls a model.  Its categories are
deterministic surface signals from saved answers, telemetry, and traces; they
are not human correctness labels or causal failure adjudications.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


AUDIT_VERSION = "realm2026-fairness-trace-audit-v1"
DEVELOPMENT_RUN = (
    "finance_icaif26_v2_development_google-gemini-2.5-flash_dev-20260709"
)
OBJECTIVE_DATASETS = ("financebench", "finqa", "tatqa", "convfinqa")
ALL_DATASETS = (*OBJECTIVE_DATASETS, "finder")
FRAMEWORKS = ("direct", "cot", "nexus", "react")
SAMPLE_SEED = "realm2026-both-wrong-v1"
BOTH_WRONG_PER_DATASET = 5
EXPECTED_ONE_SIDED = {"static_only": 42, "react_only": 10}

_ACTION_RE = re.compile(r"^\s*Action\s+(\d+)\s*:\s*(.+?)\s*$", re.MULTILINE)
_STATIC_SEARCH_RE = re.compile(r"\[Search:\s*(.*?)\]\s*\n")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<open>\()?\s*(?P<sign>[-+]?)\s*\$?\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<close>\))?\s*"
    r"(?P<scale>%|percent|hundred|thousand|million|billion)?",
    re.IGNORECASE,
)
_SCALES = {
    "": Decimal("1"),
    "%": Decimal("0.01"),
    "percent": Decimal("0.01"),
    "hundred": Decimal("100"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
}
_ABSTENTION_RE = re.compile(
    r"\b(?:unknown|insufficient|cannot determine|can't determine|not possible|"
    r"does not provide|need more information|unable to determine)\b",
    re.IGNORECASE,
)


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(str(text).encode("utf-8"))


def _file_hash(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _as_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _is_correct(row: Mapping[str, Any]) -> bool:
    score = (row.get("native_scores") or {}).get("exact_match", row.get("em"))
    try:
        return float(score) == 1.0
    except (TypeError, ValueError):
        return False


def _normalize_text(value: Any) -> str:
    text = _as_text(value).lower().replace(",", "")
    text = re.sub(r"[^a-z0-9.%+\-]+", " ", text)
    return " ".join(text.split())


def _numbers(value: Any) -> list[tuple[Decimal, Decimal, str]]:
    """Return ``(raw, scaled, token)`` triples for observable numeric tokens."""

    parsed: list[tuple[Decimal, Decimal, str]] = []
    for match in _NUMBER_RE.finditer(_as_text(value)):
        try:
            raw = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        if match.group("sign") == "-" or (match.group("open") and match.group("close")):
            raw = -abs(raw)
        scale = (match.group("scale") or "").lower()
        parsed.append((raw, raw * _SCALES[scale], match.group(0).strip()))
    return parsed


def _close(left: Decimal, right: Decimal) -> bool:
    difference = abs(left - right)
    if difference <= Decimal("0.000000001"):
        return True
    denominator = max(abs(right), Decimal("0.000001"))
    return difference / denominator <= Decimal("0.001")


def scorer_sensitive_candidate(prediction: Any, reference: Any) -> str | None:
    """Return a deterministic candidate reason, never a corrected score.

    The test is intentionally recall-oriented and therefore always triggers
    manual review.  It detects a normalized reference span or a reference
    number appearing in a longer/rounded prediction that the strict scorer
    rejected.  Presence is not semantic correctness.
    """

    prediction_text = _normalize_text(prediction)
    reference_text = _normalize_text(reference)
    reference_words = reference_text.split()
    if len(reference_text) >= 4 and len(reference_words) >= 2 and reference_text in prediction_text:
        return "normalized_reference_span_appears_in_prediction"

    prediction_numbers = _numbers(prediction)
    reference_numbers = _numbers(reference)
    for reference_raw, reference_scaled, _ in reference_numbers:
        for prediction_raw, prediction_scaled, _ in prediction_numbers:
            if prediction_raw == reference_raw:
                return "reference_numeric_value_appears_in_prediction"
            if prediction_scaled == reference_scaled:
                return "scale_normalized_reference_value_appears_in_prediction"
            if _close(prediction_raw, reference_raw) or _close(
                prediction_scaled, reference_scaled
            ):
                return "rounded_reference_numeric_value_appears_in_prediction"
    return None


def classify_failure(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify one scored-wrong result using observable deterministic rules."""

    if _is_correct(row):
        return {
            "signal": "none",
            "confidence": "high",
            "ambiguous": False,
            "manual_review_required": False,
            "rule_evidence": "dataset-native exact score is 1",
        }

    framework = str(row.get("framework") or "")
    trace = _as_text(row.get("raw_trace"))
    answer = _as_text(row.get("answer"))
    retrievals = int(row.get("retrieval_operation_count") or 0)
    calls = int(row.get("llm_call_count") or row.get("n_calls") or 0)
    actions = [(int(number), action) for number, action in _ACTION_RE.findall(trace)]

    if (
        framework == "react"
        and calls >= 7
        and any(number > 7 and action.lower().startswith("finish[unknown]") for number, action in actions)
    ):
        return {
            "signal": "forced_nontermination",
            "confidence": "high",
            "ambiguous": False,
            "manual_review_required": False,
            "rule_evidence": "seven model calls were followed by adapter-added Finish[UNKNOWN]",
        }
    if framework == "react" and retrievals == 0:
        return {
            "signal": "premature_finish_no_retrieval",
            "confidence": "high",
            "ambiguous": False,
            "manual_review_required": False,
            "rule_evidence": "ReAct finished after zero saved search/lookup operations",
        }

    candidate_reason = scorer_sensitive_candidate(answer, row.get("ground_truth"))
    if candidate_reason:
        return {
            "signal": "scorer_sensitive_candidate",
            "confidence": "medium",
            "ambiguous": True,
            "manual_review_required": True,
            "rule_evidence": candidate_reason,
        }
    if _ABSTENTION_RE.search(answer):
        return {
            "signal": "abstained_after_retrieval",
            "confidence": "high",
            "ambiguous": False,
            "manual_review_required": False,
            "rule_evidence": f"answer expressed abstention after {retrievals} retrieval operations",
        }
    if len(_numbers(answer)) >= 2 and re.search(r"[+*/]", answer) and "=" not in answer:
        return {
            "signal": "unexecuted_calculation",
            "confidence": "high",
            "ambiguous": False,
            "manual_review_required": False,
            "rule_evidence": "submitted answer is an arithmetic expression without an evaluated result",
        }
    return {
        "signal": "substantive_answer_mismatch",
        "confidence": "medium",
        "ambiguous": True,
        "manual_review_required": True,
        "rule_evidence": "non-abstaining answer was rejected and no narrower deterministic signal fired",
    }


def _trace_evidence(row: Mapping[str, Any]) -> Dict[str, Any]:
    trace = _as_text(row.get("raw_trace"))
    actions = [
        {"step": int(number), "action": action.strip()}
        for number, action in _ACTION_RE.findall(trace)
    ]
    excerpt = " ".join(trace.split())[-700:]
    signal = classify_failure(row)
    return {
        "answer": row.get("answer"),
        "correct_exact": _is_correct(row),
        "failure_signal": signal["signal"],
        "llm_calls": int(row.get("llm_call_count") or 0),
        "llm_attempts": int(row.get("llm_attempt_count") or 0),
        "retrieval_operations": int(row.get("retrieval_operation_count") or 0),
        "retry_count": int(row.get("retry_count") or 0),
        "actions": actions,
        "static_search_queries": _STATIC_SEARCH_RE.findall(trace),
        "trace_excerpt": excerpt,
        "trace_sha256": _sha256_text(trace),
        "signal_rule_evidence": signal["rule_evidence"],
    }


def _sample_hash(dataset: str, example_id: str) -> str:
    return hashlib.sha256(f"{SAMPLE_SEED}:{dataset}:{example_id}".encode("utf-8")).hexdigest()


def frozen_both_wrong_sample(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    dataset: str,
    count: int = BOTH_WRONG_PER_DATASET,
) -> list[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    candidates = [
        (_sample_hash(dataset, str(static["example_id"])), static, react)
        for static, react in pairs
        if not _is_correct(static) and not _is_correct(react)
    ]
    return sorted(candidates, key=lambda item: (item[0], str(item[1]["example_id"])))[:count]


def _combine_classification(
    pattern: str, static: Mapping[str, Any], react: Mapping[str, Any]
) -> Dict[str, Any]:
    static_signal = classify_failure(static)
    react_signal = classify_failure(react)
    if pattern == "static_only":
        return react_signal
    if pattern == "react_only":
        return static_signal
    if static_signal["signal"] == react_signal["signal"]:
        return static_signal
    return {
        "signal": "mixed_or_ambiguous",
        "confidence": "low",
        "ambiguous": True,
        "manual_review_required": True,
        "rule_evidence": (
            f"Static signal={static_signal['signal']}; ReAct signal={react_signal['signal']}"
        ),
    }


def _make_trace_item(
    dataset: str,
    static: Mapping[str, Any],
    react: Mapping[str, Any],
    pattern: str,
    selection: str,
    sample_rank_hash: str | None = None,
) -> Dict[str, Any]:
    classification = _combine_classification(pattern, static, react)
    return {
        "item_id": f"{dataset}:{static['example_id']}",
        "dataset": dataset,
        "example_id": str(static["example_id"]),
        "selection": selection,
        "sample_rank_hash": sample_rank_hash,
        "correctness_pattern": pattern,
        "ground_truth": static.get("ground_truth"),
        "category": classification["signal"],
        "confidence": classification["confidence"],
        "ambiguity": classification["ambiguous"],
        "manual_review_required": classification["manual_review_required"],
        "label_source": "deterministic_trace_rule_v1",
        "classification_evidence": classification["rule_evidence"],
        "trace_evidence": {
            "static_nexus": _trace_evidence(static),
            "react": _trace_evidence(react),
        },
    }


def _development_dir(repo_root: Path, dataset: str) -> Path:
    path = repo_root / "results" / "finance" / dataset / DEVELOPMENT_RUN
    if any("final" in part.lower() for part in path.parts) or "development" not in path.name.lower():
        raise ValueError(f"Audit input must be an explicit development run: {path}")
    return path


def _load_rows(path: Path) -> list[Dict[str, Any]]:
    if any("final" in part.lower() for part in path.parts):
        raise ValueError(f"Refusing sealed-final path: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected list in {path}")
    return [dict(row) for row in payload]


def _load_dataset_results(repo_root: Path, dataset: str) -> Dict[str, list[Dict[str, Any]]]:
    run_dir = _development_dir(repo_root, dataset)
    results = {
        framework: _load_rows(run_dir / framework / "results.json")
        for framework in FRAMEWORKS
    }
    expected_ids: set[str] | None = None
    for framework, rows in results.items():
        if len(rows) != 50:
            raise ValueError(f"{dataset}/{framework}: expected 50 development rows")
        identifiers = [str(row.get("example_id")) for row in rows]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError(f"{dataset}/{framework}: duplicate example ids")
        if any(row.get("status") != "success" for row in rows):
            raise ValueError(f"{dataset}/{framework}: non-success result present")
        if expected_ids is None:
            expected_ids = set(identifiers)
        elif set(identifiers) != expected_ids:
            raise ValueError(f"{dataset}/{framework}: unpaired development ids")
    return results


def _pair(static: Sequence[Mapping[str, Any]], react: Sequence[Mapping[str, Any]]):
    react_by_id = {str(row["example_id"]): row for row in react}
    return [(row, react_by_id[str(row["example_id"])]) for row in static]


def _observed_telemetry(
    results: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for dataset in ALL_DATASETS:
        summary[dataset] = {}
        for framework in FRAMEWORKS:
            rows = results[dataset][framework]
            calls = sum(int(row.get("llm_call_count") or 0) for row in rows)
            call_records = sum(len(row.get("call_records") or []) for row in rows)
            summary[dataset][framework] = {
                "examples": len(rows),
                "llm_calls": calls,
                "llm_calls_per_example": round(calls / len(rows), 4),
                "llm_attempts": sum(int(row.get("llm_attempt_count") or 0) for row in rows),
                "retrieval_operations": sum(
                    int(row.get("retrieval_operation_count") or 0) for row in rows
                ),
                "retries": sum(int(row.get("retry_count") or 0) for row in rows),
                "statuses": sorted({str(row.get("status")) for row in rows}),
                "requested_models": sorted({str(row.get("requested_model")) for row in rows}),
                "resolved_models": sorted({str(row.get("resolved_model")) for row in rows}),
                "telemetry_call_record_coverage": (
                    round(call_records / calls, 6) if calls else None
                ),
                "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
                "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
            }
    return summary


def _fairness_matrix() -> list[Dict[str, str]]:
    return [
        {
            "dimension": "controlled_evidence_access",
            "assessment": "equivalent_source",
            "evidence": "All methods use the same dataset adapter and controlled evidence packet; external retrieval and calculators are disabled.",
        },
        {
            "dimension": "retrieval_api_and_policy",
            "assessment": "shared_api_different_policy",
            "evidence": "All methods share Search/Lookup environment semantics, but Direct/CoT use one Search, Static uses up to three deterministic Searches, and ReAct adaptively selects Search/Lookup operations.",
        },
        {
            "dimension": "model_binding_and_sampling",
            "assessment": "equivalent",
            "evidence": "Every saved row requests and resolves google/gemini-2.5-flash; single-trace calls use temperature 0 and protocol thinking budget 0.",
        },
        {
            "dimension": "prompts_and_answer_contract",
            "assessment": "method_specific_with_output_asymmetry",
            "evidence": "Direct/CoT/Static explicitly require a short final Answer line; ReAct requests Finish[answer] but does not require a short, number-only final answer.",
        },
        {
            "dimension": "step_and_call_limits",
            "assessment": "intentionally_not_equal",
            "evidence": "Direct/CoT/Static receive one 768-output-token call; ReAct receives up to seven 512-output-token calls.",
        },
        {
            "dimension": "context_and_evidence_budget",
            "assessment": "not_equivalent_and_incompletely_enforced",
            "evidence": "The 4096-token dossier cap is applied before one-call prompts, but ReAct's growing transcript is not truncated during inference; its dossier is truncated only when saved after the episode.",
        },
        {
            "dimension": "retry_policy",
            "assessment": "equivalent",
            "evidence": "All calls share the five-attempt transport-only retry policy; observed development retry_count is zero for every audited row.",
        },
        {
            "dimension": "scorer_behavior",
            "assessment": "same_scorer_with_prompt_interaction",
            "evidence": "Dataset-native scorers are applied framework-blind after generation, but reject ambiguous multi-number or verbose answers; method-specific answer contracts therefore interact with exact correctness.",
        },
        {
            "dimension": "telemetry",
            "assessment": "complete_calls_but_missing_method_diagnostics",
            "evidence": "Saved rows contain per-call tokens, latency, cost, retries, requested/resolved model, and raw traces; runner serialization drops method-layer n_badcalls, dossier_truncated, and explicit termination reason.",
        },
        {
            "dimension": "malformed_and_nontermination_handling",
            "assessment": "asymmetric",
            "evidence": "A malformed ReAct action becomes immediate Finish[UNKNOWN], and step exhaustion adds Finish[UNKNOWN]; a one-call output missing Answer falls back to its last non-empty line. Valid but malformed outputs are not retried.",
        },
        {
            "dimension": "artifact_freeze_and_run_provenance",
            "assessment": "incomplete",
            "evidence": "The protocol is foundation_unfrozen with null prompt/scorer hashes. Config files were updated by the later Selective run, while run_history preserves the original four-framework run.",
        },
    ]


def _input_hashes(repo_root: Path) -> Dict[str, str]:
    relative_paths = [
        Path("src/agents/finance/audit_realm_fairness.py"),
        Path("src/agents/finance/protocols/finance_icaif26_v2.json"),
        Path("src/agents/finance/finance_methods.py"),
        Path("src/agents/finance/method_prompts.py"),
        Path("src/agents/finance/run_finance_experiments.py"),
        Path("src/agents/finance/finance_scoring.py"),
    ]
    for dataset in ALL_DATASETS:
        run = Path("results/finance") / dataset / DEVELOPMENT_RUN
        relative_paths.extend(
            [
                run / framework / "results.json"
                for framework in FRAMEWORKS
            ]
        )
        relative_paths.extend([run / "config.json", run / "run_history.json", run / "model_snapshot.json"])
    return {
        path.as_posix(): _file_hash(repo_root / path)
        for path in sorted(relative_paths, key=lambda item: item.as_posix())
    }


def _counts(items: Sequence[Mapping[str, Any]], key: str) -> Dict[str, int]:
    return dict(sorted(Counter(str(item[key]) for item in items).items()))


def build_audit(repo_root: Path, *, enforce_expected: bool = True) -> Dict[str, Any]:
    repo_root = repo_root.resolve()
    results = {
        dataset: _load_dataset_results(repo_root, dataset) for dataset in ALL_DATASETS
    }
    trace_items: list[Dict[str, Any]] = []
    one_sided_counts: Counter[str] = Counter()
    both_wrong_population: Dict[str, int] = {}

    for dataset in OBJECTIVE_DATASETS:
        pairs = _pair(results[dataset]["nexus"], results[dataset]["react"])
        both_wrong_population[dataset] = sum(
            not _is_correct(static) and not _is_correct(react) for static, react in pairs
        )
        for static, react in pairs:
            static_correct = _is_correct(static)
            react_correct = _is_correct(react)
            if static_correct == react_correct:
                continue
            pattern = "static_only" if static_correct else "react_only"
            one_sided_counts[pattern] += 1
            trace_items.append(
                _make_trace_item(dataset, static, react, pattern, "one_sided")
            )
        for rank_hash, static, react in frozen_both_wrong_sample(pairs, dataset):
            trace_items.append(
                _make_trace_item(
                    dataset,
                    static,
                    react,
                    "both_wrong",
                    "both_wrong_frozen_sample",
                    sample_rank_hash=rank_hash,
                )
            )

    if enforce_expected and dict(one_sided_counts) != EXPECTED_ONE_SIDED:
        raise ValueError(
            f"One-sided disagreement drift: {dict(one_sided_counts)} != {EXPECTED_ONE_SIDED}"
        )
    trace_items.sort(
        key=lambda item: (
            OBJECTIVE_DATASETS.index(str(item["dataset"])),
            0 if item["selection"] == "one_sided" else 1,
            str(item["example_id"]),
        )
    )
    manual_items = [item for item in trace_items if item["manual_review_required"]]
    return {
        "schema_version": AUDIT_VERSION,
        "scope": {
            "partition": "development_only",
            "development_examples": 250,
            "objective_trace_examples": 200,
            "objective_datasets": list(OBJECTIVE_DATASETS),
            "secondary_dataset": "finder",
            "frameworks": list(FRAMEWORKS),
            "sealed_final_partition_accessed": False,
            "external_provider_calls": 0,
        },
        "provenance": {
            "development_run": DEVELOPMENT_RUN,
            "input_sha256": _input_hashes(repo_root),
            "labels": "deterministic trace rules; not human validation",
        },
        "fairness_matrix": _fairness_matrix(),
        "observed_telemetry": _observed_telemetry(results),
        "taxonomy": {
            "forced_nontermination": "Adapter forced UNKNOWN after all seven ReAct model steps.",
            "premature_finish_no_retrieval": "ReAct finished without any saved Search or Lookup.",
            "abstained_after_retrieval": "The submitted answer explicitly abstained after at least one retrieval.",
            "unexecuted_calculation": "The submitted answer was an unevaluated arithmetic expression.",
            "scorer_sensitive_candidate": "A rejected answer contains a normalized reference span/value; author review is required and no score is changed.",
            "substantive_answer_mismatch": "A rejected non-abstaining answer has no narrower deterministic signal; causal attribution requires review.",
            "mixed_or_ambiguous": "Both-wrong systems expose different deterministic signals.",
        },
        "sampling": {
            "population": "Static Nexus and ReAct both exact-wrong on objective development examples",
            "seed": SAMPLE_SEED,
            "rank": "ascending SHA-256(seed:dataset:example_id), then example_id",
            "per_dataset": BOTH_WRONG_PER_DATASET,
            "both_wrong_population_by_dataset": both_wrong_population,
            "sample_size": len(trace_items) - sum(one_sided_counts.values()),
        },
        "summary": {
            "one_sided": dict(sorted(one_sided_counts.items())),
            "trace_item_count": len(trace_items),
            "selection_counts": _counts(trace_items, "selection"),
            "category_counts": _counts(trace_items, "category"),
            "category_counts_one_sided": _counts(
                [item for item in trace_items if item["selection"] == "one_sided"],
                "category",
            ),
            "manual_review_count": len(manual_items),
            "manual_review_item_ids": [item["item_id"] for item in manual_items],
        },
        "trace_items": trace_items,
        "limitations": [
            "Categories are deterministic surface signals, not human-validated correctness or causal diagnoses.",
            "Scorer-sensitive candidates are deliberately over-inclusive and do not alter official scores.",
            "Saved success records omit n_badcalls, dossier truncation, and explicit termination reason, limiting malformed-action reconstruction.",
            "The both-wrong audit is a frozen 20-item sample, not the full both-wrong population.",
            "The audit cannot reconstruct provider-side context-window truncation or tokenization from aggregate telemetry.",
        ],
    }


CSV_COLUMNS = (
    "item_id",
    "dataset",
    "example_id",
    "selection",
    "sample_rank_hash",
    "correctness_pattern",
    "ground_truth",
    "category",
    "confidence",
    "ambiguity",
    "manual_review_required",
    "label_source",
    "classification_evidence",
    "static_answer",
    "static_correct_exact",
    "static_failure_signal",
    "static_llm_calls",
    "static_retrieval_operations",
    "static_trace_sha256",
    "static_search_queries",
    "react_answer",
    "react_correct_exact",
    "react_failure_signal",
    "react_llm_calls",
    "react_retrieval_operations",
    "react_trace_sha256",
    "react_actions",
)


def audit_csv(audit: Mapping[str, Any]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in audit["trace_items"]:
        static = item["trace_evidence"]["static_nexus"]
        react = item["trace_evidence"]["react"]
        writer.writerow(
            {
                "item_id": item["item_id"],
                "dataset": item["dataset"],
                "example_id": item["example_id"],
                "selection": item["selection"],
                "sample_rank_hash": item["sample_rank_hash"] or "",
                "correctness_pattern": item["correctness_pattern"],
                "ground_truth": _as_text(item["ground_truth"]),
                "category": item["category"],
                "confidence": item["confidence"],
                "ambiguity": str(item["ambiguity"]).lower(),
                "manual_review_required": str(item["manual_review_required"]).lower(),
                "label_source": item["label_source"],
                "classification_evidence": item["classification_evidence"],
                "static_answer": _as_text(static["answer"]),
                "static_correct_exact": str(static["correct_exact"]).lower(),
                "static_failure_signal": static["failure_signal"],
                "static_llm_calls": static["llm_calls"],
                "static_retrieval_operations": static["retrieval_operations"],
                "static_trace_sha256": static["trace_sha256"],
                "static_search_queries": json.dumps(static["static_search_queries"], ensure_ascii=False),
                "react_answer": _as_text(react["answer"]),
                "react_correct_exact": str(react["correct_exact"]).lower(),
                "react_failure_signal": react["failure_signal"],
                "react_llm_calls": react["llm_calls"],
                "react_retrieval_operations": react["retrieval_operations"],
                "react_trace_sha256": react["trace_sha256"],
                "react_actions": json.dumps(react["actions"], ensure_ascii=False),
            }
        )
    return stream.getvalue()


def _check_or_write(path: Path, content: str, check: bool) -> None:
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            raise SystemExit(f"Audit artifact is stale: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("paper/realm2026/artifacts/fairness_audit.json"),
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=Path("paper/realm2026/artifacts/fairness_audit.csv"),
    )
    parser.add_argument("--check", action="store_true", help="fail if committed artifacts are stale")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    json_out = args.json_out if args.json_out.is_absolute() else repo_root / args.json_out
    csv_out = args.csv_out if args.csv_out.is_absolute() else repo_root / args.csv_out
    audit = build_audit(repo_root)
    _check_or_write(json_out, _stable_json(audit), args.check)
    _check_or_write(csv_out, audit_csv(audit), args.check)
    if not args.check:
        print(
            f"Wrote {len(audit['trace_items'])} development-only trace items "
            f"({audit['summary']['manual_review_count']} require manual review)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

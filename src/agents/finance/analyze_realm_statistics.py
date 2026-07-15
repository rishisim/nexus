"""Recompute paired REALM development statistics from raw per-example rows.

This analysis is intentionally development-only. It reads one explicitly named
``*_development_*`` result directory per dataset and never discovers or opens
final-partition outputs. All paired joins are by ``example_id`` and fail
loudly on duplicate, missing, or misaligned records.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

if __package__ in (None, ""):
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.agents.finance.finance_statistics import (  # type: ignore
        exact_mcnemar,
        paired_bootstrap_ci,
        stratified_paired_bootstrap_ci,
    )
else:
    from .finance_statistics import (
        exact_mcnemar,
        paired_bootstrap_ci,
        stratified_paired_bootstrap_ci,
    )


ALL_DATASETS = ("financebench", "finder", "finqa", "tatqa", "convfinqa")
PRIMARY_DATASETS = ("finqa", "tatqa", "convfinqa")
ROUTER_DATASETS = ("financebench", "finqa", "tatqa", "convfinqa")
FRAMEWORKS = ("direct", "cot", "nexus", "react", "selective")
DISPLAY_NAMES = {
    "direct": "Direct",
    "cot": "CoT/PoT",
    "nexus": "Static Nexus",
    "react": "ReAct",
    "selective": "Selective Nexus",
}
PRIMARY_METRICS = {"finqa": "exact_match", "tatqa": "f1", "convfinqa": "exact_match"}
ROUTER_METRIC = "exact_match"
DEFAULT_MODEL = "google/gemini-2.5-flash"
DEFAULT_TAG = "dev-20260709"
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_SEED = 20260709


class AnalysisError(ValueError):
    """Raised when development outputs violate an analysis invariant."""


def _slug(model_id: str) -> str:
    return model_id.replace("/", "-").replace(":", "-")


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(f"{label} must be numeric, found {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise AnalysisError(f"{label} must be finite")
    return number


def _optional_number(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value: Any = row
        found = True
        for part in name.split("."):
            if not isinstance(value, Mapping) or part not in value:
                found = False
                break
            value = value[part]
        if found and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if math.isfinite(number):
                return number
    return None


def _score(row: Mapping[str, Any], metric: str, label: str) -> float:
    scores = row.get("native_scores")
    if not isinstance(scores, Mapping) or scores.get(metric) is None:
        raise AnalysisError(f"{label}: missing native_scores.{metric}")
    value = _finite(scores[metric], f"{label}.native_scores.{metric}")
    if metric == "exact_match" and value not in (0.0, 1.0):
        raise AnalysisError(f"{label}: exact_match must be binary, found {value}")
    return value


def _optional_score(row: Mapping[str, Any], metric: str) -> float | None:
    scores = row.get("native_scores")
    if not isinstance(scores, Mapping) or scores.get(metric) is None:
        return None
    return _finite(scores[metric], f"native_scores.{metric}")


def _effective_cost(row: Mapping[str, Any]) -> Tuple[float | None, str]:
    provider = _optional_number(row, "provider_cost_usd", "telemetry.provider_cost_usd")
    estimated = _optional_number(row, "estimated_cost_usd", "telemetry.estimated_cost_usd")
    if provider is not None:
        if provider < 0:
            raise AnalysisError("provider cost cannot be negative")
        return provider, "provider"
    if estimated is not None:
        if estimated < 0:
            raise AnalysisError("estimated cost cannot be negative")
        return estimated, "estimated"
    return None, "missing"


def _provider_failure(row: Mapping[str, Any]) -> bool:
    if row.get("status") != "success":
        return True
    records = row.get("call_records") or []
    if not isinstance(records, list):
        return True
    for record in records:
        if not isinstance(record, Mapping):
            return True
        if record.get("status") not in (None, "ok", "success"):
            return True
        if record.get("error_type"):
            return True
    return False


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalysisError(f"Missing required development artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"Invalid JSON in {path}: {exc}") from exc


def _validate_framework_rows(
    dataset: str,
    framework: str,
    rows: Any,
    *,
    expected_count: int = 50,
) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        raise AnalysisError(f"{dataset}/{framework}: results.json must contain a list")
    if len(rows) != expected_count:
        raise AnalysisError(
            f"{dataset}/{framework}: expected {expected_count} development rows, found {len(rows)}"
        )
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise AnalysisError(f"{dataset}/{framework}[{position}] is not an object")
        example_id = str(row.get("example_id", ""))
        if not example_id:
            raise AnalysisError(f"{dataset}/{framework}[{position}] has no example_id")
        if example_id in seen:
            raise AnalysisError(f"{dataset}/{framework}: duplicate example_id={example_id}")
        seen.add(example_id)
        if row.get("dataset") not in (None, dataset):
            raise AnalysisError(
                f"{dataset}/{framework}/{example_id}: dataset field is {row.get('dataset')!r}"
            )
        if row.get("framework") not in (None, framework):
            raise AnalysisError(
                f"{dataset}/{framework}/{example_id}: framework field is {row.get('framework')!r}"
            )
        output.append(dict(row))
    return output


def load_development_runs(
    results_root: Path,
    *,
    model_id: str = DEFAULT_MODEL,
    results_tag: str = DEFAULT_TAG,
    protocol_id: str = "finance_icaif26_v2",
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Load and validate only the named development result directories."""

    run_name = f"finance_icaif26_v2_development_{_slug(model_id)}_{results_tag}"
    if "final" in run_name.lower() or "_development_" not in run_name:
        raise AnalysisError(f"Refusing non-development run name: {run_name}")
    runs: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for dataset in ALL_DATASETS:
        run_dir = results_root / dataset / run_name
        if "final" in str(run_dir).lower():
            raise AnalysisError(f"Refusing path containing final partition: {run_dir}")
        config_path = run_dir / "config.json"
        config = _load_json(config_path)
        if isinstance(config, Mapping):
            if config.get("partition") not in (None, "development"):
                raise AnalysisError(f"{run_dir}: config is not development")
            if config.get("protocol_id") not in (None, protocol_id):
                raise AnalysisError(f"{run_dir}: protocol mismatch")
        framework_rows = {}
        for framework in FRAMEWORKS:
            framework_rows[framework] = _validate_framework_rows(
                dataset,
                framework,
                _load_json(run_dir / framework / "results.json"),
            )
        expected_ids = {str(row["example_id"]) for row in framework_rows[FRAMEWORKS[0]]}
        for framework, rows in framework_rows.items():
            ids = {str(row["example_id"]) for row in rows}
            if ids != expected_ids:
                raise AnalysisError(
                    f"{dataset}: {framework} is not paired with direct; "
                    f"missing={sorted(expected_ids - ids)}, extra={sorted(ids - expected_ids)}"
                )
            for row in rows:
                if row.get("protocol_id") not in (None, protocol_id):
                    raise AnalysisError(
                        f"{dataset}/{framework}/{row['example_id']}: protocol mismatch"
                    )
        runs[dataset] = framework_rows
    return runs


def _index(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    indexed: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = str(row["example_id"])
        if key in indexed:
            raise AnalysisError(f"duplicate paired key while indexing: {key}")
        indexed[key] = row
    return indexed


def _paired_rows(
    left_rows: Sequence[Mapping[str, Any]], right_rows: Sequence[Mapping[str, Any]]
) -> List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    left, right = _index(left_rows), _index(right_rows)
    if set(left) != set(right):
        raise AnalysisError(
            "paired records are misaligned: "
            f"missing_right={sorted(set(left) - set(right))}, "
            f"missing_left={sorted(set(right) - set(left))}"
        )
    return [(key, left[key], right[key]) for key in sorted(left)]


def _cohen_dz(differences: Sequence[float]) -> float | None:
    if len(differences) < 2:
        return None
    sd = statistics.stdev(differences)
    return statistics.mean(differences) / sd if sd else None


def _pairwise_quality(
    dataset: str,
    metric: str,
    left_name: str,
    right_name: str,
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    n_resamples: int,
) -> Dict[str, Any]:
    pairs = _paired_rows(left_rows, right_rows)
    left_values = [
        _score(left, metric, f"{dataset}/{left_name}/{example_id}")
        for example_id, left, _ in pairs
    ]
    right_values = [
        _score(right, metric, f"{dataset}/{right_name}/{example_id}")
        for example_id, _, right in pairs
    ]
    differences = [right - left for left, right in zip(left_values, right_values)]
    bootstrap = paired_bootstrap_ci(
        left_values, right_values, n_resamples=n_resamples, seed=seed
    )
    record: Dict[str, Any] = {
        "dataset": dataset,
        "metric": metric,
        "left": left_name,
        "right": right_name,
        "n_pairs": len(pairs),
        "denominator": f"{len(pairs)} paired development examples",
        "left_mean": statistics.mean(left_values),
        "right_mean": statistics.mean(right_values),
        "difference_right_minus_left": statistics.mean(differences),
        "cohen_dz": _cohen_dz(differences),
        "bootstrap_ci": bootstrap.to_dict(),
    }
    if metric == "exact_match":
        record["paired_test"] = {
            "name": "exact_two_sided_mcnemar",
            **exact_mcnemar(left_values, right_values).to_dict(),
        }
    else:
        record["paired_test"] = {
            "name": "not_applicable",
            "reason": "primary TAT-QA metric is continuous official F1, not binary correctness",
        }
    return record


def _primary_macro_pair(
    runs: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    left_name: str,
    right_name: str,
    *,
    seed: int,
    n_resamples: int,
) -> Dict[str, Any]:
    left_by_dataset: Dict[str, List[float]] = {}
    right_by_dataset: Dict[str, List[float]] = {}
    per_dataset: Dict[str, Dict[str, float]] = {}
    for dataset in PRIMARY_DATASETS:
        metric = PRIMARY_METRICS[dataset]
        pairs = _paired_rows(runs[dataset][left_name], runs[dataset][right_name])
        left_values = [
            _score(left, metric, f"{dataset}/{left_name}/{example_id}")
            for example_id, left, _ in pairs
        ]
        right_values = [
            _score(right, metric, f"{dataset}/{right_name}/{example_id}")
            for example_id, _, right in pairs
        ]
        left_by_dataset[dataset] = left_values
        right_by_dataset[dataset] = right_values
        per_dataset[dataset] = {
            "metric": metric,
            "n_pairs": len(pairs),
            "left_mean": statistics.mean(left_values),
            "right_mean": statistics.mean(right_values),
            "difference_right_minus_left": statistics.mean(
                right - left for left, right in zip(left_values, right_values)
            ),
        }
    bootstrap = stratified_paired_bootstrap_ci(
        left_by_dataset,
        right_by_dataset,
        n_resamples=n_resamples,
        seed=seed,
    )
    all_differences = [
        right - left
        for dataset in PRIMARY_DATASETS
        for left, right in zip(left_by_dataset[dataset], right_by_dataset[dataset])
    ]
    return {
        "scope": "primary_macro",
        "left": left_name,
        "right": right_name,
        "metric": "unweighted macro of FinQA exact_match, TAT-QA F1, ConvFinQA exact_match",
        "datasets": list(PRIMARY_DATASETS),
        "stratum_sizes": {dataset: len(left_by_dataset[dataset]) for dataset in PRIMARY_DATASETS},
        "n_pairs": sum(len(values) for values in left_by_dataset.values()),
        "denominator": "three equally weighted dataset means; 50 paired development examples per dataset",
        "left_macro": statistics.mean(
            per_dataset[dataset]["left_mean"] for dataset in PRIMARY_DATASETS
        ),
        "right_macro": statistics.mean(
            per_dataset[dataset]["right_mean"] for dataset in PRIMARY_DATASETS
        ),
        "difference_right_minus_left": bootstrap.estimate,
        "cohen_dz_over_micro_pairs": _cohen_dz(all_differences),
        "per_dataset": per_dataset,
        "stratified_bootstrap_ci": bootstrap.to_dict(),
    }


def _efficiency_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    status_counts = Counter(str(row.get("status", "missing")) for row in rows)
    successful = [row for row in rows if row.get("status") == "success"]
    token_fields = ("input_tokens", "output_tokens", "total_tokens")
    token_totals: Dict[str, float] = {}
    token_coverage: Dict[str, int] = {}
    for field in token_fields:
        values = [_optional_number(row, field, f"telemetry.{field}") for row in rows]
        available = [value for value in values if value is not None]
        token_totals[field] = sum(available)
        token_coverage[field] = len(available)

    call_values = [_optional_number(row, "llm_call_count", "n_calls", "telemetry.llm_call_count") for row in rows]
    call_available = [value for value in call_values if value is not None]
    retrieval_values = [
        _optional_number(row, "retrieval_operation_count", "retrieval_calls", "telemetry.retrieval_call_count")
        for row in rows
    ]
    retrieval_available = [value for value in retrieval_values if value is not None]
    costs, sources = [], []
    for row in rows:
        cost, source = _effective_cost(row)
        if cost is not None:
            costs.append(cost)
        sources.append(source)
    successful_latencies = [
        _optional_number(row, "latency_ms", "telemetry.latency_ms")
        for row in successful
    ]
    successful_latencies = [value for value in successful_latencies if value is not None]
    latency_sorted = sorted(successful_latencies)
    missingness_fields = (
        "resolved_model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "llm_call_count",
        "latency_ms",
        "provider_cost_usd",
        "estimated_cost_usd",
        "route_selected",
    )
    missingness = {
        field: {
            "missing_examples": sum(
                _optional_number(row, field, f"telemetry.{field}") is None
                if field not in ("resolved_model", "route_selected")
                else row.get(field) in (None, "")
                for row in rows
            ),
            "denominator": n,
        }
        for field in missingness_fields
    }
    return {
        "input_rows": n,
        "successful_rows": len(successful),
        "failed_rows": n - len(successful),
        "provider_failure_examples": sum(_provider_failure(row) for row in rows),
        "status_counts": dict(sorted(status_counts.items())),
        "answer_calls_total": int(sum(call_available)),
        "answer_calls_per_input_example": sum(call_available) / n if n else None,
        "answer_call_coverage": len(call_available) / n if n else None,
        "retrieval_operations_total": int(sum(retrieval_available)),
        "token_totals": token_totals,
        "token_coverage": token_coverage,
        "token_per_input_example": {
            field: token_totals[field] / n if n and token_coverage[field] == n else None
            for field in token_fields
        },
        "cost_total_usd": sum(costs),
        "usd_per_example": statistics.mean(costs) if len(costs) == n and n else None,
        "observed_cost_per_input_example": sum(costs) / n if n else None,
        "cost_coverage": len(costs) / n if n else None,
        "price_source_counts": dict(sorted(Counter(sources).items())),
        "latency_median_ms": statistics.median(successful_latencies) if successful_latencies else None,
        "latency_p95_ms": (
            _percentile(latency_sorted, 0.95) if successful_latencies else None
        ),
        "latency_available_successful_examples": len(successful_latencies),
        "latency_denominator_successful_examples": len(successful),
        "missingness": missingness,
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise AnalysisError("cannot compute percentile of empty sequence")
    position = probability * (len(values) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] + fraction * (values[upper] - values[lower])


def _efficiency_all_rows(
    runs: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    datasets: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    return {
        framework: _efficiency_summary(
            [row for dataset in datasets for row in runs[dataset][framework]]
        )
        for framework in FRAMEWORKS
    }


def _complementarity(
    runs: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
) -> Dict[str, Any]:
    by_dataset: Dict[str, Any] = {}
    totals = Counter()
    for dataset in ROUTER_DATASETS:
        pairs = _paired_rows(runs[dataset]["nexus"], runs[dataset]["react"])
        counts = Counter()
        for example_id, static, react in pairs:
            static_correct = _score(static, ROUTER_METRIC, f"{dataset}/nexus/{example_id}") == 1.0
            react_correct = _score(react, ROUTER_METRIC, f"{dataset}/react/{example_id}") == 1.0
            if static_correct and react_correct:
                counts["both_correct"] += 1
            elif static_correct:
                counts["static_only_correct"] += 1
            elif react_correct:
                counts["react_only_correct"] += 1
            else:
                counts["both_wrong"] += 1
        n = len(pairs)
        for key in ("both_correct", "static_only_correct", "react_only_correct", "both_wrong"):
            counts[key] += 0
            totals[key] += counts[key]
        union = counts["both_correct"] + counts["static_only_correct"] + counts["react_only_correct"]
        by_dataset[dataset] = {
            "metric": ROUTER_METRIC,
            "n_pairs": n,
            "denominator": f"{n} paired objective routing development examples",
            **dict(counts),
            "static_accuracy": (counts["both_correct"] + counts["static_only_correct"]) / n,
            "react_accuracy": (counts["both_correct"] + counts["react_only_correct"]) / n,
            "oracle_accuracy": union / n,
            "oracle_headroom_over_static": counts["react_only_correct"] / n,
        }
    n = sum(by_dataset[dataset]["n_pairs"] for dataset in ROUTER_DATASETS)
    union = totals["both_correct"] + totals["static_only_correct"] + totals["react_only_correct"]
    selective_rows = [row for dataset in ROUTER_DATASETS for row in runs[dataset]["selective"]]
    selective_scores = [
        _score(row, ROUTER_METRIC, f"{row.get('dataset')}/selective/{row['example_id']}")
        for row in selective_rows
    ]
    route_values = [row.get("route_selected") for row in selective_rows]
    missing_route = sum(value in (None, "") for value in route_values)
    static_rows = [row for dataset in ROUTER_DATASETS for row in runs[dataset]["nexus"]]
    static_scores = [
        _score(row, ROUTER_METRIC, f"{row.get('dataset')}/nexus/{row['example_id']}")
        for row in static_rows
    ]
    selective_costs = [_effective_cost(row)[0] for row in selective_rows]
    if any(value is None for value in selective_costs):
        selective_cost = None
    else:
        selective_cost = statistics.mean(value for value in selective_costs if value is not None)
    return {
        "by_dataset": by_dataset,
        "aggregate": {
            "metric": ROUTER_METRIC,
            "n_pairs": n,
            "denominator": f"{n} paired objective routing development examples",
            **dict(totals),
            "static_accuracy": (totals["both_correct"] + totals["static_only_correct"]) / n,
            "react_accuracy": (totals["both_correct"] + totals["react_only_correct"]) / n,
            "oracle_accuracy": union / n,
            "oracle_headroom_over_static": totals["react_only_correct"] / n,
            "always_static_accuracy": statistics.mean(static_scores),
            "selective_observed_accuracy": statistics.mean(selective_scores),
            "selective_observed_cost_per_example_usd": selective_cost,
            "selective_observed_escalation_rate": (
                sum(value == "react" for value in route_values) / n if missing_route == 0 else None
            ),
            "selective_route_counts": dict(sorted(Counter(route_values).items(), key=lambda item: str(item[0]))),
            "selective_route_missing_examples": missing_route,
        },
    }


def _primary_headlines(
    runs: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> Dict[str, Any]:
    macro: Dict[str, float] = {}
    cost: Dict[str, float] = {}
    per_dataset: Dict[str, Dict[str, Dict[str, float]]] = {}
    for dataset in PRIMARY_DATASETS:
        per_dataset[dataset] = {}
        metric = PRIMARY_METRICS[dataset]
        for framework in FRAMEWORKS:
            values = [
                _score(row, metric, f"{dataset}/{framework}/{row['example_id']}")
                for row in runs[dataset][framework]
            ]
            costs = [_effective_cost(row)[0] for row in runs[dataset][framework]]
            if any(value is None for value in costs):
                raise AnalysisError(f"{dataset}/{framework}: incomplete cost telemetry")
            per_dataset[dataset][framework] = {
                "metric": metric,
                "quality_mean": statistics.mean(values),
                "cost_per_example_usd": statistics.mean(
                    value for value in costs if value is not None
                ),
            }
    for framework in FRAMEWORKS:
        macro[framework] = statistics.mean(
            per_dataset[dataset][framework]["quality_mean"] for dataset in PRIMARY_DATASETS
        )
        cost[framework] = statistics.mean(
            per_dataset[dataset][framework]["cost_per_example_usd"]
            for dataset in PRIMARY_DATASETS
        )
    return {"primary_macro": macro, "primary_cost_per_example_usd": cost, "per_dataset": per_dataset}


def _recomputed_dataset_summaries(
    runs: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Recompute every field emitted by the existing development summary."""

    output: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for dataset in ALL_DATASETS:
        output[dataset] = {}
        for framework in FRAMEWORKS:
            rows = runs[dataset][framework]
            exact = [value for row in rows if (value := _optional_score(row, "exact_match")) is not None]
            f1 = [value for row in rows if (value := _optional_score(row, "f1")) is not None]
            costs = [_effective_cost(row)[0] for row in rows]
            costs = [value for value in costs if value is not None]
            latencies = [
                _optional_number(row, "latency_ms", "telemetry.latency_ms")
                for row in rows
            ]
            latencies = [value for value in latencies if value is not None]
            calls = [
                _optional_number(row, "llm_call_count", "n_calls", "telemetry.llm_call_count")
                for row in rows
            ]
            calls = [value for value in calls if value is not None]
            primary_values = f1 if dataset == "tatqa" else exact
            output[dataset][framework] = {
                "count": len(rows),
                "exact_match": statistics.mean(exact) if exact else None,
                "f1": statistics.mean(f1) if f1 else None,
                "primary_value": statistics.mean(primary_values) if primary_values else None,
                "calls_total": int(sum(calls)),
                "calls_per_example": statistics.mean(calls) if calls else None,
                "cost_total_usd": sum(costs),
                "cost_per_example_usd": statistics.mean(costs) if costs else None,
                "latency_median_ms": statistics.median(latencies) if latencies else None,
                "latency_p95_ms": _percentile(sorted(latencies), 0.95) if latencies else None,
                "telemetry_complete": sum(
                    bool(
                        row.get("resolved_model")
                        and row.get("total_tokens") is not None
                        and row.get("latency_ms") is not None
                        and (
                            row.get("provider_cost_usd") is not None
                            or row.get("estimated_cost_usd") is not None
                        )
                    )
                    for row in rows
                ),
            }
    return output


def _compare_number(
    discrepancies: List[str], label: str, actual: Any, expected: Any, *, tolerance: float = 1e-12
) -> None:
    if actual is None or expected is None:
        if actual != expected:
            discrepancies.append(f"{label}: actual={actual!r}, expected={expected!r}")
        return
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance):
        discrepancies.append(f"{label}: actual={actual!r}, expected={expected!r}")


def verify_existing_summary(
    headlines: Mapping[str, Any],
    complementarity: Mapping[str, Any],
    existing_summary: Mapping[str, Any],
) -> List[str]:
    discrepancies: List[str] = []
    if headlines.get("model_id") != existing_summary.get("model_id"):
        discrepancies.append(
            f"model_id: actual={headlines.get('model_id')!r}, expected={existing_summary.get('model_id')!r}"
        )
    if headlines.get("results_tag") != existing_summary.get("results_tag"):
        discrepancies.append(
            f"results_tag: actual={headlines.get('results_tag')!r}, expected={existing_summary.get('results_tag')!r}"
        )
    for framework in FRAMEWORKS:
        _compare_number(
            discrepancies,
            f"primary_macro.{framework}",
            headlines["primary_macro"][framework],
            existing_summary.get("primary_macro", {}).get(framework),
        )
        _compare_number(
            discrepancies,
            f"primary_cost_per_example_usd.{framework}",
            headlines["primary_cost_per_example_usd"][framework],
            existing_summary.get("primary_cost_per_example_usd", {}).get(framework),
        )
    expected_datasets = existing_summary.get("datasets", {})
    for dataset in ALL_DATASETS:
        for framework in FRAMEWORKS:
            actual_metrics = headlines["dataset_summaries"][dataset][framework]
            expected_metrics = expected_datasets.get(dataset, {}).get(framework, {})
            for field in (
                "count",
                "exact_match",
                "f1",
                "primary_value",
                "calls_total",
                "calls_per_example",
                "cost_total_usd",
                "cost_per_example_usd",
                "latency_median_ms",
                "latency_p95_ms",
                "telemetry_complete",
            ):
                _compare_number(
                    discrepancies,
                    f"datasets.{dataset}.{framework}.{field}",
                    actual_metrics.get(field),
                    expected_metrics.get(field),
                )
    expected_counts = existing_summary.get("router_disagreement", {})
    for dataset in ROUTER_DATASETS:
        observed = complementarity["by_dataset"][dataset]
        expected = expected_counts.get(dataset, {})
        for observed_key, expected_key in (
            ("both_correct", "both"),
            ("static_only_correct", "static_only"),
            ("react_only_correct", "react_only"),
            ("both_wrong", "neither"),
        ):
            if observed[observed_key] != expected.get(expected_key):
                discrepancies.append(
                    f"router_disagreement.{dataset}.{expected_key}: "
                    f"actual={observed[observed_key]!r}, expected={expected.get(expected_key)!r}"
                )
    observed = complementarity["aggregate"]
    expected = existing_summary.get("router_observed_rerun", {})
    for actual_key, expected_key in (
        ("n_pairs", "count"),
        ("selective_observed_accuracy", "exact_accuracy"),
        ("selective_observed_cost_per_example_usd", "cost_per_example_usd"),
        ("selective_observed_escalation_rate", "escalation_rate"),
    ):
        _compare_number(discrepancies, f"router_observed_rerun.{expected_key}", observed[actual_key], expected.get(expected_key))
    return discrepancies


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write_csv(path: Path, records: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(records)


def _flatten_paired_csv(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for record in payload["quality"]["dataset_pairwise"]:
        test = record.get("paired_test", {})
        ci = record.get("bootstrap_ci", {})
        records.append(
            {
                "scope": "dataset",
                "dataset": record["dataset"],
                "metric": record["metric"],
                "left": record["left"],
                "right": record["right"],
                "n_pairs": record["n_pairs"],
                "left_mean": record["left_mean"],
                "right_mean": record["right_mean"],
                "difference_right_minus_left": record["difference_right_minus_left"],
                "cohen_dz": record["cohen_dz"],
                "ci_lower": ci.get("lower"),
                "ci_upper": ci.get("upper"),
                "bootstrap_seed": ci.get("seed"),
                "paired_test": test.get("name"),
                "p_value": test.get("p_value"),
                "discordant_pairs": test.get("discordant_pairs"),
            }
        )
    for record in payload["quality"]["primary_macro_pairwise"]:
        ci = record["stratified_bootstrap_ci"]
        records.append(
            {
                "scope": "primary_macro",
                "dataset": "macro",
                "metric": record["metric"],
                "left": record["left"],
                "right": record["right"],
                "n_pairs": record["n_pairs"],
                "left_mean": record["left_macro"],
                "right_mean": record["right_macro"],
                "difference_right_minus_left": record["difference_right_minus_left"],
                "cohen_dz": record["cohen_dz_over_micro_pairs"],
                "ci_lower": ci["lower"],
                "ci_upper": ci["upper"],
                "bootstrap_seed": ci["seed"],
                "paired_test": "stratified_paired_bootstrap",
                "p_value": None,
                "discordant_pairs": None,
            }
        )
    return records


def _flatten_efficiency_csv(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for scope, by_framework in (
        ("by_dataset", payload["efficiency"]["by_dataset"]),
        ("primary_3_dataset", payload["efficiency"]["primary"]),
        ("all_5_dataset", payload["efficiency"]["all_5"]),
    ):
        for dataset_or_framework, value in by_framework.items():
            if scope == "by_dataset":
                dataset = dataset_or_framework
                for framework, stats in value.items():
                    records.append(_efficiency_row(scope, dataset, framework, stats))
            else:
                records.append(_efficiency_row(scope, "aggregate", dataset_or_framework, value))
    return records


def _efficiency_row(scope: str, dataset: str, framework: str, stats: Mapping[str, Any]) -> Dict[str, Any]:
    token_per_example = stats.get("token_per_input_example", {})
    return {
        "scope": scope,
        "dataset": dataset,
        "system": framework,
        "system_display": DISPLAY_NAMES[framework],
        "input_rows": stats.get("input_rows"),
        "successful_rows": stats.get("successful_rows"),
        "failed_rows": stats.get("failed_rows"),
        "provider_failure_examples": stats.get("provider_failure_examples"),
        "answer_calls_total": stats.get("answer_calls_total"),
        "answer_calls_per_input_example": stats.get("answer_calls_per_input_example"),
        "input_tokens_per_example": token_per_example.get("input_tokens"),
        "output_tokens_per_example": token_per_example.get("output_tokens"),
        "total_tokens_per_example": token_per_example.get("total_tokens"),
        "cost_total_usd": stats.get("cost_total_usd"),
        "usd_per_example": stats.get("usd_per_example"),
        "cost_coverage": stats.get("cost_coverage"),
        "latency_median_ms": stats.get("latency_median_ms"),
        "latency_p95_ms": stats.get("latency_p95_ms"),
        "latency_available_successful_examples": stats.get("latency_available_successful_examples"),
        "latency_denominator_successful_examples": stats.get("latency_denominator_successful_examples"),
        "status_counts": json.dumps(stats.get("status_counts", {}), sort_keys=True),
        "missingness": json.dumps(stats.get("missingness", {}), sort_keys=True),
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _write_latex(path: Path, payload: Mapping[str, Any]) -> None:
    rows = []
    primary_efficiency = payload["efficiency"]["primary"]
    for framework in FRAMEWORKS:
        quality = payload["headlines"]["primary_macro"][framework]
        stats = primary_efficiency[framework]
        calls = stats["answer_calls_per_input_example"]
        tokens = stats["token_per_input_example"]
        rows.append(
            " & ".join(
                [
                    DISPLAY_NAMES[framework],
                    _fmt(100 * quality, 2),
                    _fmt(calls, 2),
                    _fmt(tokens.get("input_tokens"), 0),
                    _fmt(tokens.get("output_tokens"), 0),
                    _fmt(tokens.get("total_tokens"), 0),
                    _fmt(stats["usd_per_example"], 6),
                    _fmt(stats["latency_median_ms"], 0),
                    _fmt(stats["latency_p95_ms"], 0),
                ]
            )
            + " \\\\"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    text = """% Generated by src/agents/finance/analyze_realm_statistics.py.
% All values are development-only. Quality is a 3-dataset macro; efficiency
% denominators are 150 primary development examples per system.
\\begin{table}[t]
\\centering
\\small
\\begin{tabular}{lrrrrrrrr}
\\toprule
System & Macro (\\%) & Calls/ex. & Input tok./ex. & Output tok./ex. & Total tok./ex. & US\\$/ex. & Median ms & P95 ms \\\\
\\midrule
""" + "\n".join(rows) + """
\\bottomrule
\\end{tabular}
\\caption{Development-only quality and efficiency recomputed from paired raw results.}
\\label{tab:realm-paired-statistics}
\\end{table}
"""
    path.write_text(text, encoding="utf-8")


def _write_memo(path: Path, payload: Mapping[str, Any]) -> None:
    h = payload["headlines"]
    c = payload["complementarity"]["aggregate"]
    lines = [
        "# REALM 2026 paired statistics memo",
        "",
        "This memo and its generated tables use only the locked `development` result directories",
        f"for `{payload['model_id']}` and tag `{payload['results_tag']}`. The sealed final partition was not opened.",
        "",
        "## Scope and denominators",
        "",
        f"- Raw input: {len(ALL_DATASETS)} datasets × {len(FRAMEWORKS)} systems × 50 paired development examples.",
        "- Primary quality macro: unweighted mean of FinQA execution accuracy, TAT-QA official F1, and ConvFinQA execution accuracy (50 paired examples per dataset; 150 example rows per system).",
        f"- Router complementarity: {c['n_pairs']} paired examples across FinanceBench, FinQA, TAT-QA, and ConvFinQA, using exact-match correctness as in the locked router analysis.",
        "- Efficiency: `llm_call_count` is model/answer-call count; retrieval operations are reported separately. Cost uses provider cost when present, otherwise estimated cost. Latency is per-example end-to-end latency; median and P95 use successful rows with available latency.",
        f"- Bootstrap: percentile paired bootstrap with {payload['bootstrap']['n_resamples']:,} resamples and seed {payload['bootstrap']['seed']}; primary macro resamples each dataset stratum independently and averages the three stratum means.",
        "",
        "## Recomputed headline values",
        "",
        "| System | Primary macro | USD/example |",
        "|---|---:|---:|",
    ]
    for framework in FRAMEWORKS:
        lines.append(
            f"| {DISPLAY_NAMES[framework]} | {h['primary_macro'][framework]:.4f} | ${h['primary_cost_per_example_usd'][framework]:.6f} |"
        )
    lines.extend(
        [
            "",
            f"Static-only successes: {c['both_correct'] + c['static_only_correct']}/{c['n_pairs']} ({c['static_accuracy']:.3f}); ReAct-only successes: {c['react_only_correct']}/{c['n_pairs']} ({c['react_only_correct'] / c['n_pairs']:.3f}); oracle union: {c['oracle_accuracy']:.3f}; oracle headroom over static: {c['oracle_headroom_over_static']:.3f}.",
            f"The observed selective rerun escalated {c['selective_observed_escalation_rate']:.3f} of cases and reached {c['selective_observed_accuracy']:.3f} exact accuracy at ${c['selective_observed_cost_per_example_usd']:.6f}/example.",
            "",
            "## Interpretation boundary",
            "",
            "These are method-selection observations on development data, not confirmatory inference or a held-out test estimate. The paired intervals and exact McNemar results quantify uncertainty conditional on this frozen development sample; they do not restore independence after method selection, correct for all exploratory comparisons, or support population-level claims. The results describe controlled/evidence-conditioned reasoning and do not establish end-to-end retrieval or universal agentic failure.",
            "",
            "## Verification",
            "",
            f"The script independently recomputed the existing development summary: `{payload['verification']['status']}`.",
        ]
    )
    if payload["verification"]["discrepancies"]:
        lines.extend(["", "Discrepancies:"])
        lines.extend(f"- {item}" for item in payload["verification"]["discrepancies"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(
    *,
    results_root: Path,
    artifact_dir: Path,
    existing_summary_path: Path,
    model_id: str = DEFAULT_MODEL,
    results_tag: str = DEFAULT_TAG,
    protocol_id: str = "finance_icaif26_v2",
    seed: int = DEFAULT_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> Dict[str, Any]:
    if n_resamples < 1:
        raise AnalysisError("n_resamples must be positive")
    runs = load_development_runs(
        results_root,
        model_id=model_id,
        results_tag=results_tag,
        protocol_id=protocol_id,
    )
    headlines = _primary_headlines(runs)
    headlines["model_id"] = model_id
    headlines["results_tag"] = results_tag
    headlines["dataset_summaries"] = _recomputed_dataset_summaries(runs)
    complementarity = _complementarity(runs)
    existing_summary = _load_json(existing_summary_path)
    discrepancies = verify_existing_summary(headlines, complementarity, existing_summary)

    pair_records = []
    macro_records = []
    pair_index = 0
    for left_index, left_name in enumerate(FRAMEWORKS):
        for right_name in FRAMEWORKS[left_index + 1 :]:
            for dataset in PRIMARY_DATASETS:
                pair_records.append(
                    _pairwise_quality(
                        dataset,
                        PRIMARY_METRICS[dataset],
                        left_name,
                        right_name,
                        runs[dataset][left_name],
                        runs[dataset][right_name],
                        seed=seed + pair_index,
                        n_resamples=n_resamples,
                    )
                )
                pair_index += 1
            macro_records.append(
                _primary_macro_pair(
                    runs,
                    left_name,
                    right_name,
                    seed=seed + 1000 + len(macro_records),
                    n_resamples=n_resamples,
                )
            )

    efficiency_by_dataset = {
        dataset: {
            framework: _efficiency_summary(runs[dataset][framework])
            for framework in FRAMEWORKS
        }
        for dataset in ALL_DATASETS
    }
    efficiency = {
        "by_dataset": efficiency_by_dataset,
        "primary": _efficiency_all_rows(runs, PRIMARY_DATASETS),
        "all_5": _efficiency_all_rows(runs, ALL_DATASETS),
    }
    payload: Dict[str, Any] = {
        "schema_version": "realm-paired-statistics-v1",
        "partition": "development",
        "model_id": model_id,
        "results_tag": results_tag,
        "protocol_id": protocol_id,
        "datasets": list(ALL_DATASETS),
        "systems": list(FRAMEWORKS),
        "bootstrap": {"confidence": 0.95, "n_resamples": n_resamples, "seed": seed},
        "headlines": headlines,
        "quality": {
            "dataset_pairwise": pair_records,
            "primary_macro_pairwise": macro_records,
        },
        "complementarity": complementarity,
        "efficiency": efficiency,
        "verification": {
            "status": "passed" if not discrepancies else "failed",
            "existing_summary": str(existing_summary_path),
            "discrepancies": discrepancies,
        },
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "paired_statistics.json").write_text(_stable_json(payload), encoding="utf-8")
    paired_fields = (
        "scope", "dataset", "metric", "left", "right", "n_pairs", "left_mean", "right_mean",
        "difference_right_minus_left", "cohen_dz", "ci_lower", "ci_upper", "bootstrap_seed",
        "paired_test", "p_value", "discordant_pairs",
    )
    _write_csv(artifact_dir / "paired_statistics.csv", _flatten_paired_csv(payload), paired_fields)
    efficiency_fields = tuple(_efficiency_row("", "", "direct", efficiency["primary"]).keys())
    _write_csv(artifact_dir / "efficiency.csv", _flatten_efficiency_csv(payload), efficiency_fields)
    _write_latex(artifact_dir / "paired_statistics.tex", payload)
    _write_memo(artifact_dir.parent / "notes" / "paired_statistics.md", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("results/finance"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("paper/realm2026/artifacts"))
    parser.add_argument(
        "--existing-summary",
        type=Path,
        default=Path("paper/icaif2026/artifacts/development_summary.json"),
    )
    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--results-tag", default=DEFAULT_TAG)
    parser.add_argument("--protocol-id", default="finance_icaif26_v2")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-resamples", type=int, default=DEFAULT_BOOTSTRAP_RESAMPLES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = analyze(
            results_root=args.results_root,
            artifact_dir=args.artifact_dir,
            existing_summary_path=args.existing_summary,
            model_id=args.model_id,
            results_tag=args.results_tag,
            protocol_id=args.protocol_id,
            seed=args.seed,
            n_resamples=args.n_resamples,
        )
    except AnalysisError as exc:
        print(f"[REALM STATISTICS ERROR] {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "verification": payload["verification"],
        "primary_macro": payload["headlines"]["primary_macro"],
        "complementarity": payload["complementarity"]["aggregate"],
    }, indent=2, sort_keys=True))
    return 0 if payload["verification"]["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

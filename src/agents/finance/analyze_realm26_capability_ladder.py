"""Curate paired capability-tier aggregates without retaining raw provider rows."""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import finance_scoring
from .finance_statistics import exact_mcnemar, paired_bootstrap_ci, stratified_paired_bootstrap_ci
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_capability_protocol import DATASETS, DEFAULT_PROTOCOL_PATH, FRAMEWORKS, TIERS, load_manifest, load_protocol


def _rows(root: Path, dataset: str, framework: str) -> List[Dict[str, Any]]:
    path = root / dataset / framework / "results.json"
    if not path.exists():
        raise ProtocolError(f"Missing frozen results: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ProtocolError(f"Malformed results: {path}")
    return rows


def _nested(row: Mapping[str, Any], path: str) -> float:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ProtocolError(f"Missing serialized metric {path}")
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"Non-numeric serialized metric {path}")
    return float(value)


def _paired_rows(protocol: Mapping[str, Any], manifest: Mapping[str, Any], root: Path, tier: str) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    output: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    model = protocol["models"][tier]
    inference = protocol["inference"]
    reasoning_by_tier = inference.get("reasoning_effort_by_tier")
    expected_reasoning = (
        reasoning_by_tier[tier]
        if isinstance(reasoning_by_tier, Mapping)
        else inference.get("reasoning_effort")
    )
    for dataset in DATASETS:
        expected = [str(item["example_id"]) for item in manifest["datasets"][dataset]["examples"]]
        output[dataset] = {}
        for framework in FRAMEWORKS:
            rows = _rows(root, dataset, framework)
            by_id = {str(row["example_id"]): row for row in rows}
            if len(rows) != 50 or set(by_id) != set(expected):
                raise ProtocolError(f"{tier}/{dataset}/{framework}: incomplete or unexpected sample")
            ordered = [by_id[example_id] for example_id in expected]
            for item, row in zip(manifest["datasets"][dataset]["examples"], ordered):
                if row.get("status") != "success" or row.get("item_hash") != item.get("item_hash"):
                    raise ProtocolError("Failed row or item drift")
                if row.get("tier") != tier or row.get("requested_model") != model["requested_model_id"] or row.get("resolved_model") != model["requested_model_id"] or row.get("catalog_canonical_slug") != model["canonical_slug"]:
                    raise ProtocolError("Tier model binding mismatch")
                if (
                    row.get("provider_name") != "OpenAI"
                    or row.get("action_transport") != "strict_single_function_tool"
                    or row.get("reasoning_effort") != expected_reasoning
                    or row.get("reasoning_parameter_sent") is not (tier != "control")
                    or row.get("sampling_parameters_sent") != []
                    or row.get("structured_outputs") is not True
                    or row.get("tool_choice_sent") is not True
                ):
                    raise ProtocolError("Provider or request-parameter binding mismatch")
                if row.get("answer_contract") != protocol["workflows"]["answer_contract"] or row.get("method_version") != "realm26_harmonized_v2":
                    raise ProtocolError("Shared harmonized-v2 method contract drift")
                if framework == "static" and int(row.get("llm_call_count", 0)) != 1:
                    raise ProtocolError("Static treatment-integrity failure")
                if framework == "react" and not (
                    row.get("first_model_action") == "Search"
                    and row.get("react_process_integrity") is True
                    and int(row.get("llm_call_count", 0)) >= 2
                    and int(row.get("retrieval_operation_count", 0)) >= 1
                    and int(row.get("evidence_word_count", 0)) > 0
                    and row.get("parse_status") == "ok"
                ):
                    raise ProtocolError("ReAct treatment-integrity failure")
                if "native_scores" not in row:
                    row["native_scores"] = finance_scoring.score_dataset(
                        dataset,
                        str(row.get("answer") or "UNKNOWN"),
                        row.get("ground_truth"),
                        gold_scale=str(row.get("gold_scale") or ""),
                        question_type=str(row.get("question_type") or ""),
                    ).to_dict()
            output[dataset][framework] = ordered
    return output


def _mean_fields(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> Dict[str, float]:
    output: Dict[str, float] = {}
    for field in fields:
        values = [row.get(field) for row in rows]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise ProtocolError(f"Incomplete efficiency field: {field}")
        output[f"mean_{field}"] = mean(float(value) for value in values)
    return output


def analyze_tier(protocol: Mapping[str, Any], manifest: Mapping[str, Any], root: Path, tier: str) -> Dict[str, Any]:
    paired = _paired_rows(protocol, manifest, root, tier)
    metric_paths = protocol["analysis"]["dataset_quality_metrics"]
    n_resamples = int(protocol["analysis"]["bootstrap_resamples"])
    seed = int(protocol["analysis"]["bootstrap_seed"])
    quality = {
        framework: {
            dataset: [_nested(row, metric_paths[dataset]) for row in paired[dataset][framework]]
            for dataset in DATASETS
        }
        for framework in FRAMEWORKS
    }
    exact = {
        framework: {
            dataset: [_nested(row, "native_scores.exact_match") for row in paired[dataset][framework]]
            for dataset in DATASETS
        }
        for framework in FRAMEWORKS
    }
    datasets: Dict[str, Any] = {}
    all_rows = {framework: [] for framework in FRAMEWORKS}
    all_exact = {framework: [] for framework in FRAMEWORKS}
    for dataset in DATASETS:
        datasets[dataset] = {
            "quality_metric": metric_paths[dataset],
            "quality": {framework: mean(quality[framework][dataset]) for framework in FRAMEWORKS},
            "paired_bootstrap_react_minus_static": paired_bootstrap_ci(
                quality["static"][dataset], quality["react"][dataset], n_resamples=n_resamples, seed=seed
            ).to_dict(),
            "complementarity_exact": exact_mcnemar(exact["static"][dataset], exact["react"][dataset]).to_dict(),
        }
        for framework in FRAMEWORKS:
            all_rows[framework].extend(paired[dataset][framework])
            all_exact[framework].extend(exact[framework][dataset])
    matrix = exact_mcnemar(all_exact["static"], all_exact["react"]).to_dict()
    union = matrix["both_correct"] + matrix["left_only_correct"] + matrix["right_only_correct"]
    static_correct = matrix["both_correct"] + matrix["left_only_correct"]
    react_correct = matrix["both_correct"] + matrix["right_only_correct"]
    matrix.update({
        "oracle_union_accuracy": union / 150,
        "oracle_headroom_over_best_branch": (union - max(static_correct, react_correct)) / 150,
        "react_only_frequency": matrix["right_only_correct"] / 150,
        "static_only_frequency": matrix["left_only_correct"] / 150,
    })
    primary = stratified_paired_bootstrap_ci(
        quality["static"], quality["react"], n_resamples=n_resamples, seed=seed
    ).to_dict()
    efficiency_fields = list(protocol["analysis"]["efficiency_fields"])
    efficiency_intervals = {
        field: paired_bootstrap_ci(
            [float(row[field]) for row in all_rows["static"]],
            [float(row[field]) for row in all_rows["react"]],
            n_resamples=n_resamples,
            seed=seed,
        ).to_dict()
        for field in efficiency_fields
    }
    ledger = json.loads((root.parent / "cumulative_spend_ledger.json").read_text(encoding="utf-8"))
    if ledger.get("pending_reservations"):
        raise ProtocolError("Analysis forbidden with unresolved spend reservation")
    spend = sum(float(row["actual_cost_usd"]) for row in ledger["calls"] if row.get("tier") == tier)
    total = sum(float(row["actual_cost_usd"]) for row in ledger["calls"])
    if abs(total - float(ledger["actual_study_spend_usd"])) > 1e-9:
        raise ProtocolError("Cumulative spend ledger mismatch")
    commits = {str(row["pre_result_commit"]) for framework in FRAMEWORKS for row in all_rows[framework]}
    if len(commits) != 1:
        raise ProtocolError("Rows do not share one public pre-result freeze")
    return {
        "canonical_slug": protocol["models"][tier]["canonical_slug"],
        "complementarity_exact": matrix,
        "datasets": datasets,
        "efficiency": {
            "paired_bootstrap_react_minus_static": efficiency_intervals,
            "systems": {framework: _mean_fields(all_rows[framework], efficiency_fields) for framework in FRAMEWORKS},
        },
        "macro_quality": {framework: mean(mean(quality[framework][dataset]) for dataset in DATASETS) for framework in FRAMEWORKS},
        "pre_result_commit": commits.pop(),
        "primary_stratified_bootstrap_react_minus_static": primary,
        "provider_spend_usd": spend,
        "requested_model_id": protocol["models"][tier]["requested_model_id"],
        "sample": {"items": 150, "paired_arm_rows": 300, "per_dataset": 50},
        "tier": tier,
    }


def compare_tiers(
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    roots: Mapping[str, Path],
) -> Dict[str, Any]:
    """Compare tier quality and the preregistered ReAct-minus-Static interactions."""

    metric_paths = protocol["analysis"]["dataset_quality_metrics"]
    n_resamples = int(protocol["analysis"]["bootstrap_resamples"])
    seed = int(protocol["analysis"]["bootstrap_seed"])
    paired = {
        tier: _paired_rows(protocol, manifest, roots[tier], tier)
        for tier in TIERS
    }
    quality = {
        tier: {
            framework: {
                dataset: [
                    _nested(row, metric_paths[dataset])
                    for row in paired[tier][dataset][framework]
                ]
                for dataset in DATASETS
            }
            for framework in FRAMEWORKS
        }
        for tier in TIERS
    }
    deltas = {
        tier: {
            dataset: [
                react - static
                for static, react in zip(
                    quality[tier]["static"][dataset],
                    quality[tier]["react"][dataset],
                )
            ]
            for dataset in DATASETS
        }
        for tier in TIERS
    }

    quality_differences: Dict[str, Any] = {}
    interactions: Dict[str, Any] = {}
    for reference, target in combinations(TIERS, 2):
        comparison = f"{target}_minus_{reference}"
        quality_differences[comparison] = {
            framework: stratified_paired_bootstrap_ci(
                quality[reference][framework],
                quality[target][framework],
                n_resamples=n_resamples,
                seed=seed,
            ).to_dict()
            for framework in FRAMEWORKS
        }
        interactions[comparison] = stratified_paired_bootstrap_ci(
            deltas[reference],
            deltas[target],
            n_resamples=n_resamples,
            seed=seed,
        ).to_dict()

    return {
        "quality_differences": quality_differences,
        "react_minus_static_delta_interactions": interactions,
        "interaction_estimand": (
            "(ReAct - Static) target-tier macro quality minus "
            "(ReAct - Static) reference-tier macro quality"
        ),
        "interaction_method": "dataset-stratified paired percentile bootstrap",
    }


def render_memo(result: Mapping[str, Any]) -> str:
    lines = [
        "# REALM 2026 capability-ladder decision report",
        "",
        "All results are development-only and use the completed harmonized-v2 Static and retrieval-first ReAct contracts.",
        "",
    ]
    for tier in TIERS:
        if tier not in result["tiers"]:
            continue
        row = result["tiers"][tier]
        ci = row["primary_stratified_bootstrap_react_minus_static"]
        comp = row["complementarity_exact"]
        lines.extend([
            f"## {tier.title()}",
            "",
            f"Requested `{row['requested_model_id']}`; resolved `{row['canonical_slug']}`.",
            f"Static macro {row['macro_quality']['static']:.4f}; ReAct macro {row['macro_quality']['react']:.4f}.",
            f"ReAct-minus-Static {ci['estimate']:.4f}, 95% CI [{ci['lower']:.4f}, {ci['upper']:.4f}].",
            f"Exact matrix: both correct {comp['both_correct']}, Static only {comp['left_only_correct']}, ReAct only {comp['right_only_correct']}, both wrong {comp['both_wrong']}.",
            f"Oracle headroom over the better branch: {comp['oracle_headroom_over_best_branch']:.4f}.",
            f"Provider spend: USD {row['provider_spend_usd']:.6f}.",
            "",
        ])
    lines.extend([
        "## Frozen tier execution",
        "",
        f"All {len(TIERS)} tiers ({', '.join(TIERS)}) were required prospectively, and no outcomes were analyzed until every tier completed.",
        "",
        "No protected-final example was loaded, rendered, executed, or scored.",
        "",
    ])
    interactions = result["tier_comparison"]["react_minus_static_delta_interactions"]
    if interactions:
        lines.extend(["## ReAct-minus-Static interactions", ""])
        for name, interval in interactions.items():
            lines.append(
                f"{name}: {interval['estimate']:.4f}, 95% CI "
                f"[{interval['lower']:.4f}, {interval['upper']:.4f}]."
            )
        lines.append("")
    return "\n".join(lines)


def _validate_roots(roots: Mapping[str, Path]) -> Dict[str, Path]:
    expected = set(TIERS)
    actual = set(roots)
    if actual != expected:
        raise ProtocolError(
            "Analysis requires exactly one completed root for every frozen tier: "
            f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
        )
    return {tier: Path(roots[tier]).resolve() for tier in TIERS}


def _validate_study_completion(protocol: Mapping[str, Any], roots: Mapping[str, Path]) -> None:
    parents = {path.parent for path in roots.values()}
    if len(parents) != 1:
        raise ProtocolError("All tier roots must share one frozen run root")
    completion_path = parents.pop() / "study_complete.json"
    if not completion_path.exists():
        raise ProtocolError("Analysis is forbidden until the three-tier completion record exists")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    expected = 150 * len(FRAMEWORKS)
    if (
        completion.get("status") != "complete"
        or completion.get("process_checks_passed") is not True
        or completion.get("tier_episode_counts") != {tier: expected for tier in TIERS}
    ):
        raise ProtocolError("Three-tier process completion is incomplete")


def analyze(protocol_path: str | Path, roots: Mapping[str, Path]) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    manifest = load_manifest(protocol)
    normalized_roots = _validate_roots(roots)
    _validate_study_completion(protocol, normalized_roots)
    tiers = {
        tier: analyze_tier(protocol, manifest, normalized_roots[tier], tier)
        for tier in TIERS
    }
    comparison = compare_tiers(protocol, manifest, normalized_roots)
    result: Dict[str, Any] = {
        "analysis_schema_version": "realm26-capability-analysis-v2",
        "claims_scope": protocol["claims_scope"],
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "protocol_id": protocol["protocol_id"],
        "tier_execution": protocol["tier_execution"],
        "tier_comparison": comparison,
        "tiers": tiers,
    }
    result["analysis_fingerprint"] = fingerprint(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    for tier in TIERS:
        parser.add_argument(f"--{tier}-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--memo", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    result = analyze(
        args.protocol,
        {tier: Path(getattr(args, f"{tier}_root")) for tier in TIERS},
    )
    write_stable_json(Path(args.output), result)
    Path(args.memo).write_text(render_memo(result), encoding="utf-8")
    print(json.dumps({
        "analysis_fingerprint": result["analysis_fingerprint"],
        "tiers": sorted(result["tiers"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()

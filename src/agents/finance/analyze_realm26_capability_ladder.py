"""Curate paired capability-tier aggregates without retaining raw provider rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .finance_statistics import exact_mcnemar, paired_bootstrap_ci, stratified_paired_bootstrap_ci
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_capability_protocol import DATASETS, DEFAULT_PROTOCOL_PATH, FRAMEWORKS, load_manifest, load_protocol


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
                if row.get("tier") != tier or row.get("requested_model") != model["requested_model_id"] or row.get("resolved_model") != model["canonical_slug"]:
                    raise ProtocolError("Tier model binding mismatch")
                if row.get("provider_name") != "OpenAI" or row.get("reasoning_effort") != "none" or row.get("sampling_parameters_sent") != []:
                    raise ProtocolError("Provider or request-parameter binding mismatch")
                if row.get("answer_contract") != "strict_json_finish_v1" or row.get("method_version") != "realm26_harmonized_v2":
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
    ledger = json.loads((root / "spend_ledger.json").read_text(encoding="utf-8"))
    if ledger.get("pending_reservations"):
        raise ProtocolError("Analysis forbidden with unresolved spend reservation")
    spend = sum(float(row["actual_cost_usd"]) for row in ledger["calls"])
    if abs(spend - float(ledger["actual_spend_usd"])) > 1e-9 or spend > float(protocol["models"][tier]["hard_cap_usd"]):
        raise ProtocolError("Spend ledger mismatch or cap breach")
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


def compare_tiers(protocol: Mapping[str, Any], manifest: Mapping[str, Any], luna_root: Path, terra_root: Path) -> Dict[str, Any]:
    metric_paths = protocol["analysis"]["dataset_quality_metrics"]
    n_resamples = int(protocol["analysis"]["bootstrap_resamples"])
    seed = int(protocol["analysis"]["bootstrap_seed"])
    luna = _paired_rows(protocol, manifest, luna_root, "luna")
    terra = _paired_rows(protocol, manifest, terra_root, "terra")
    output: Dict[str, Any] = {}
    for framework in FRAMEWORKS:
        luna_by_dataset = {dataset: [_nested(row, metric_paths[dataset]) for row in luna[dataset][framework]] for dataset in DATASETS}
        terra_by_dataset = {dataset: [_nested(row, metric_paths[dataset]) for row in terra[dataset][framework]] for dataset in DATASETS}
        output[f"{framework}_terra_minus_luna"] = stratified_paired_bootstrap_ci(
            luna_by_dataset, terra_by_dataset, n_resamples=n_resamples, seed=seed
        ).to_dict()
    return output


def render_memo(result: Mapping[str, Any]) -> str:
    lines = [
        "# REALM 2026 capability-ladder decision report",
        "",
        "All results are development-only and use the completed harmonized-v2 Static and retrieval-first ReAct contracts.",
        "",
    ]
    for tier in ("luna", "terra"):
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
    trigger = result["terra_trigger"]
    lines.extend([
        "## Frozen Terra decision",
        "",
        f"Terra triggered: `{str(trigger['run_terra']).lower()}` because Luna's lower confidence bound was {trigger['luna_primary_ci']['lower']:.4f}.",
        "",
        "No sealed-final example was loaded, rendered, executed, or scored.",
        "",
    ])
    return "\n".join(lines)


def analyze(protocol_path: str | Path, luna_root: Path, terra_root: Optional[Path] = None) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    manifest = load_manifest(protocol)
    luna = analyze_tier(protocol, manifest, luna_root, "luna")
    lower = float(luna["primary_stratified_bootstrap_react_minus_static"]["lower"])
    trigger = {
        "automatic_rule": "run Terra iff Luna primary 95% CI lower bound <= 0",
        "luna_primary_ci": luna["primary_stratified_bootstrap_react_minus_static"],
        "manual_override": False,
        "pre_result_commit": luna["pre_result_commit"],
        "run_terra": lower <= 0,
        "trigger_schema_version": "realm26-terra-trigger-v1",
    }
    tiers: Dict[str, Any] = {"luna": luna}
    comparison = None
    if terra_root is not None:
        if not trigger["run_terra"]:
            raise ProtocolError("Terra results exist despite a false frozen trigger")
        tiers["terra"] = analyze_tier(protocol, manifest, terra_root, "terra")
        comparison = compare_tiers(protocol, manifest, luna_root, terra_root)
    result: Dict[str, Any] = {
        "analysis_schema_version": "realm26-capability-analysis-v1",
        "claims_scope": protocol["claims_scope"],
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "protocol_id": protocol["protocol_id"],
        "terra_trigger": trigger,
        "tier_comparison": comparison,
        "tiers": tiers,
    }
    result["analysis_fingerprint"] = fingerprint(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--luna-root", required=True)
    parser.add_argument("--terra-root")
    parser.add_argument("--output", required=True)
    parser.add_argument("--trigger-output", required=True)
    parser.add_argument("--memo", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    result = analyze(
        args.protocol,
        Path(args.luna_root).resolve(),
        Path(args.terra_root).resolve() if args.terra_root else None,
    )
    write_stable_json(Path(args.output), result)
    write_stable_json(Path(args.trigger_output), result["terra_trigger"])
    Path(args.memo).write_text(render_memo(result), encoding="utf-8")
    print(json.dumps({
        "analysis_fingerprint": result["analysis_fingerprint"],
        "run_terra": result["terra_trigger"]["run_terra"],
        "tiers": sorted(result["tiers"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()

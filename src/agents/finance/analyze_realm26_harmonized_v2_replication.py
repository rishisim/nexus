"""Frozen paired analysis for the REALM 2026 harmonized v2 corrective study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .finance_statistics import (
    cost_latency_summary,
    exact_mcnemar,
    paired_bootstrap_ci,
    stratified_paired_bootstrap_ci,
)
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_harmonized_v2_protocol import DATASETS, DEFAULT_PROTOCOL_PATH, FRAMEWORKS, load_manifest, load_protocol


def _rows(root: Path, dataset: str, framework: str) -> List[Dict[str, Any]]:
    path = root / dataset / framework / "results.json"
    if not path.exists():
        raise ProtocolError(f"Missing frozen results: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ProtocolError(f"Malformed results: {path}")
    return rows


def _nested_metric(row: Mapping[str, Any], path: str) -> float:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ProtocolError(f"Frozen serialized metric {path!r} is absent")
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"Frozen serialized metric {path!r} is non-numeric")
    return float(value)


def _pair_dataset(root: Path, manifest: Mapping[str, Any], dataset: str) -> Dict[str, List[Dict[str, Any]]]:
    expected = [str(item["example_id"]) for item in manifest["datasets"][dataset]["examples"]]
    output: Dict[str, List[Dict[str, Any]]] = {}
    for framework in FRAMEWORKS:
        rows = _rows(root, dataset, framework)
        by_id = {str(row["example_id"]): row for row in rows}
        if len(rows) != 50 or set(by_id) != set(expected):
            raise ProtocolError(f"{dataset}/{framework}: incomplete or unexpected sample")
        ordered = [by_id[example_id] for example_id in expected]
        for item, row in zip(manifest["datasets"][dataset]["examples"], ordered):
            if row.get("status") != "success" or row.get("item_hash") != item.get("item_hash"):
                raise ProtocolError(f"{dataset}/{framework}: failed row or item drift")
            if row.get("answer_contract") != "strict_json_finish_v1":
                raise ProtocolError("Answer contract drift in results")
            if row.get("method_version") != "realm26_harmonized_v2":
                raise ProtocolError("Method-version drift in results")
            if int(row.get("max_prompt_word_count", 999999)) > int(row["context_word_budget"]):
                raise ProtocolError("Context ceiling violation in results")
            if int(row.get("evidence_word_count", 999999)) > int(row["evidence_word_budget"]):
                raise ProtocolError("Evidence ceiling violation in results")
            if framework == "static" and int(row.get("llm_call_count", 0)) != 1:
                raise ProtocolError("Static treatment-integrity failure in results")
            if framework == "react" and not (
                row.get("first_model_action") == "Search"
                and row.get("react_process_integrity") is True
                and int(row.get("llm_call_count", 0)) >= 2
                and int(row.get("retrieval_operation_count", 0)) >= 1
                and int(row.get("evidence_word_count", 0)) > 0
                and row.get("parse_status") == "ok"
            ):
                raise ProtocolError("ReAct treatment-integrity failure in results")
        output[framework] = ordered
    return output


def _field(rows: Sequence[Mapping[str, Any]], name: str) -> List[float]:
    values = []
    for row in rows:
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProtocolError(f"Paired efficiency field {name!r} is incomplete")
        values.append(float(value))
    return values


def analyze(protocol_path: str | Path, results_root: Path) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    manifest = load_manifest(protocol)
    n_resamples = int(protocol["analysis"]["bootstrap_resamples"])
    seed = int(protocol["analysis"]["bootstrap_seed"])
    paired = {dataset: _pair_dataset(results_root, manifest, dataset) for dataset in DATASETS}
    metric_paths = protocol["analysis"]["dataset_quality_metrics"]
    static_by_dataset = {dataset: [_nested_metric(row, metric_paths[dataset]) for row in paired[dataset]["static"]] for dataset in DATASETS}
    react_by_dataset = {dataset: [_nested_metric(row, metric_paths[dataset]) for row in paired[dataset]["react"]] for dataset in DATASETS}

    datasets: Dict[str, Any] = {}
    all_rows = {framework: [] for framework in FRAMEWORKS}
    all_binary = {framework: [] for framework in FRAMEWORKS}
    for dataset in DATASETS:
        static = static_by_dataset[dataset]
        react = react_by_dataset[dataset]
        static_exact = [_nested_metric(row, "native_scores.exact_match") for row in paired[dataset]["static"]]
        react_exact = [_nested_metric(row, "native_scores.exact_match") for row in paired[dataset]["react"]]
        comp = exact_mcnemar(static_exact, react_exact).to_dict()
        datasets[dataset] = {
            "complementarity_exact": comp,
            "paired_bootstrap_react_minus_static": paired_bootstrap_ci(static, react, n_resamples=n_resamples, seed=seed).to_dict(),
            "quality": {"metric": metric_paths[dataset], "static": mean(static), "react": mean(react)},
            "systems": {framework: cost_latency_summary(paired[dataset][framework]) for framework in FRAMEWORKS},
        }
        for framework in FRAMEWORKS:
            all_rows[framework].extend(paired[dataset][framework])
            all_binary[framework].extend(static_exact if framework == "static" else react_exact)

    complementarity = exact_mcnemar(all_binary["static"], all_binary["react"]).to_dict()
    union_correct = complementarity["both_correct"] + complementarity["left_only_correct"] + complementarity["right_only_correct"]
    complementarity.update({
        "oracle_union_accuracy": union_correct / 150,
        "success_overlap_jaccard": complementarity["both_correct"] / union_correct if union_correct else 1.0,
    })
    efficiency_intervals = {}
    for field in protocol["analysis"]["efficiency_paired_intervals"]:
        efficiency_intervals[field] = paired_bootstrap_ci(
            _field(all_rows["static"], field),
            _field(all_rows["react"], field),
            n_resamples=n_resamples,
            seed=seed,
        ).to_dict()
    macro = {
        framework: mean(mean(static_by_dataset[d] if framework == "static" else react_by_dataset[d]) for d in DATASETS)
        for framework in FRAMEWORKS
    }
    ledger = json.loads((results_root / "spend_ledger.json").read_text(encoding="utf-8"))
    if ledger.get("pending_reservations"):
        raise ProtocolError("Analysis forbidden with an unresolved spend reservation")
    call_sum = sum(float(row["actual_cost_usd"]) for row in ledger["calls"])
    if abs(call_sum - float(ledger["actual_spend_usd"])) > 1e-9 or call_sum > 5.0:
        raise ProtocolError("Spend ledger is inconsistent or exceeds USD 5")
    commits = {str(row["pre_result_commit"]) for framework in FRAMEWORKS for row in all_rows[framework]}
    if len(commits) != 1:
        raise ProtocolError("Results do not share one public pre-result commit")
    primary_ci = stratified_paired_bootstrap_ci(
        static_by_dataset,
        react_by_dataset,
        n_resamples=n_resamples,
        seed=seed,
    ).to_dict()
    interpretation = (
        "static_advantage"
        if primary_ci["upper"] < 0
        else "react_advantage"
        if primary_ci["lower"] > 0
        else "inconclusive"
    )
    result: Dict[str, Any] = {
        "analysis_schema_version": "realm26-harmonized-analysis-v2",
        "claims_scope": protocol["claims_scope"],
        "datasets": datasets,
        "frameworks": {framework: cost_latency_summary(all_rows[framework]) for framework in FRAMEWORKS},
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "model_id": protocol["inference"]["model_id"],
        "overall": {
            "complementarity_exact": complementarity,
            "efficiency_paired_bootstrap_react_minus_static": efficiency_intervals,
            "macro_quality": macro,
            "directional_interpretation": interpretation,
            "primary_stratified_bootstrap_react_minus_static": primary_ci,
            "treatment_integrity": {
                "react_rows_passing": 150,
                "react_rows_required": 150,
                "required_first_action": "Search",
                "required_minimum_evidence_operations": 1,
                "required_minimum_model_calls": 2,
                "static_rows_passing_one_call_check": 150,
            },
        },
        "pre_result_commit": commits.pop(),
        "protocol_id": protocol["protocol_id"],
        "provider_spend_usd": call_sum,
        "sample": {"datasets": 3, "items": 150, "paired_arm_rows": 300},
        "separation_statement": "This fresh-sample v2 corrective study is separate from the invalid v1 manipulation check and does not reopen or replace the original documented selector gate.",
    }
    result["analysis_fingerprint"] = fingerprint(result)
    return result


def render_memo(analysis: Mapping[str, Any]) -> str:
    macro = analysis["overall"]["macro_quality"]
    ci = analysis["overall"]["primary_stratified_bootstrap_react_minus_static"]
    comp = analysis["overall"]["complementarity_exact"]
    static = analysis["frameworks"]["static"]
    react = analysis["frameworks"]["react"]
    return f"""# REALM 2026 prompt/context-harmonized v2 corrective replication

This is a fresh-sample development-only v2 corrective study. It is separate
from the v1 manipulation-check failure and does not reopen or replace the
original documented selector gate. No final-partition example was executed,
scored, or inspected; final-manifest identifiers were used only to exclude
overlap.

## Frozen design

- Public pre-result commit: `{analysis['pre_result_commit']}`.
- Sample: 150 fresh development items (50 each from FinQA, TAT-QA, and
  ConvFinQA), disjoint from the original 250, the 75-item second-family study,
  all 150 v1 items, and the 900 final identifiers.
- Binding: `{analysis['model_id']}`, OpenAI-only through OpenRouter, temperature
  zero, one attempt, no provider fallback.
- Harmonization: identical strict JSON finish contract, canonical scorer input,
  malformed-to-UNKNOWN fallback, 3,000-word cumulative evidence ceiling, three
  evidence operations, 4,096-word per-call context ceiling, and 384 output
  tokens per call. Static remains one call; ReAct remains bounded iterative.
- Treatment integrity: every ReAct row began with a model-selected Search,
  observed evidence, and used at least two model calls. All 150 ReAct rows and
  all 150 one-call Static rows passed their prospectively frozen process checks.
- Provider spend: USD {analysis['provider_spend_usd']:.6f} under the USD 5 cap.

## Development result

Static macro dataset-native quality was {macro['static']:.4f}; ReAct was
{macro['react']:.4f}. The paired dataset-stratified ReAct-minus-Static estimate
was {ci['estimate']:.4f} (95% percentile interval {ci['lower']:.4f} to
{ci['upper']:.4f}). Exact complementarity counts were: both correct
{comp['both_correct']}, Static-only {comp['left_only_correct']}, ReAct-only
{comp['right_only_correct']}, and both wrong {comp['both_wrong']} (exact
McNemar p={comp['p_value']:.6g}).

The frozen directional interpretation is
`{analysis['overall']['directional_interpretation']}`.

Static averaged {static['mean_llm_calls']:.3f} model calls and USD
{static['mean_cost_usd']:.6f} per item; ReAct averaged
{react['mean_llm_calls']:.3f} calls and USD {react['mean_cost_usd']:.6f}.

These are development-only findings and support no claim about the sealed final
partition or a universal advantage of static or agentic reasoning.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--memo", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    analysis = analyze(args.protocol, Path(args.results_root).resolve())
    write_stable_json(Path(args.output), analysis)
    Path(args.memo).parent.mkdir(parents=True, exist_ok=True)
    Path(args.memo).write_text(render_memo(analysis), encoding="utf-8")
    print(json.dumps({"analysis_fingerprint": analysis["analysis_fingerprint"], "provider_spend_usd": analysis["provider_spend_usd"]}, sort_keys=True))


if __name__ == "__main__":
    main()

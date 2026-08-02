"""Run the prospectively frozen REALM capability ladder without outcome peeking."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.shared.llm_telemetry import LLMResult

from . import finance_scoring
from .finance_utils import set_active_dataset
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_capability_llm import call_capability_model, validate_live_catalog
from .realm26_capability_methods import METHODS
from .realm26_capability_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    FRAMEWORKS,
    load_manifest,
    load_protocol,
    resolve_path,
    validate_manifest_against_sources,
)
from .realm26_harmonized_data import HarmonizedEnvFactory
from .realm26_harmonized_v2_methods import REACT_ACTION_POLICY
from .run_finance_experiments import aggregate_telemetry


RESULT_SCHEMA_VERSION = "realm26-capability-result-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StopExperiment(ProtocolError):
    """A prospectively frozen stop condition fired."""


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise StopExperiment(f"Git preflight failed: git {' '.join(args)}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def public_head_preflight(protocol: Mapping[str, Any]) -> Dict[str, str]:
    protocol_path = Path(str(protocol["_path"]))
    repo = Path(_git(protocol_path.parent, "rev-parse", "--show-toplevel"))
    publication = protocol["publication"]
    branch = _git(repo, "branch", "--show-current")
    if branch != publication["branch"]:
        raise StopExperiment(f"Execution branch {branch!r} is not the frozen capability branch")
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise StopExperiment("Tracked worktree is not clean before provider inference")
    head = _git(repo, "rev-parse", "HEAD")
    remote_rows = _git(repo, "ls-remote", "--heads", publication["remote"], f"refs/heads/{branch}").splitlines()
    if len(remote_rows) != 1 or remote_rows[0].split()[0] != head:
        raise StopExperiment("Capability branch HEAD is not exactly pushed to the public remote")
    return {"branch": branch, "commit": head, "remote": publication["remote"], "repo": str(repo)}


class SpendLedger:
    def __init__(self, path: Path, protocol_fingerprint: str, tier: str, spec: Mapping[str, Any]):
        self.path = path
        self.protocol_fingerprint = protocol_fingerprint
        self.tier = tier
        self.cap = float(spec["hard_cap_usd"])
        self.maximum_call = float(spec["maximum_reserved_call_cost_usd"])
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {
                "actual_spend_usd": 0.0,
                "calls": [],
                "hard_cap_usd": self.cap,
                "maximum_reserved_call_cost_usd": self.maximum_call,
                "pending_reservations": [],
                "protocol_fingerprint": protocol_fingerprint,
                "schema_version": "realm26-capability-spend-ledger-v1",
                "tier": tier,
            }
            self._write()
        if self.data.get("protocol_fingerprint") != protocol_fingerprint or self.data.get("tier") != tier:
            raise StopExperiment("Spend ledger belongs to another frozen protocol or tier")
        if float(self.data.get("hard_cap_usd", -1)) != self.cap or float(self.data.get("maximum_reserved_call_cost_usd", -1)) != self.maximum_call:
            raise StopExperiment("Spend ledger cap or reservation changed")
        if self.data.get("pending_reservations"):
            raise StopExperiment("Unresolved spend reservation after interruption")

    @property
    def actual_spend(self) -> float:
        return float(self.data.get("actual_spend_usd", 0.0))

    def _write(self) -> None:
        write_stable_json(self.path, self.data)

    def reserve(self, call_key: str, prompt_hash: str) -> None:
        used = {str(row["call_key"]) for row in self.data["calls"]}
        if call_key in used or self.actual_spend + self.maximum_call > self.cap + 1e-12:
            raise StopExperiment(f"{self.tier}: reservation would duplicate a call or exceed the hard cap")
        self.data["pending_reservations"] = [{
            "call_key": call_key,
            "maximum_cost_usd": self.maximum_call,
            "prompt_sha256": prompt_hash,
            "reserved_at": utc_now(),
        }]
        self._write()

    def complete(self, call_key: str, response: Any, estimated_cost: float) -> None:
        pending = self.data["pending_reservations"]
        if len(pending) != 1 or pending[0]["call_key"] != call_key:
            raise StopExperiment("Spend reservation identity mismatch")
        result: LLMResult = response.result
        charge = result.provider_cost_usd if result.provider_cost_usd is not None else estimated_cost
        charge = float(charge)
        if charge < 0 or charge > self.maximum_call + 1e-12 or self.actual_spend + charge > self.cap + 1e-12:
            raise StopExperiment(f"{self.tier}: provider charge exceeded the frozen reservation or cap")
        self.data["pending_reservations"] = []
        self.data["actual_spend_usd"] = self.actual_spend + charge
        self.data["calls"].append({
            "actual_cost_usd": charge,
            "call_key": call_key,
            "cached_tokens": result.cached_tokens,
            "completed_at": utc_now(),
            "estimated_cost_usd": estimated_cost,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "prompt_sha256": pending[0]["prompt_sha256"],
            "provider_cost_usd": result.provider_cost_usd,
            "provider_name": response.provider_name,
            "reasoning_effort": response.request_parameters["reasoning_effort"],
            "reasoning_tokens": result.reasoning_tokens,
            "requested_model": result.requested_model,
            "reserved_maximum_cost_usd": self.maximum_call,
            "resolved_model": result.resolved_model,
            "sampling_parameters_sent": response.request_parameters["sampling_parameters_sent"],
            "status": result.status,
            "total_tokens": result.total_tokens,
        })
        self._write()


class BudgetedCapabilityModel:
    def __init__(self, protocol: Mapping[str, Any], snapshot: Mapping[str, Any], ledger: SpendLedger, tier: str, pair_key: str):
        self.protocol = protocol
        self.snapshot = snapshot
        self.ledger = ledger
        self.tier = tier
        self.pair_key = pair_key
        self.call_index = 0
        self.call_records: List[Dict[str, Any]] = []
        self.spec = protocol["models"][tier]
        pricing = snapshot["models"][tier]["openai_endpoint"]["pricing"]
        self.input_rate = float(pricing["prompt"])
        self.output_rate = float(pricing["completion"])
        self.cache_rate = float(pricing["input_cache_read"])

    def __call__(self, prompt: str, stop=None, temperature=None, num_traces: int = 1, max_tokens: int = 384, model_id: Optional[str] = None, **_: Any) -> LLMResult:
        expected = str(self.spec["requested_model_id"])
        if model_id != expected or temperature is not None or num_traces != 1:
            raise StopExperiment("Per-call model or forbidden sampling parameter changed")
        if int(max_tokens) != int(self.protocol["workflows"]["max_output_tokens_per_call"]):
            raise StopExperiment("Per-call output ceiling changed")
        self.call_index += 1
        call_key = f"{self.pair_key}/call-{self.call_index}"
        prompt_hash = "sha256:" + hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()
        self.ledger.reserve(call_key, prompt_hash)
        response = call_capability_model(
            prompt=str(prompt),
            requested_model=expected,
            canonical_slug=str(self.spec["canonical_slug"]),
            max_tokens=int(max_tokens),
            stop=[] if stop is None else list(stop),
        )
        result = response.result
        cached = min(result.cached_tokens, result.input_tokens)
        estimated = (result.input_tokens - cached) * self.input_rate + cached * self.cache_rate + result.output_tokens * self.output_rate
        if result.estimated_cost_usd is None:
            result = replace(result, estimated_cost_usd=estimated)
            response = replace(response, result=result)
        self.ledger.complete(call_key, response, estimated)
        record = result.to_dict()
        record.update({
            "call_key": call_key,
            "prompt_sha256": prompt_hash,
            "provider_name": response.provider_name,
            **response.request_parameters,
        })
        self.call_records.append(record)
        return result


class LeakageGuardEnv:
    FORBIDDEN_UNFINISHED_KEYS = {"answer_from", "gold_scale", "gt_answer", "question_type", "scale"}

    def __init__(self, env: Any):
        self._env = env

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def reset(self, idx: int) -> str:
        return self._env.reset(idx=idx)

    def step(self, action: str):
        observation, reward, done, info = self._env.step(action)
        if not done and self.FORBIDDEN_UNFINISHED_KEYS & set(info or {}):
            raise StopExperiment("Runtime target metadata leaked before Finish")
        return observation, reward, done, info


class CapabilityRunner:
    def __init__(self, protocol_path: str | Path = DEFAULT_PROTOCOL_PATH, *, tier: str, env_factory=None):
        self.protocol = load_protocol(protocol_path)
        if tier not in self.protocol["models"]:
            raise StopExperiment(f"Unknown capability tier: {tier}")
        self.tier = tier
        self.publication = public_head_preflight(self.protocol)
        self.protocol_path = Path(self.protocol["_path"])
        self.manifest = load_manifest(self.protocol)
        self.env_factory = env_factory or HarmonizedEnvFactory()
        validate_manifest_against_sources(self.protocol, self.manifest, self.env_factory)
        self.snapshot_path = resolve_path(self.protocol_path, str(self.protocol["model_snapshot"]))
        validate_live_catalog(self.snapshot_path)
        self.snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        repo = Path(self.publication["repo"])
        root = Path(str(self.protocol["results"]["root"]))
        self.results_root = (repo / root / tier).resolve()
        self.results_root.mkdir(parents=True, exist_ok=True)
        body = {key: value for key, value in self.protocol.items() if key != "_path"}
        self.protocol_fingerprint = fingerprint(body)
        self.pre_result_commit = self.publication["commit"]
        self.config_path = self.results_root / "config.json"
        self.smoke_path = self.results_root / "smoke_complete.json"
        self.history_path = self.results_root / "run_history.json"
        self._write_or_validate_config()
        self.ledger = SpendLedger(self.results_root / "spend_ledger.json", self.protocol_fingerprint, tier, self.protocol["models"][tier])

    def _config(self) -> Dict[str, Any]:
        spec = self.protocol["models"][self.tier]
        return {
            "canonical_slug": spec["canonical_slug"],
            "frameworks": list(FRAMEWORKS),
            "manifest_fingerprint": self.manifest["manifest_fingerprint"],
            "pre_result_commit": self.pre_result_commit,
            "protocol_fingerprint": self.protocol_fingerprint,
            "protocol_id": self.protocol["protocol_id"],
            "requested_model_id": spec["requested_model_id"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "sample_count": 150,
            "tier": self.tier,
        }

    def _write_or_validate_config(self) -> None:
        expected = self._config()
        if self.config_path.exists():
            if json.loads(self.config_path.read_text(encoding="utf-8")) != expected:
                raise StopExperiment("Resume configuration differs from frozen run")
        else:
            write_stable_json(self.config_path, expected)

    def _path(self, dataset: str, framework: str) -> Path:
        return self.results_root / dataset / framework / "results.json"

    def _load(self, dataset: str, framework: str) -> List[Dict[str, Any]]:
        path = self._path(dataset, framework)
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len({str(row["example_id"]) for row in rows}) != len(rows):
            raise StopExperiment(f"Malformed result store: {path}")
        return rows

    def _save(self, dataset: str, framework: str, row: Dict[str, Any]) -> None:
        rows = self._load(dataset, framework)
        if any(str(saved["example_id"]) == str(row["example_id"]) for saved in rows):
            raise StopExperiment("Attempted to overwrite immutable output")
        rows.append(row)
        order = {str(item["example_id"]): n for n, item in enumerate(self.manifest["datasets"][dataset]["examples"])}
        rows.sort(key=lambda saved: order[str(saved["example_id"])])
        write_stable_json(self._path(dataset, framework), rows)

    def _pairs(self, phase: str) -> List[Tuple[str, Mapping[str, Any], str]]:
        if phase == "smoke":
            spec = self.protocol["smoke"]
            dataset = str(spec["dataset"])
            item = self.manifest["datasets"][dataset]["examples"][int(spec["item_ordinal"])]
            return [(dataset, item, framework) for framework in FRAMEWORKS]
        return [(dataset, item, framework) for dataset in DATASETS for item in self.manifest["datasets"][dataset]["examples"] for framework in FRAMEWORKS]

    def _pending(self, phase: str) -> List[Tuple[str, Mapping[str, Any], str]]:
        return [(dataset, item, framework) for dataset, item, framework in self._pairs(phase) if not any(str(row["example_id"]) == str(item["example_id"]) for row in self._load(dataset, framework))]

    def _run_pair(self, dataset: str, item: Mapping[str, Any], framework: str) -> Dict[str, Any]:
        set_active_dataset(dataset)
        env = LeakageGuardEnv(self.env_factory(dataset))
        spec = self.protocol["models"][self.tier]
        model = BudgetedCapabilityModel(self.protocol, self.snapshot, self.ledger, self.tier, f"{dataset}/{item['example_id']}/{framework}")
        workflow = self.protocol["workflows"]
        try:
            _, result = METHODS[framework](
                idx=int(item["index"]), model_id=spec["requested_model_id"], to_print=False,
                env=env, llm_func=model,
                evidence_word_budget=int(workflow["evidence_word_budget_per_item"]),
                context_word_budget=int(workflow["context_word_budget_per_call"]),
                max_retrieval_operations=int(workflow["max_retrieval_operations_per_item"]),
                max_output_tokens=int(workflow["max_output_tokens_per_call"]),
                max_steps=int(workflow["react_max_steps"]),
            )
            return self._success(dataset, item, framework, result, model)
        except Exception as exc:
            self._save(dataset, framework, {
                "call_records_before_stop": model.call_records,
                "dataset": dataset,
                "error": str(exc)[:500],
                "error_type": type(exc).__name__,
                "example_id": str(item["example_id"]),
                "framework": framework,
                "item_hash": item["item_hash"],
                "status": "provider_or_integrity_failure",
                "tier": self.tier,
            })
            raise StopExperiment(f"First provider/integrity failure stopped the study: {exc}") from exc

    def _success(self, dataset: str, item: Mapping[str, Any], framework: str, result: Mapping[str, Any], model: BudgetedCapabilityModel) -> Dict[str, Any]:
        requested = self.protocol["models"][self.tier]["requested_model_id"]
        canonical = self.protocol["models"][self.tier]["canonical_slug"]
        telemetry = aggregate_telemetry(result, requested)
        calls = telemetry["call_records"]
        prompts = list(result.get("prompt_records") or [])
        if not calls or len(calls) != len(prompts) or len(calls) != len(model.call_records):
            raise StopExperiment("Per-call telemetry or prompt coverage is incomplete")
        for call, prompt, model_call in zip(calls, prompts, model.call_records):
            if call.get("requested_model") != requested or call.get("resolved_model") != requested or call.get("status") != "ok":
                raise StopExperiment("Model/status binding mismatch")
            if model_call.get("provider_name") != "OpenAI" or model_call.get("reasoning_effort") != "none" or model_call.get("sampling_parameters_sent") != []:
                raise StopExperiment("Provider or request-parameter binding mismatch")
            if prompt["sha256"] != model_call.get("prompt_sha256") or int(prompt["word_count"]) > int(self.protocol["workflows"]["context_word_budget_per_call"]):
                raise StopExperiment("Prompt hash or context ceiling mismatch")
            call.update({
                "call_key": model_call["call_key"],
                "prompt_sha256": prompt["sha256"],
                "prompt_utf8_bytes": prompt["utf8_bytes"],
                "prompt_word_count": prompt["word_count"],
                "provider_name": "OpenAI",
                "catalog_canonical_slug": canonical,
                "reasoning_effort": "none",
                "sampling_parameters_sent": [],
            })
        if telemetry["total_tokens"] <= 0 or telemetry["latency_ms"] <= 0:
            raise StopExperiment("Usage or latency telemetry is incomplete")
        if framework == "static" and int(telemetry["llm_call_count"]) != 1:
            raise StopExperiment("Static did not use exactly one model call")
        if framework == "react" and not (
            result.get("react_action_policy") == REACT_ACTION_POLICY
            and result.get("first_model_action") == "Search"
            and result.get("react_process_integrity") is True
            and int(telemetry["llm_call_count"]) >= 2
            and int(result.get("retrieval_operation_count", 0)) >= 1
            and int(result.get("evidence_word_count", 0)) > 0
            and result.get("parse_status") == "ok"
        ):
            raise StopExperiment("ReAct treatment-integrity check failed")
        canonical_answer = str(result.get("answer") or "UNKNOWN")
        ground_truth = result.get("gt_answer", result.get("ground_truth"))
        score = finance_scoring.score_dataset(
            dataset, canonical_answer, ground_truth,
            gold_scale=result.get("gold_scale", result.get("scale", "")),
            question_type=result.get("question_type", ""),
        ).to_dict()
        trace = str(result.get("raw_trace", ""))
        provider_cost = telemetry["provider_cost_usd"]
        estimated_cost = telemetry["estimated_cost_usd"]
        return {
            "answer": canonical_answer,
            "answer_contract": "strict_json_finish_v1",
            "backend": "openrouter",
            "cached_tokens": telemetry["cached_tokens"],
            "call_records": calls,
            "context_word_budget": result["context_word_budget"],
            "dataset": dataset,
            "effective_cost_usd": provider_cost if provider_cost is not None else estimated_cost,
            "episode_wall_ms": result["episode_wall_ms"],
            "estimated_cost_usd": estimated_cost,
            "evidence_hash": result["evidence_hash"],
            "evidence_word_budget": result["evidence_word_budget"],
            "evidence_word_count": result["evidence_word_count"],
            "example_id": str(item["example_id"]),
            "first_model_action": result.get("first_model_action"),
            "framework": framework,
            "ground_truth": ground_truth,
            "input_tokens": telemetry["input_tokens"],
            "item_hash": item["item_hash"],
            "latency_ms": telemetry["latency_ms"],
            "llm_attempt_count": telemetry["llm_attempt_count"],
            "llm_call_count": telemetry["llm_call_count"],
            "malformed_fallback": result["malformed_fallback"],
            "max_prompt_word_count": result["max_prompt_word_count"],
            "method_version": result["method_version"],
            "model_actions": list(result.get("model_actions") or []),
            "native_scores": score,
            "output_tokens": telemetry["output_tokens"],
            "parse_status": result["parse_status"],
            "pre_result_commit": self.pre_result_commit,
            "prompt_hash": result["prompt_hash"],
            "prompt_records": prompts,
            "protocol_id": self.protocol["protocol_id"],
            "provider_cost_usd": provider_cost,
            "provider_name": "OpenAI",
            "question_idx": int(item["index"]),
            "raw_trace": trace,
            "react_action_policy": result.get("react_action_policy"),
            "react_process_integrity": result.get("react_process_integrity"),
            "reasoning_effort": "none",
            "reasoning_tokens": telemetry["reasoning_tokens"],
            "requested_model": requested,
            "resolved_model": requested,
            "catalog_canonical_slug": canonical,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "retrieval_operation_count": int(result["retrieval_operation_count"]),
            "retry_count": telemetry["retry_count"],
            "sampling_parameters_sent": [],
            "scorer_input_sha256": "sha256:" + hashlib.sha256(canonical_answer.encode("utf-8")).hexdigest(),
            "status": "success",
            "tier": self.tier,
            "total_tokens": telemetry["total_tokens"],
            "trace_hash": "sha256:" + hashlib.sha256(trace.encode("utf-8")).hexdigest(),
        }

    def _smoke_process_check(self) -> Dict[str, bool]:
        spec = self.protocol["smoke"]
        dataset = str(spec["dataset"])
        example_id = str(self.manifest["datasets"][dataset]["examples"][int(spec["item_ordinal"])]["example_id"])
        static = next(row for row in self._load(dataset, "static") if str(row["example_id"]) == example_id)
        react = next(row for row in self._load(dataset, "react") if str(row["example_id"]) == example_id)
        checks = {
            "binding": all(row.get("requested_model") == "openai/gpt-5.6-luna" and row.get("resolved_model") == "openai/gpt-5.6-luna" and row.get("catalog_canonical_slug") == "openai/gpt-5.6-luna-20260709" and row.get("provider_name") == "OpenAI" for row in (static, react)),
            "reasoning_effort_none": all(row.get("reasoning_effort") == "none" and row.get("sampling_parameters_sent") == [] for row in (static, react)),
            "react_evidence_observed": int(react.get("evidence_word_count", 0)) > 0,
            "react_first_action_search": react.get("first_model_action") == "Search",
            "react_minimum_calls": int(react.get("llm_call_count", 0)) >= 2,
            "react_minimum_retrieval": int(react.get("retrieval_operation_count", 0)) >= 1,
            "react_parse_ok": react.get("parse_status") == "ok",
            "static_one_call": int(static.get("llm_call_count", 0)) == 1,
            "telemetry": all(int(row.get("total_tokens", 0)) > 0 and float(row.get("effective_cost_usd", -1)) >= 0 for row in (static, react)),
        }
        if not all(checks.values()):
            raise StopExperiment(f"Counted smoke process check failed: {checks}")
        return checks

    def run(self, phase: str) -> None:
        if self.tier != "luna" and phase == "smoke":
            raise StopExperiment("Only Luna has a counted smoke phase")
        if phase == "full" and self.tier == "luna" and not self.smoke_path.exists():
            raise StopExperiment("Full Luna requires the counted two-arm smoke")
        if phase == "smoke" and self.smoke_path.exists():
            print("[COMPLETE] Counted Luna smoke already validated; no provider calls made.")
            return
        pending = self._pending(phase)
        if not pending:
            print(f"[COMPLETE] {self.tier}/{phase} already complete; no provider calls made.")
            return
        history = json.loads(self.history_path.read_text(encoding="utf-8")) if self.history_path.exists() else []
        successes = 0
        for ordinal, (dataset, item, framework) in enumerate(pending, 1):
            print(f"[{ordinal}/{len(pending)}] {self.tier}/{dataset}/{item['example_id']}/{framework}", flush=True)
            try:
                row = self._run_pair(dataset, item, framework)
            except StopExperiment:
                history.append({"attempted_pairs": ordinal, "finished_at": utc_now(), "phase": phase, "spend_usd": self.ledger.actual_spend, "status": "stopped", "successes": successes})
                write_stable_json(self.history_path, history)
                raise
            self._save(dataset, framework, row)
            successes += 1
        if phase == "smoke":
            checks = self._smoke_process_check()
            write_stable_json(self.smoke_path, {
                "completed_at": utc_now(),
                "pair_count": 2,
                "pre_result_commit": self.pre_result_commit,
                "process_checks": checks,
                "process_checks_passed": True,
                "protocol_fingerprint": self.protocol_fingerprint,
                "spend_usd": self.ledger.actual_spend,
            })
        history.append({"attempted_pairs": len(pending), "finished_at": utc_now(), "phase": phase, "spend_usd": self.ledger.actual_spend, "status": "complete", "successes": successes})
        write_stable_json(self.history_path, history)
        print(f"[COMPLETE] {self.tier}/{phase}: {successes} immutable rows; spend=${self.ledger.actual_spend:.6f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--tier", choices=("luna", "terra"), required=True)
    parser.add_argument("--phase", choices=("smoke", "full"), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    protocol = load_protocol(args.protocol)
    publication = public_head_preflight(protocol)
    snapshot_path = resolve_path(Path(protocol["_path"]), str(protocol["model_snapshot"]))
    catalog = validate_live_catalog(snapshot_path)
    run_root_probe = str(protocol["results"]["root"]).rstrip("/") + "/.ignore-probe"
    _git(Path(publication["repo"]), "check-ignore", "-q", "--no-index", run_root_probe)
    preflight = {
        "catalog": catalog,
        "credential_available": bool(os.getenv("OPENROUTER_API_KEY")),
        "publication": publication,
        "run_root_ignored": True,
    }
    if args.preflight_only:
        print(json.dumps(preflight, sort_keys=True))
        return
    if not preflight["credential_available"]:
        raise SystemExit("OPENROUTER_API_KEY is unavailable; no provider calls made")
    CapabilityRunner(
        args.protocol,
        tier=args.tier,
    ).run(args.phase)


if __name__ == "__main__":
    main()

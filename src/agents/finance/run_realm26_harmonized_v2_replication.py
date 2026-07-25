"""Execute the frozen REALM 2026 harmonized v2 corrective study."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.shared.llm import llm_with_metadata
from src.shared.llm_telemetry import LLMResult

from . import finance_scoring
from .finance_utils import set_active_dataset
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_harmonized_v2_methods import METHODS, REACT_ACTION_POLICY
from .realm26_harmonized_data import HarmonizedEnvFactory
from .realm26_harmonized_v2_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    FRAMEWORKS,
    load_manifest,
    load_protocol,
    resolve_path,
    validate_manifest_against_sources,
)
from .run_finance_experiments import aggregate_telemetry


RESULT_SCHEMA_VERSION = "realm26-harmonized-result-v2"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StopExperiment(ProtocolError):
    """A frozen stop condition fired; no further provider call is permitted."""


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise StopExperiment(
            f"Git preflight failed: git {' '.join(args)}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def public_freeze_preflight(protocol: Mapping[str, Any]) -> Dict[str, str]:
    """Require the exact clean frozen commit to exist on the public remote branch."""

    protocol_path = Path(str(protocol["_path"]))
    repo = Path(_git(protocol_path.parent, "rev-parse", "--show-toplevel"))
    publication = protocol["publication"]
    branch = _git(repo, "branch", "--show-current")
    if branch != publication["branch"]:
        raise StopExperiment(f"Execution branch {branch!r} is not the frozen task branch")
    head = _git(repo, "rev-parse", "HEAD")
    status_lines = _git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    configured_root = Path(str(protocol["results"]["root"]))
    allowed_prefix = configured_root.as_posix().rstrip("/") + "/"
    unexpected = []
    for line in status_lines:
        path = line[3:].split(" -> ")[-1]
        if not (path == configured_root.as_posix() or path.startswith(allowed_prefix)):
            unexpected.append(line)
    if unexpected:
        raise StopExperiment(f"Frozen tree has non-result changes: {unexpected}")
    remote = str(publication["remote"])
    ref = f"refs/heads/{branch}"
    remote_rows = _git(repo, "ls-remote", "--heads", remote, ref).splitlines()
    if len(remote_rows) != 1 or remote_rows[0].split()[0] != head:
        raise StopExperiment("HEAD is not the exact publicly pushed frozen branch tip")
    return {"branch": branch, "commit": head, "remote": remote, "repo": str(repo)}


class SpendLedger:
    """Persistent pre-call reservations under the exact frozen USD cap."""

    def __init__(self, path: Path, protocol_fingerprint: str, cap_usd: float):
        self.path = path
        self.protocol_fingerprint = protocol_fingerprint
        self.cap_usd = float(cap_usd)
        if self.cap_usd != 5.0:
            raise StopExperiment("Spend ledger requires the frozen USD 5 hard cap")
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            if self.data.get("protocol_fingerprint") != protocol_fingerprint:
                raise StopExperiment("Spend ledger belongs to another protocol")
            if float(self.data.get("hard_cap_usd", -1)) != self.cap_usd:
                raise StopExperiment("Spend ledger cap mismatch")
        else:
            self.data = {
                "actual_spend_usd": 0.0,
                "calls": [],
                "hard_cap_usd": self.cap_usd,
                "pending_reservations": [],
                "protocol_fingerprint": protocol_fingerprint,
                "schema_version": "realm26-harmonized-spend-ledger-v2",
            }
            self._write()
        if self.data.get("pending_reservations"):
            raise StopExperiment("Unresolved spend reservation after interruption")

    @property
    def actual_spend(self) -> float:
        return float(self.data.get("actual_spend_usd", 0.0))

    def _write(self) -> None:
        write_stable_json(self.path, self.data)

    def reserve(self, call_key: str, maximum_cost_usd: float, prompt_sha256: str) -> None:
        existing = {str(row["call_key"]) for row in self.data["calls"]}
        pending = {str(row["call_key"]) for row in self.data["pending_reservations"]}
        if call_key in existing or call_key in pending:
            raise StopExperiment("Duplicate immutable spend-ledger call key")
        maximum = float(maximum_cost_usd)
        if maximum <= 0 or self.actual_spend + maximum > self.cap_usd + 1e-12:
            raise StopExperiment("USD 5 hard cap would be exceeded by the next call")
        self.data["pending_reservations"].append({
            "call_key": call_key,
            "maximum_cost_usd": maximum,
            "prompt_sha256": prompt_sha256,
            "reserved_at": utc_now(),
        })
        self._write()

    def complete(self, call_key: str, result: LLMResult, estimated_cost: float) -> None:
        pending = self.data["pending_reservations"]
        matches = [row for row in pending if row["call_key"] == call_key]
        if len(matches) != 1:
            raise StopExperiment("Spend reservation identity mismatch")
        reservation = float(matches[0]["maximum_cost_usd"])
        charge = result.provider_cost_usd
        if charge is None and result.total_tokens > 0:
            charge = estimated_cost
        if charge is None:
            charge = reservation
        charge = float(charge)
        if charge < 0 or charge > reservation + 1e-9:
            raise StopExperiment("Provider charge exceeded frozen reservation")
        total = self.actual_spend + charge
        if total > self.cap_usd + 1e-12:
            raise StopExperiment("Provider spend breached the USD 5 hard cap")
        self.data["pending_reservations"] = [row for row in pending if row["call_key"] != call_key]
        self.data["actual_spend_usd"] = total
        self.data["calls"].append({
            "actual_cost_usd": charge,
            "backend": result.backend,
            "cached_tokens": result.cached_tokens,
            "call_key": call_key,
            "completed_at": utc_now(),
            "estimated_cost_usd": estimated_cost,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "prompt_sha256": matches[0]["prompt_sha256"],
            "provider_cost_usd": result.provider_cost_usd,
            "provider_route_requested": "OpenAI",
            "reasoning_tokens": result.reasoning_tokens,
            "requested_model": result.requested_model,
            "reserved_maximum_cost_usd": reservation,
            "resolved_model": result.resolved_model,
            "retry_count": result.retry_count,
            "status": result.status,
            "total_tokens": result.total_tokens,
        })
        self._write()


class BudgetedModel:
    """One-attempt, zero-temperature, exact-binding model wrapper with telemetry."""

    def __init__(self, protocol: Mapping[str, Any], snapshot: Mapping[str, Any], ledger: SpendLedger, pair_key: str):
        self.protocol = protocol
        self.snapshot = snapshot
        self.ledger = ledger
        self.pair_key = pair_key
        self.call_index = 0
        self.call_records: List[Dict[str, Any]] = []
        pricing = snapshot["endpoint"]["pricing"]
        self.input_rate = float(pricing["prompt"])
        self.output_rate = float(pricing["completion"])
        self.cache_rate = float(pricing.get("input_cache_read", pricing["prompt"]))

    def _estimate(self, result: LLMResult) -> float:
        cached = min(result.cached_tokens, result.input_tokens)
        return ((result.input_tokens - cached) * self.input_rate + cached * self.cache_rate + result.output_tokens * self.output_rate)

    def __call__(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        num_traces: int = 1,
        max_tokens: int = 384,
        model_id: Optional[str] = None,
        return_metadata: bool = True,
        **_: Any,
    ) -> LLMResult:
        inference = self.protocol["inference"]
        expected = str(inference["model_id"])
        frozen_max = int(self.protocol["workflows"]["max_output_tokens_per_call"])
        if model_id != expected or temperature not in (None, 0, 0.0) or num_traces != 1:
            raise StopExperiment("Per-call model or sampling binding changed")
        if int(max_tokens) != frozen_max:
            raise StopExperiment("Per-call output ceiling changed")
        self.call_index += 1
        call_key = f"{self.pair_key}/call-{self.call_index}"
        prompt_hash = "sha256:" + hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()
        maximum = (
            len(str(prompt).encode("utf-8")) * self.input_rate + frozen_max * self.output_rate
        ) * float(self.protocol["budget"]["reservation_multiplier"])
        self.ledger.reserve(call_key, maximum, prompt_hash)
        result = llm_with_metadata(
            str(prompt),
            stop=[] if stop is None else stop,
            temperature=0,
            num_traces=1,
            max_tokens=frozen_max,
            model_id=expected,
            backend="openrouter",
            max_retries=1,
        )
        estimated = self._estimate(result)
        if result.estimated_cost_usd is None:
            result = replace(result, estimated_cost_usd=estimated)
        self.ledger.complete(call_key, result, estimated)
        record = result.to_dict()
        record.update({
            "call_key": call_key,
            "prompt_sha256": prompt_hash,
            "provider_route_requested": "OpenAI",
        })
        self.call_records.append(record)
        if result.requested_model != expected or result.resolved_model != expected:
            raise StopExperiment("Requested/resolved model mismatch")
        if result.backend != "openrouter":
            raise StopExperiment("Backend mismatch")
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
        if not done:
            leaked = self.FORBIDDEN_UNFINISHED_KEYS & set(info or {})
            if leaked:
                raise StopExperiment(f"Runtime target-metadata leakage: {sorted(leaked)}")
        return observation, reward, done, info


class HarmonizedV2Runner:
    def __init__(self, protocol_path: str | Path = DEFAULT_PROTOCOL_PATH, *, results_root: Optional[str | Path] = None, env_factory=None, llm_factory=BudgetedModel):
        self.protocol = load_protocol(protocol_path)
        self.publication = public_freeze_preflight(self.protocol)
        self.protocol_path = Path(self.protocol["_path"])
        self.manifest = load_manifest(self.protocol)
        self.env_factory = env_factory or HarmonizedEnvFactory()
        validate_manifest_against_sources(self.protocol, self.manifest, self.env_factory)
        self.snapshot = json.loads(resolve_path(self.protocol_path, str(self.protocol["model_snapshot"])).read_text(encoding="utf-8"))
        repo = Path(self.publication["repo"])
        root = Path(results_root or self.protocol["results"]["root"])
        self.results_root = root if root.is_absolute() else (repo / root).resolve()
        self.results_root.mkdir(parents=True, exist_ok=True)
        body = {key: value for key, value in self.protocol.items() if key != "_path"}
        self.protocol_fingerprint = fingerprint(body)
        self.config_path = self.results_root / "config.json"
        self.smoke_path = self.results_root / "smoke_complete.json"
        self.history_path = self.results_root / "run_history.json"
        self._write_or_validate_config()
        self.ledger = SpendLedger(self.results_root / "spend_ledger.json", self.protocol_fingerprint, float(self.protocol["budget"]["hard_cap_usd"]))
        self.llm_factory = llm_factory

    def _config(self) -> Dict[str, Any]:
        return {
            "frameworks": list(FRAMEWORKS),
            "manifest_fingerprint": self.manifest["manifest_fingerprint"],
            "model_id": self.protocol["inference"]["model_id"],
            "pre_result_commit": self.publication["commit"],
            "protocol_fingerprint": self.protocol_fingerprint,
            "protocol_id": self.protocol["protocol_id"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "sample_count": 150,
            "seed": self.protocol["seed"],
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
        ids = [str(row["example_id"]) for row in rows]
        if not isinstance(rows, list) or len(ids) != len(set(ids)):
            raise StopExperiment(f"Malformed or duplicate result store: {path}")
        return rows

    def _save(self, dataset: str, framework: str, row: Dict[str, Any]) -> None:
        rows = self._load(dataset, framework)
        if any(str(saved["example_id"]) == str(row["example_id"]) for saved in rows):
            raise StopExperiment("Attempted to overwrite immutable result")
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

    def _success(self, dataset: str, item: Mapping[str, Any], framework: str, result: Mapping[str, Any], model: BudgetedModel) -> Dict[str, Any]:
        telemetry = aggregate_telemetry(result, self.protocol["inference"]["model_id"])
        calls = telemetry["call_records"]
        prompts = list(result.get("prompt_records") or [])
        if not calls or len(calls) != len(prompts) or len(calls) != len(model.call_records):
            raise StopExperiment("Per-call telemetry/prompt coverage is incomplete")
        expected = self.protocol["inference"]["model_id"]
        for call, prompt, model_call in zip(calls, prompts, model.call_records):
            if call.get("requested_model") != expected or call.get("resolved_model") != expected or call.get("status") != "ok":
                raise StopExperiment("Successful pair violates exact model/status binding")
            if call.get("backend") != "openrouter" or int(prompt["word_count"]) > int(self.protocol["workflows"]["context_word_budget_per_call"]):
                raise StopExperiment("Successful pair violates backend/context binding")
            if prompt["sha256"] != model_call.get("prompt_sha256"):
                raise StopExperiment("Per-call prompt telemetry hash mismatch")
            call["provider_route_requested"] = "OpenAI"
            call["call_key"] = model_call["call_key"]
            call["prompt_sha256"] = prompt["sha256"]
            call["prompt_utf8_bytes"] = prompt["utf8_bytes"]
            call["prompt_word_count"] = prompt["word_count"]
        if telemetry["total_tokens"] <= 0 or telemetry["latency_ms"] <= 0:
            raise StopExperiment("Exact usage/latency telemetry is incomplete")
        if framework == "static" and int(telemetry["llm_call_count"]) != 1:
            raise StopExperiment("Static did not enact its frozen one-call treatment")
        if framework == "react":
            process_ok = (
                result.get("react_action_policy") == REACT_ACTION_POLICY
                and result.get("first_model_action") == "Search"
                and bool(result.get("react_process_integrity"))
                and int(telemetry["llm_call_count"]) >= int(self.protocol["workflows"]["react_min_model_calls"])
                and int(result.get("retrieval_operation_count", 0)) >= int(self.protocol["workflows"]["react_min_evidence_operations"])
                and int(result.get("evidence_word_count", 0)) > 0
                and result.get("parse_status") == "ok"
            )
            if not process_ok:
                raise StopExperiment("ReAct treatment-integrity check failed")
        canonical_answer = str(result.get("answer") or "UNKNOWN")
        ground_truth = result.get("gt_answer", result.get("ground_truth"))
        score = finance_scoring.score_dataset(
            dataset,
            canonical_answer,
            ground_truth,
            gold_scale=result.get("gold_scale", result.get("scale", "")),
            question_type=result.get("question_type", ""),
        ).to_dict()
        trace = str(result.get("raw_trace", ""))
        provider_cost = telemetry["provider_cost_usd"]
        estimated_cost = telemetry["estimated_cost_usd"]
        return {
            "answer": canonical_answer,
            "answer_contract": "strict_json_finish_v1",
            "backend": telemetry["backend"],
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
            "first_model_action": result.get("first_model_action"),
            "model_actions": list(result.get("model_actions") or []),
            "native_scores": score,
            "output_tokens": telemetry["output_tokens"],
            "parse_status": result["parse_status"],
            "pre_result_commit": self.publication["commit"],
            "prompt_hash": result["prompt_hash"],
            "prompt_records": prompts,
            "protocol_id": self.protocol["protocol_id"],
            "provider_cost_usd": provider_cost,
            "provider_route_requested": "OpenAI",
            "question_idx": int(item["index"]),
            "raw_trace": trace,
            "react_action_policy": result.get("react_action_policy"),
            "react_process_integrity": result.get("react_process_integrity"),
            "reasoning_tokens": telemetry["reasoning_tokens"],
            "requested_model": expected,
            "resolved_model": telemetry["resolved_model"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "retrieval_operation_count": int(result["retrieval_operation_count"]),
            "retry_count": telemetry["retry_count"],
            "scorer_input_sha256": "sha256:" + hashlib.sha256(canonical_answer.encode("utf-8")).hexdigest(),
            "status": "success",
            "total_tokens": telemetry["total_tokens"],
            "trace_hash": "sha256:" + hashlib.sha256(trace.encode("utf-8")).hexdigest(),
        }

    def _failure(self, dataset: str, item: Mapping[str, Any], framework: str, exc: BaseException, model: BudgetedModel) -> Dict[str, Any]:
        return {
            "call_records_before_stop": model.call_records,
            "dataset": dataset,
            "error": str(exc)[:500],
            "error_type": type(exc).__name__,
            "example_id": str(item["example_id"]),
            "framework": framework,
            "item_hash": item["item_hash"],
            "protocol_id": self.protocol["protocol_id"],
            "question_idx": int(item["index"]),
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "status": "provider_or_integrity_failure",
        }

    def _run_pair(self, dataset: str, item: Mapping[str, Any], framework: str) -> Dict[str, Any]:
        set_active_dataset(dataset)
        env = LeakageGuardEnv(self.env_factory(dataset))
        model = self.llm_factory(self.protocol, self.snapshot, self.ledger, f"{dataset}/{item['example_id']}/{framework}")
        workflow = self.protocol["workflows"]
        try:
            _, result = METHODS[framework](
                idx=int(item["index"]),
                model_id=self.protocol["inference"]["model_id"],
                to_print=False,
                env=env,
                llm_func=model,
                evidence_word_budget=int(workflow["evidence_word_budget_per_item"]),
                context_word_budget=int(workflow["context_word_budget_per_call"]),
                max_retrieval_operations=int(workflow["max_retrieval_operations_per_item"]),
                max_output_tokens=int(workflow["max_output_tokens_per_call"]),
                max_steps=int(workflow["react_max_steps"]),
            )
            return self._success(dataset, item, framework, result, model)
        except Exception as exc:
            self._save(dataset, framework, self._failure(dataset, item, framework, exc, model))
            raise StopExperiment(f"First provider/integrity failure stopped the study: {exc}") from exc

    def _history(self, phase: str, attempted: int, successes: int, status: str) -> None:
        rows = json.loads(self.history_path.read_text(encoding="utf-8")) if self.history_path.exists() else []
        rows.append({"attempted_pairs": attempted, "finished_at": utc_now(), "phase": phase, "spend_usd": self.ledger.actual_spend, "status": status, "successes": successes})
        write_stable_json(self.history_path, rows)

    def _smoke_process_check(self) -> Dict[str, Any]:
        """Validate only predeclared process fields; never read answers or scores."""

        spec = self.protocol["smoke"]
        dataset = str(spec["dataset"])
        item = self.manifest["datasets"][dataset]["examples"][int(spec["item_ordinal"])]
        example_id = str(item["example_id"])
        static_rows = [row for row in self._load(dataset, "static") if str(row["example_id"]) == example_id]
        react_rows = [row for row in self._load(dataset, "react") if str(row["example_id"]) == example_id]
        if len(static_rows) != 1 or len(react_rows) != 1:
            raise StopExperiment("Smoke process check requires exactly one row per arm")
        static = static_rows[0]
        react = react_rows[0]
        checks = {
            "react_evidence_observed": int(react.get("evidence_word_count", 0)) > 0,
            "react_first_action_search": react.get("first_model_action") == "Search",
            "react_minimum_calls_met": int(react.get("llm_call_count", 0)) >= int(self.protocol["workflows"]["react_min_model_calls"]),
            "react_minimum_retrieval_met": int(react.get("retrieval_operation_count", 0)) >= int(self.protocol["workflows"]["react_min_evidence_operations"]),
            "react_parse_ok": react.get("parse_status") == "ok",
            "react_process_integrity": react.get("react_process_integrity") is True,
            "static_one_call": int(static.get("llm_call_count", 0)) == 1,
        }
        if not all(checks.values()):
            raise StopExperiment(f"Frozen smoke manipulation check failed: {checks}")
        return checks

    def _validate_smoke_marker(self) -> None:
        marker = json.loads(self.smoke_path.read_text(encoding="utf-8"))
        if (
            marker.get("pre_result_commit") != self.publication["commit"]
            or marker.get("protocol_fingerprint") != self.protocol_fingerprint
            or marker.get("process_checks_passed") is not True
            or not all((marker.get("process_checks") or {}).values())
        ):
            raise StopExperiment("Smoke marker does not prove the frozen v2 manipulation check")

    def run(self, phase: str) -> None:
        if phase == "full" and not self.smoke_path.exists():
            raise StopExperiment("Full run requires the frozen two-arm smoke")
        if phase == "full":
            self._validate_smoke_marker()
        if phase == "smoke" and self.smoke_path.exists():
            print("[COMPLETE] Smoke already validated; no provider calls made.")
            return
        pending = self._pending(phase)
        if not pending:
            if phase == "full":
                print("[COMPLETE] Full run already complete; no provider calls made.")
                return
            raise StopExperiment("Smoke rows exist without a smoke marker")
        successes = 0
        for ordinal, (dataset, item, framework) in enumerate(pending, 1):
            print(f"[{ordinal}/{len(pending)}] {dataset}/{item['example_id']}/{framework}", flush=True)
            try:
                row = self._run_pair(dataset, item, framework)
            except StopExperiment:
                self._history(phase, ordinal, successes, "stopped")
                raise
            self._save(dataset, framework, row)
            successes += 1
        if phase == "smoke":
            try:
                process_checks = self._smoke_process_check()
            except StopExperiment:
                self._history(phase, len(pending), successes, "stopped")
                raise
            self._history(phase, len(pending), successes, "complete")
            write_stable_json(self.smoke_path, {
                "completed_at": utc_now(),
                "pair_count": 2,
                "pre_result_commit": self.publication["commit"],
                "protocol_fingerprint": self.protocol_fingerprint,
                "process_checks": process_checks,
                "process_checks_passed": True,
                "spend_usd": self.ledger.actual_spend,
                "telemetry_complete": True,
            })
            print(f"[SMOKE PASS] exact binding, telemetry, and ReAct process integrity validated; spend USD {self.ledger.actual_spend:.6f}; outcomes not summarized.")
        else:
            self._history(phase, len(pending), successes, "complete")
            print(f"[RUN COMPLETE] 300 paired-arm rows persisted; spend USD {self.ledger.actual_spend:.6f}.")


def preflight(protocol_path: str | Path = DEFAULT_PROTOCOL_PATH) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    llm_module = importlib.import_module("src.shared.llm")
    if float(llm_module.LLM_DELAY) != float(protocol["inference"]["inter_call_delay_seconds"]):
        raise StopExperiment("LLM_DELAY differs from the frozen inter-call delay")
    publication = public_freeze_preflight(protocol)
    credential = bool(os.getenv("OPENROUTER_API_KEY"))
    return {"artifact_guard": "passed", "credential_available": credential, "pre_result_commit": publication["commit"], "public_push_guard": "passed"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--phase", choices=("smoke", "full"))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dotenv", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.dotenv:
        from dotenv import load_dotenv
        load_dotenv(args.dotenv, override=False)
    report = preflight(args.protocol)
    if args.preflight_only:
        print(json.dumps(report, sort_keys=True))
        return
    if not args.phase:
        raise SystemExit("--phase is required unless --preflight-only is used")
    if not report["credential_available"]:
        raise SystemExit("OPENROUTER_API_KEY is unavailable; no provider calls made")
    HarmonizedV2Runner(args.protocol).run(args.phase)


if __name__ == "__main__":
    main()

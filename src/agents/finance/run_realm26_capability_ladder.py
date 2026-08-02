"""Run the prospectively frozen three-tier REALM robustness study.

The executor deliberately does not calculate or print outcome statistics.  It
only persists immutable episode records and, after every scheduled episode has
completed, a process-only completion record for the separately frozen analyzer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.shared.llm_telemetry import LLMResult

from .finance_utils import set_active_dataset
from .protocol_v2 import ProtocolError, fingerprint, write_stable_json
from .realm26_capability_llm import call_capability_model, validate_live_catalog
from .realm26_capability_methods import METHODS
from .realm26_capability_protocol import (
    DATASETS,
    DEFAULT_PROTOCOL_PATH,
    FRAMEWORKS,
    TIERS,
    load_manifest,
    load_protocol,
    resolve_path,
    validate_manifest_against_sources,
)
from .realm26_harmonized_data import HarmonizedEnvFactory
from .realm26_harmonized_v2_methods import REACT_ACTION_POLICY
from .run_finance_experiments import aggregate_telemetry


RESULT_SCHEMA_VERSION = "realm26-capability-result-v2"


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


def load_probe_protocol(path: str | Path) -> Dict[str, Any]:
    """Load the pre-freeze probe contract without requiring frozen artifacts."""

    protocol_path = Path(path).resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["_path"] = str(protocol_path)
    if protocol.get("freeze_state") not in {"draft_pre_probe", "frozen"}:
        raise StopExperiment("Format probes require the prospective pre-probe or frozen contract")
    if tuple(protocol.get("models", {})) != tuple(TIERS):
        raise StopExperiment("Format probes require control, Luna, and Terra")
    budget = protocol.get("budget") or {}
    probe_reservation = sum(float(protocol["models"][tier]["maximum_reserved_probe_cost_usd"]) for tier in TIERS)
    prior_probe_attempts = float(budget.get("format_probe_prior_attempt_allowance_usd", 0.0))
    if abs(probe_reservation - float(budget.get("format_probe_maximum_reservation_usd", -1))) > 1e-12:
        raise StopExperiment("Format-probe reservation does not reconcile across tiers")
    if (
        float(budget.get("prior_failed_attempt_allowance_usd", -1))
        + float(budget.get("prior_failed_frozen_study_allowance_usd", 0.0))
        + prior_probe_attempts
        + float(budget.get("format_probe_actual_spend_usd", 0.0))
        + probe_reservation
        + float(budget.get("study_maximum_reservation_usd", -1))
        > float(budget.get("hard_cap_usd", -1)) + 1e-12
    ):
        raise StopExperiment("Format probes are not guaranteed within the cumulative hard cap")
    if (protocol.get("inference") or {}).get("reasoning_effort_by_tier") != {
        "control": None, "luna": "none", "terra": "none",
    }:
        raise StopExperiment("Authorized reasoning-parameter exception changed")
    return protocol


def _budget_value(spec: Mapping[str, Any], names: Sequence[str], *, default: Optional[float] = None) -> float:
    present = [name for name in names if name in spec]
    if len(present) > 1:
        values = {float(spec[name]) for name in present}
        if len(values) != 1:
            raise StopExperiment(f"Conflicting cumulative-budget fields: {present}")
    if present:
        return float(spec[present[0]])
    if default is not None:
        return float(default)
    raise StopExperiment(f"Missing cumulative-budget field (one of {list(names)})")


def cumulative_budget_contract(protocol: Mapping[str, Any]) -> Dict[str, float]:
    """Normalize the frozen overall cap and already-incurred charges.

    Older freezes called the conservative prior charge an ``allowance``; newer
    freezes call it spend.  Both names have the same fail-closed semantics here.
    Live probe spend is separate and may not be hidden inside a tier allowance.
    """

    budget = protocol.get("budget") or {}
    hard_cap = _budget_value(
        budget,
        ("cumulative_hard_cap_usd", "total_hard_cap_usd", "hard_cap_usd", "authorized_total_usd"),
        default=20.0,
    )
    prior = _budget_value(
        budget,
        ("prior_failed_attempt_spend_usd", "prior_failed_attempt_charge_usd", "prior_failed_attempt_allowance_usd"),
        default=0.0,
    )
    prior += float(budget.get("prior_failed_frozen_study_allowance_usd", 0.0))
    probes = (
        float(budget.get("format_probe_prior_attempt_allowance_usd", 0.0))
        + float(budget.get("format_probe_actual_spend_usd", 0.0))
    )
    if hard_cap <= 0 or prior < 0 or probes < 0:
        raise StopExperiment("Cumulative budget values must be non-negative with a positive hard cap")
    reserved_study = _budget_value(
        budget,
        ("study_maximum_reservation_usd",),
        default=sum(float(protocol["models"][tier].get("maximum_reserved_study_cost_usd", 0.0)) for tier in TIERS),
    )
    if prior + probes + reserved_study > hard_cap + 1e-12:
        raise StopExperiment("The complete three-tier study is not guaranteed within the cumulative hard cap")
    return {
        "cumulative_hard_cap_usd": hard_cap,
        "format_probe_spend_usd": probes,
        "prior_failed_attempt_spend_usd": prior,
        "reserved_study_cost_usd": reserved_study,
    }


class CumulativeBudgetGuard:
    """One persistent ledger for prior attempts, probes, and all study tiers."""

    def __init__(
        self,
        contract: Mapping[str, float],
        *,
        path: Optional[Path] = None,
        protocol_fingerprint: str = "sha256:unspecified",
        models: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ):
        self.cap = float(contract["cumulative_hard_cap_usd"])
        self.baseline = float(contract["prior_failed_attempt_spend_usd"]) + float(contract["format_probe_spend_usd"])
        self.path = path
        self.protocol_fingerprint = protocol_fingerprint
        self.models = dict(models or {})
        expected = {
            "actual_study_spend_usd": 0.0,
            "calls": [],
            "cumulative_hard_cap_usd": self.cap,
            "format_probe_spend_or_reservation_usd": float(contract["format_probe_spend_usd"]),
            "pending_reservations": [],
            "prior_failed_attempt_spend_usd": float(contract["prior_failed_attempt_spend_usd"]),
            "protocol_fingerprint": protocol_fingerprint,
            "schema_version": "realm26-capability-cumulative-spend-ledger-v1",
        }
        if path is not None and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = expected
            self._write()
        for key in (
            "cumulative_hard_cap_usd",
            "format_probe_spend_or_reservation_usd",
            "prior_failed_attempt_spend_usd",
            "protocol_fingerprint",
            "schema_version",
        ):
            if self.data.get(key) != expected[key]:
                raise StopExperiment("Cumulative spend ledger differs from the frozen budget contract")
        if self.data.get("pending_reservations"):
            raise StopExperiment("Unresolved cumulative spend reservation after interruption")
        if self.current_spend > self.cap + 1e-12:
            raise StopExperiment("Existing cumulative spend exceeds the frozen hard cap")

    def _write(self) -> None:
        if self.path is not None:
            write_stable_json(self.path, self.data)

    @property
    def current_spend(self) -> float:
        return self.baseline + float(self.data.get("actual_study_spend_usd", 0.0))

    def tier_view(self, tier: str) -> "CumulativeTierView":
        if tier not in self.models:
            raise StopExperiment(f"Unknown tier for cumulative spend ledger: {tier}")
        return CumulativeTierView(self, tier)

    def reserve(self, tier: str, call_key: str, prompt_hash: str) -> None:
        maximum_cost = float(self.models[tier]["maximum_reserved_call_cost_usd"])
        used = {str(row["call_key"]) for row in self.data["calls"]}
        if call_key in used:
            raise StopExperiment("Cumulative ledger would duplicate a provider call")
        if self.current_spend + maximum_cost > self.cap + 1e-12:
            raise StopExperiment("Next call would exceed the cumulative USD 20 hard cap")
        self.data["pending_reservations"] = [{
            "call_key": call_key,
            "maximum_cost_usd": maximum_cost,
            "prompt_sha256": prompt_hash,
            "reserved_at": utc_now(),
            "tier": tier,
        }]
        self._write()

    def complete(self, tier: str, call_key: str, response: Any, estimated_cost: float) -> None:
        pending = self.data["pending_reservations"]
        if len(pending) != 1 or pending[0]["call_key"] != call_key or pending[0]["tier"] != tier:
            raise StopExperiment("Cumulative spend reservation identity mismatch")
        result: LLMResult = response.result
        charge = float(result.provider_cost_usd if result.provider_cost_usd is not None else estimated_cost)
        if charge < 0 or charge > float(pending[0]["maximum_cost_usd"]) + 1e-12:
            raise StopExperiment(f"{tier}: provider charge exceeded the frozen call reservation")
        if self.current_spend + charge > self.cap + 1e-12:
            raise StopExperiment("Provider charge breached the cumulative USD 20 hard cap")
        self.data["pending_reservations"] = []
        self.data["actual_study_spend_usd"] = float(self.data["actual_study_spend_usd"]) + charge
        self.data["calls"].append({
            "actual_cost_usd": charge,
            "call_key": call_key,
            "completed_at": utc_now(),
            "estimated_cost_usd": estimated_cost,
            "finish_reason": response.finish_reason,
            "maximum_reserved_call_cost_usd": pending[0]["maximum_cost_usd"],
            "prompt_sha256": pending[0]["prompt_sha256"],
            "provider_cost_usd": result.provider_cost_usd,
            "tier": tier,
        })
        self._write()


class CumulativeTierView:
    """Tier-bound interface used by the model wrapper over the global ledger."""

    def __init__(self, ledger: CumulativeBudgetGuard, tier: str):
        self.ledger = ledger
        self.tier = tier

    @property
    def actual_spend(self) -> float:
        return sum(float(row["actual_cost_usd"]) for row in self.ledger.data["calls"] if row["tier"] == self.tier)

    def reserve(self, call_key: str, prompt_hash: str) -> None:
        self.ledger.reserve(self.tier, call_key, prompt_hash)

    def complete(self, call_key: str, response: Any, estimated_cost: float) -> None:
        self.ledger.complete(self.tier, call_key, response, estimated_cost)


class BudgetedCapabilityModel:
    def __init__(self, protocol: Mapping[str, Any], snapshot: Mapping[str, Any], ledger: CumulativeTierView, tier: str, pair_key: str, framework: str):
        self.protocol = protocol
        self.ledger = ledger
        self.tier = tier
        self.pair_key = pair_key
        self.framework = framework
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
        sleep(float(self.protocol["inference"]["inter_call_delay_seconds"]))
        self.ledger.reserve(call_key, prompt_hash)
        response = call_capability_model(
            prompt=str(prompt), requested_model=expected,
            canonical_slug=str(self.spec["canonical_slug"]), max_tokens=int(max_tokens),
            action_schema="finish" if self.framework == "static" else ("search" if self.call_index == 1 else "react"),
            seed=int(self.protocol["inference"]["request_seed"]),
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
            "finish_reason": response.finish_reason,
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


def normalized_execution_schedule(
    manifest: Mapping[str, Any],
    *,
    tiers: Sequence[str] = TIERS,
    frameworks: Sequence[str] = FRAMEWORKS,
) -> List[Tuple[str, str, str, str]]:
    """Validate and flatten the frozen counterbalanced execution schedule."""

    schedule = manifest.get("execution_schedule")
    rows = schedule.get("items") if isinstance(schedule, Mapping) else None
    if not isinstance(schedule, Mapping) or not isinstance(schedule.get("schedule_seed"), int):
        raise StopExperiment("Manifest execution_schedule is missing its frozen seed")
    if not isinstance(rows, list) or not rows:
        raise StopExperiment("Manifest has no frozen execution_schedule")
    item_keys = {
        (str(dataset), str(item["example_id"]))
        for dataset in DATASETS
        for item in manifest["datasets"][dataset]["examples"]
    }
    if len(rows) != len(item_keys):
        raise StopExperiment("Execution schedule must contain exactly one row per study item")
    seen: set[Tuple[str, str]] = set()
    flattened: List[Tuple[str, str, str, str]] = []
    model_positions: Dict[str, Counter[int]] = {tier: Counter() for tier in tiers}
    static_first: Counter[str] = Counter()
    permutation_counts: Counter[Tuple[str, ...]] = Counter()
    positions: List[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise StopExperiment("Malformed execution schedule row")
        if not isinstance(row.get("position"), int):
            raise StopExperiment("Execution schedule position is missing or malformed")
        positions.append(int(row["position"]))
        dataset, example_id = str(row.get("dataset_id")), str(row.get("example_id"))
        key = (dataset, example_id)
        if key not in item_keys or key in seen:
            raise StopExperiment("Execution schedule contains an unknown or duplicate item")
        seen.add(key)
        model_order = tuple(str(value) for value in row.get("model_order", []))
        if len(model_order) != len(tiers) or set(model_order) != set(tiers):
            raise StopExperiment("Every schedule row must execute every mandatory tier exactly once")
        permutation_counts[model_order] += 1
        arm_spec = row.get("framework_order_by_tier")
        if not isinstance(arm_spec, Mapping) or set(arm_spec) != set(tiers):
            raise StopExperiment("framework_order_by_tier must bind every mandatory tier")
        by_tier = {tier: tuple(str(value) for value in arm_spec[tier]) for tier in tiers}
        for position, tier in enumerate(model_order):
            arms = by_tier[tier]
            if len(arms) != len(frameworks) or set(arms) != set(frameworks):
                raise StopExperiment("Every scheduled tier must execute Static and ReAct exactly once")
            model_positions[tier][position] += 1
            static_first[tier] += int(arms[0] == "static")
            flattened.extend((dataset, example_id, tier, framework) for framework in arms)
    if seen != item_keys:
        raise StopExperiment("Execution schedule does not cover the frozen manifest")
    if positions != list(range(len(rows))):
        raise StopExperiment("Execution schedule positions must be ordered, contiguous, and zero-based")
    if len(permutation_counts) != 6 or set(permutation_counts.values()) != {25}:
        raise StopExperiment("Model-order schedule must use all six permutations exactly 25 times")
    # Exact balance is possible for the frozen 150-item, three-tier/two-arm study.
    for tier in tiers:
        if len(set(model_positions[tier].values())) != 1:
            raise StopExperiment("Model-order schedule is not position-balanced")
        if static_first[tier] * 2 != len(rows):
            raise StopExperiment("Static/ReAct episode order is not balanced within tier")
    return flattened


def run_format_probes(protocol: Mapping[str, Any], repo: Path) -> None:
    """Run nine synthetic schema probes before any benchmark item is selected."""

    root = (repo / Path(str(protocol["results"]["root"])) / "format_probes").resolve()
    completion_path = root / "probe_complete.json"
    failure_path = root / "probe_failure.json"
    if failure_path.exists():
        raise StopExperiment("A prior prospective format probe failed; repair requires a new freeze")
    if completion_path.exists():
        return
    budget = protocol["budget"]
    contract = {
        "cumulative_hard_cap_usd": float(budget["hard_cap_usd"]),
        "format_probe_spend_usd": 0.0,
        "prior_failed_attempt_spend_usd": (
            float(budget["prior_failed_attempt_allowance_usd"])
            + float(budget.get("prior_failed_frozen_study_allowance_usd", 0.0))
            + float(budget.get("format_probe_prior_attempt_allowance_usd", 0.0))
            + float(budget.get("format_probe_actual_spend_usd", 0.0))
        ),
    }
    protocol_body = {key: value for key, value in protocol.items() if key != "_path"}
    protocol_fingerprint = fingerprint(protocol_body)
    ledger = CumulativeBudgetGuard(
        contract,
        path=root / "cumulative_spend_ledger.json",
        protocol_fingerprint=protocol_fingerprint,
        models=protocol["models"],
    )
    prompts = {
        "finish": (
            "Synthetic non-benchmark format check only. Return exactly one Finish action "
            "with an empty argument and the short answer 7."
        ),
        "search": (
            "Synthetic non-benchmark first-retrieval format check. Return exactly one "
            "Search action whose argument is a concise query for 2024 operating-margin "
            "details and whose answer is empty."
        ),
        "react": (
            "Synthetic non-benchmark later-retrieval format check. Return exactly one "
            "Lookup action whose argument is operating margin and whose answer is empty."
        ),
    }
    completed_keys = {str(row["call_key"]) for row in ledger.data["calls"]}
    for tier in TIERS:
        spec = protocol["models"][tier]
        for action_schema in ("finish", "search", "react"):
            call_key = f"{tier}/{action_schema}"
            if call_key in completed_keys:
                continue
            prompt = prompts[action_schema]
            prompt_hash = "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            sleep(float(protocol["inference"]["inter_call_delay_seconds"]))
            ledger.reserve(tier, call_key, prompt_hash)
            try:
                response = call_capability_model(
                    prompt=prompt,
                    requested_model=str(spec["requested_model_id"]),
                    canonical_slug=str(spec["canonical_slug"]),
                    max_tokens=int(protocol["workflows"]["max_output_tokens_per_call"]),
                    action_schema=action_schema,
                    seed=int(protocol["inference"]["request_seed"]),
                    stop=[],
                )
                expected_reasoning = None if tier == "control" else "none"
                expected_sent = tier != "control"
                if (
                    response.provider_name != "OpenAI"
                    or response.finish_reason != "stop"
                    or response.result.status != "ok"
                    or response.result.requested_model != spec["requested_model_id"]
                    or response.result.resolved_model != spec["requested_model_id"]
                    or response.request_parameters.get("reasoning_effort") != expected_reasoning
                    or response.request_parameters.get("reasoning_parameter_sent") is not expected_sent
                    or response.request_parameters.get("seed") != int(protocol["inference"]["request_seed"])
                    or response.request_parameters.get("sampling_parameters_sent") != []
                    or response.request_parameters.get("structured_outputs") is not True
                ):
                    raise StopExperiment("Synthetic probe provider/request binding failed")
                provider_cost = response.result.provider_cost_usd
                if provider_cost is None:
                    raise StopExperiment("Synthetic probe cost telemetry is missing")
                ledger.complete(tier, call_key, response, float(provider_cost))
            except Exception as exc:
                write_stable_json(failure_path, {
                    "action_schema": action_schema,
                    "error": str(exc)[:500],
                    "error_type": type(exc).__name__,
                    "failed_at": utc_now(),
                    "protocol_fingerprint": protocol_fingerprint,
                    "status": "stopped",
                    "tier": tier,
                })
                raise StopExperiment(f"First synthetic format-probe failure stopped probing: {exc}") from exc
            print(f"[FORMAT PROBE] {tier}/{action_schema} process checks passed", flush=True)
    if len(ledger.data["calls"]) != len(TIERS) * 3:
        raise StopExperiment("All nine mandatory synthetic format probes did not complete")
    write_stable_json(completion_path, {
        "completed_at": utc_now(),
        "cumulative_spend_usd": ledger.current_spend,
        "probe_count": len(ledger.data["calls"]),
        "process_checks_passed": True,
        "protocol_fingerprint": protocol_fingerprint,
        "status": "complete",
        "tiers": list(TIERS),
    })
    print("[FORMAT PROBES COMPLETE] all tier/schema process checks passed")


class CapabilityRunner:
    def __init__(self, protocol_path: str | Path = DEFAULT_PROTOCOL_PATH, *, env_factory=None):
        self.protocol = load_protocol(protocol_path)
        if tuple(self.protocol["models"]) != tuple(TIERS):
            raise StopExperiment("Study command requires the frozen control/Luna/Terra tier order")
        self.publication = public_head_preflight(self.protocol)
        self.protocol_path = Path(self.protocol["_path"])
        self.manifest = load_manifest(self.protocol)
        self.env_factory = env_factory or HarmonizedEnvFactory()
        validate_manifest_against_sources(self.protocol, self.manifest, self.env_factory)
        self.schedule = normalized_execution_schedule(self.manifest)
        self.items = {
            (dataset, str(item["example_id"])): item
            for dataset in DATASETS
            for item in self.manifest["datasets"][dataset]["examples"]
        }
        self.snapshot_path = resolve_path(self.protocol_path, str(self.protocol["model_snapshot"]))
        validate_live_catalog(self.snapshot_path)
        self.snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        repo = Path(self.publication["repo"])
        self.results_root = (repo / Path(str(self.protocol["results"]["root"]))).resolve()
        self.results_root.mkdir(parents=True, exist_ok=True)
        body = {key: value for key, value in self.protocol.items() if key != "_path"}
        self.protocol_fingerprint = fingerprint(body)
        self.pre_result_commit = self.publication["commit"]
        self.config_path = self.results_root / "config.json"
        self.history_path = self.results_root / "run_history.json"
        self.completion_path = self.results_root / "study_complete.json"
        self.budget_contract = cumulative_budget_contract(self.protocol)
        self.budget_guard = CumulativeBudgetGuard(
            self.budget_contract,
            path=self.results_root / "cumulative_spend_ledger.json",
            protocol_fingerprint=self.protocol_fingerprint,
            models=self.protocol["models"],
        )
        self.ledgers = {tier: self.budget_guard.tier_view(tier) for tier in TIERS}
        self._write_or_validate_config()
        self._fail_if_prior_study_failure()

    def _config(self) -> Dict[str, Any]:
        return {
            "frameworks": list(FRAMEWORKS),
            "manifest_fingerprint": self.manifest["manifest_fingerprint"],
            "model_bindings": {
                tier: {
                    "canonical_slug": self.protocol["models"][tier]["canonical_slug"],
                    "requested_model_id": self.protocol["models"][tier]["requested_model_id"],
                }
                for tier in TIERS
            },
            "pre_result_commit": self.pre_result_commit,
            "protocol_fingerprint": self.protocol_fingerprint,
            "protocol_id": self.protocol["protocol_id"],
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "sample_count": len(self.manifest["execution_schedule"]["items"]),
            "schedule_fingerprint": fingerprint(self.manifest["execution_schedule"]),
            "tiers": list(TIERS),
        }

    def _write_or_validate_config(self) -> None:
        expected = self._config()
        if self.config_path.exists():
            if json.loads(self.config_path.read_text(encoding="utf-8")) != expected:
                raise StopExperiment("Resume configuration differs from frozen run")
        else:
            write_stable_json(self.config_path, expected)

    def _path(self, tier: str, dataset: str, framework: str) -> Path:
        return self.results_root / tier / dataset / framework / "results.json"

    def _load(self, tier: str, dataset: str, framework: str) -> List[Dict[str, Any]]:
        path = self._path(tier, dataset, framework)
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len({str(row["example_id"]) for row in rows}) != len(rows):
            raise StopExperiment(f"Malformed result store: {path}")
        return rows

    def _save(self, tier: str, dataset: str, framework: str, row: Dict[str, Any]) -> None:
        rows = self._load(tier, dataset, framework)
        if any(str(saved["example_id"]) == str(row["example_id"]) for saved in rows):
            raise StopExperiment("Attempted to overwrite immutable output")
        rows.append(row)
        order = {str(item["example_id"]): n for n, item in enumerate(self.manifest["datasets"][dataset]["examples"])}
        rows.sort(key=lambda saved: order[str(saved["example_id"])])
        write_stable_json(self._path(tier, dataset, framework), rows)

    def _fail_if_prior_study_failure(self) -> None:
        if any(
            row.get("status") != "success"
            for tier in TIERS for dataset in DATASETS for framework in FRAMEWORKS
            for row in self._load(tier, dataset, framework)
        ):
            raise StopExperiment("A frozen provider/integrity failure already stopped this study")

    def _pending(self) -> List[Tuple[str, str, str, str]]:
        return [
            episode for episode in self.schedule
            if not any(
                str(row["example_id"]) == episode[1]
                for row in self._load(episode[2], episode[0], episode[3])
            )
        ]

    def _run_episode(self, dataset: str, item: Mapping[str, Any], tier: str, framework: str) -> Dict[str, Any]:
        set_active_dataset(dataset)
        env = LeakageGuardEnv(self.env_factory(dataset))
        spec = self.protocol["models"][tier]
        model = BudgetedCapabilityModel(
            self.protocol, self.snapshot, self.ledgers[tier], tier,
            f"{dataset}/{item['example_id']}/{tier}/{framework}", framework,
        )
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
            return self._success(dataset, item, tier, framework, result, model)
        except Exception as exc:
            self._save(tier, dataset, framework, {
                "call_count_before_stop": len(model.call_records),
                "dataset": dataset,
                "error": str(exc)[:500],
                "error_type": type(exc).__name__,
                "example_id": str(item["example_id"]),
                "framework": framework,
                "item_hash": item["item_hash"],
                "status": "provider_or_integrity_failure",
                "tier": tier,
            })
            raise StopExperiment(f"First provider/integrity failure stopped the study: {exc}") from exc

    def _success(self, dataset: str, item: Mapping[str, Any], tier: str, framework: str, result: Mapping[str, Any], model: BudgetedCapabilityModel) -> Dict[str, Any]:
        requested = self.protocol["models"][tier]["requested_model_id"]
        canonical = self.protocol["models"][tier]["canonical_slug"]
        telemetry = aggregate_telemetry(result, requested)
        calls = telemetry["call_records"]
        prompts = list(result.get("prompt_records") or [])
        if not calls or len(calls) != len(prompts) or len(calls) != len(model.call_records):
            raise StopExperiment("Per-call telemetry or prompt coverage is incomplete")
        expected_reasoning = None if tier == "control" else "none"
        expected_reasoning_sent = tier != "control"
        expected_seed = int(self.protocol["inference"]["request_seed"])
        for call_index, (call, prompt, model_call) in enumerate(zip(calls, prompts, model.call_records), 1):
            if call.get("requested_model") != requested or call.get("resolved_model") != requested or call.get("status") != "ok":
                raise StopExperiment("Model/status binding mismatch")
            expected_schema = "finish" if framework == "static" else ("search" if call_index == 1 else "react")
            if (
                model_call.get("provider_name") != "OpenAI"
                or model_call.get("finish_reason") != "stop"
                or model_call.get("reasoning_effort") != expected_reasoning
                or model_call.get("reasoning_parameter_sent") is not expected_reasoning_sent
                or model_call.get("seed") != expected_seed
                or model_call.get("sampling_parameters_sent") != []
                or model_call.get("structured_outputs") is not True
                or model_call.get("action_schema") != expected_schema
            ):
                raise StopExperiment("Provider or request-parameter binding mismatch")
            if (
                prompt["sha256"] != model_call.get("prompt_sha256")
                or int(prompt["word_count"]) > int(self.protocol["workflows"]["context_word_budget_per_call"])
                or int(prompt["utf8_bytes"]) > int(self.protocol["workflows"]["context_utf8_byte_budget_per_call"])
            ):
                raise StopExperiment("Prompt hash, word ceiling, or UTF-8 byte ceiling mismatch")
            call.update({
                "action_schema": model_call["action_schema"],
                "call_key": model_call["call_key"],
                "catalog_canonical_slug": canonical,
                "prompt_sha256": prompt["sha256"],
                "prompt_utf8_bytes": prompt["utf8_bytes"],
                "prompt_word_count": prompt["word_count"],
                "provider_name": "OpenAI",
                "reasoning_effort": expected_reasoning,
                "reasoning_parameter_sent": expected_reasoning_sent,
                "seed": expected_seed,
                "sampling_parameters_sent": [],
                "structured_outputs": True,
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
        trace = str(result.get("raw_trace", ""))
        provider_cost = telemetry["provider_cost_usd"]
        estimated_cost = telemetry["estimated_cost_usd"]
        # Do not score here.  The frozen analyzer may read outcomes only after
        # study_complete.json proves that all three mandatory tiers completed.
        return {
            "answer": str(result.get("answer") or "UNKNOWN"),
            "answer_contract": self.protocol["workflows"]["answer_contract"],
            "backend": "openrouter",
            "cached_tokens": telemetry["cached_tokens"],
            "call_records": calls,
            "catalog_canonical_slug": canonical,
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
            "gold_scale": result.get("gold_scale", result.get("scale", "")),
            "ground_truth": result.get("gt_answer", result.get("ground_truth")),
            "input_tokens": telemetry["input_tokens"],
            "item_hash": item["item_hash"],
            "latency_ms": telemetry["latency_ms"],
            "llm_attempt_count": telemetry["llm_attempt_count"],
            "llm_call_count": telemetry["llm_call_count"],
            "malformed_fallback": result["malformed_fallback"],
            "max_prompt_word_count": result["max_prompt_word_count"],
            "method_version": result["method_version"],
            "model_actions": list(result.get("model_actions") or []),
            "output_tokens": telemetry["output_tokens"],
            "parse_status": result["parse_status"],
            "pre_result_commit": self.pre_result_commit,
            "prompt_hash": result["prompt_hash"],
            "prompt_records": prompts,
            "protocol_id": self.protocol["protocol_id"],
            "provider_cost_usd": provider_cost,
            "provider_name": "OpenAI",
            "question_type": result.get("question_type", ""),
            "question_idx": int(item["index"]),
            "raw_trace": trace,
            "react_action_policy": result.get("react_action_policy"),
            "react_process_integrity": result.get("react_process_integrity"),
            "reasoning_effort": expected_reasoning,
            "reasoning_parameter_sent": expected_reasoning_sent,
            "reasoning_tokens": telemetry["reasoning_tokens"],
            "requested_model": requested,
            "resolved_model": requested,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "retrieval_operation_count": int(result["retrieval_operation_count"]),
            "retry_count": telemetry["retry_count"],
            "sampling_parameters_sent": [],
            "seed": expected_seed,
            "scorer_input_sha256": "sha256:" + hashlib.sha256(str(result.get("answer") or "UNKNOWN").encode("utf-8")).hexdigest(),
            "status": "success",
            "structured_outputs": True,
            "tier": tier,
            "total_tokens": telemetry["total_tokens"],
            "trace_hash": "sha256:" + hashlib.sha256(trace.encode("utf-8")).hexdigest(),
        }

    def _completion_counts(self) -> Dict[str, int]:
        return {
            tier: sum(len(self._load(tier, dataset, framework)) for dataset in DATASETS for framework in FRAMEWORKS)
            for tier in TIERS
        }

    def run(self) -> None:
        if self.completion_path.exists():
            completion = json.loads(self.completion_path.read_text(encoding="utf-8"))
            if completion.get("protocol_fingerprint") != self.protocol_fingerprint:
                raise StopExperiment("Completion record belongs to another frozen protocol")
            return
        pending = self._pending()
        history = json.loads(self.history_path.read_text(encoding="utf-8")) if self.history_path.exists() else []
        successes = 0
        for ordinal, (dataset, example_id, tier, framework) in enumerate(pending, 1):
            # Identifiers and process position only; never print answers, scores,
            # costs by model, or partial aggregates.
            print(f"[{ordinal}/{len(pending)}] {dataset}/{example_id}/{tier}/{framework}", flush=True)
            try:
                row = self._run_episode(dataset, self.items[(dataset, example_id)], tier, framework)
            except StopExperiment:
                history.append({
                    "attempted_episodes": ordinal, "finished_at": utc_now(),
                    "status": "stopped", "successful_episodes": successes,
                })
                write_stable_json(self.history_path, history)
                raise
            self._save(tier, dataset, framework, row)
            successes += 1
        if self._pending():
            raise StopExperiment("Study schedule remains incomplete after execution")
        counts = self._completion_counts()
        expected_per_tier = len(self.manifest["execution_schedule"]["items"]) * len(FRAMEWORKS)
        if set(counts) != set(TIERS) or any(count != expected_per_tier for count in counts.values()):
            raise StopExperiment("All three mandatory tiers did not complete the frozen schedule")
        history.append({
            "attempted_episodes": len(pending), "finished_at": utc_now(),
            "status": "complete", "successful_episodes": successes,
        })
        write_stable_json(self.history_path, history)
        write_stable_json(self.completion_path, {
            "completed_at": utc_now(),
            "cumulative_spend_usd": self.budget_guard.current_spend,
            "episode_count": sum(counts.values()),
            "pre_result_commit": self.pre_result_commit,
            "process_checks_passed": True,
            "protocol_fingerprint": self.protocol_fingerprint,
            "status": "complete",
            "tier_episode_counts": counts,
        })
        print("[COMPLETE] all mandatory tiers and scheduled episodes passed process checks")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--format-probes", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.format_probes:
        protocol = load_probe_protocol(args.protocol)
        protocol_path = Path(protocol["_path"])
        repo = Path(_git(protocol_path.parent, "rev-parse", "--show-toplevel"))
        run_root_probe = str(protocol["results"]["root"]).rstrip("/") + "/format_probes/.ignore-probe"
        _git(repo, "check-ignore", "-q", "--no-index", run_root_probe)
        snapshot_path = resolve_path(protocol_path, str(protocol["model_snapshot"]))
        catalog = validate_live_catalog(snapshot_path)
        preflight = {
            "catalog": catalog,
            "credential_available": bool(os.getenv("OPENROUTER_API_KEY")),
            "probe_count": len(TIERS) * 3,
            "run_root_ignored": True,
        }
        if args.preflight_only:
            print(json.dumps(preflight, sort_keys=True))
            return
        if not preflight["credential_available"]:
            raise SystemExit("OPENROUTER_API_KEY is unavailable; no provider calls made")
        run_format_probes(protocol, repo)
        return
    protocol = load_protocol(args.protocol)
    publication = public_head_preflight(protocol)
    snapshot_path = resolve_path(Path(protocol["_path"]), str(protocol["model_snapshot"]))
    catalog = validate_live_catalog(snapshot_path)
    run_root_probe = str(protocol["results"]["root"]).rstrip("/") + "/.ignore-probe"
    _git(Path(publication["repo"]), "check-ignore", "-q", "--no-index", run_root_probe)
    preflight = {
        "catalog": catalog,
        "credential_available": bool(os.getenv("OPENROUTER_API_KEY")),
        "cumulative_budget": cumulative_budget_contract(protocol),
        "publication": publication,
        "run_root_ignored": True,
        "scheduled_episode_count": len(normalized_execution_schedule(load_manifest(protocol))),
    }
    if args.preflight_only:
        print(json.dumps(preflight, sort_keys=True))
        return
    if not preflight["credential_available"]:
        raise SystemExit("OPENROUTER_API_KEY is unavailable; no provider calls made")
    CapabilityRunner(args.protocol).run()


if __name__ == "__main__":
    main()

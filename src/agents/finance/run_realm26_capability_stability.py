"""Run the frozen same-manifest, different-seed capability stability check.

This is a post-hoc generation-stability replication, not a fresh-sample study.
It reuses the hash-validated capability implementation and manifest without
editing the completed study's frozen protocol.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .protocol_v2 import ProtocolError, fingerprint
from .realm26_capability_llm import validate_live_catalog
from .realm26_capability_protocol import (
    DATASETS,
    FRAMEWORKS,
    TIERS,
    load_manifest,
    load_protocol,
    resolve_path,
    sha256_file,
    validate_manifest_against_sources,
)
from .realm26_harmonized_data import HarmonizedEnvFactory
from .run_realm26_capability_ladder import (
    CapabilityRunner,
    CumulativeBudgetGuard,
    StopExperiment,
    _git,
    cumulative_budget_contract,
    normalized_execution_schedule,
    public_head_preflight,
)


STABILITY_PROTOCOL_ID = "realm26_capability_stability"
DEFAULT_STABILITY_SPEC = Path(__file__).with_name("protocols") / f"{STABILITY_PROTOCOL_ID}.json"


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProtocolError(f"Expected a JSON object: {path}")
    return payload


def load_stability_protocol(
    spec_path: str | Path = DEFAULT_STABILITY_SPEC,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Validate the replication overlay and return overlay, base, and spec."""

    path = Path(spec_path).resolve()
    spec = _load_json(path)
    if (
        spec.get("schema_version") != "realm26-capability-stability-v1"
        or spec.get("study_type") != "same_manifest_different_seed_post_hoc_stability"
        or spec.get("freeze_state") != "frozen"
        or spec.get("same_manifest") is not True
        or spec.get("same_request_contract_except_seed") is not True
    ):
        raise ProtocolError("Unexpected or unfrozen capability-stability specification")

    base_path = resolve_path(path, str(spec.get("base_protocol")))
    base = load_protocol(base_path)
    manifest_path = resolve_path(path, str(spec.get("manifest")))
    snapshot_path = resolve_path(path, str(spec.get("model_snapshot")))
    expected_hashes = spec.get("artifact_hashes") or {}
    actual_hashes = {
        "base_protocol": sha256_file(base_path),
        "manifest": sha256_file(manifest_path),
        "model_snapshot": sha256_file(snapshot_path),
    }
    if expected_hashes != actual_hashes:
        raise ProtocolError(f"Stability artifact hash mismatch: expected={expected_hashes}, actual={actual_hashes}")
    if resolve_path(base_path, str(base["manifest"])) != manifest_path:
        raise ProtocolError("Stability run does not bind the original frozen manifest")

    request_seed = int(spec.get("request_seed", -1))
    original_seed = int(base["inference"]["request_seed"])
    if request_seed < 0 or request_seed == original_seed:
        raise ProtocolError("Stability request seed must be prospectively different")
    original = spec.get("original_run") or {}
    if (
        int(original.get("request_seed", -1)) != original_seed
        or original.get("pre_result_commit") != "d328ac71d306f9fd828953aff084dea925711d7e"
        or original.get("analysis_fingerprint")
        != "sha256:4b6ccd22e86e001298491f91eba3e8a4d8305e5f71c5a40fefd2efb6885fec80"
    ):
        raise ProtocolError("Original completed-run provenance changed")
    if spec.get("tier_execution") != {
        "all_arms_required": True,
        "all_tiers_required": True,
        "analysis_after_complete": True,
        "tiers": list(TIERS),
    }:
        raise ProtocolError("Stability run must execute every tier and arm")

    budget = spec.get("budget") or {}
    prior = float(budget.get("prior_cumulative_spend_usd", -1))
    study = sum(float(base["models"][tier]["maximum_reserved_study_cost_usd"]) for tier in TIERS)
    combined = prior + study
    hard_cap = float(budget.get("hard_cap_usd", -1))
    if (
        abs(prior - 1.0071798110000005) > 1e-12
        or abs(study - float(budget.get("study_maximum_reservation_usd", -1))) > 1e-12
        or abs(combined - float(budget.get("combined_maximum_reservation_usd", -1))) > 1e-12
        or abs(hard_cap - combined - float(budget.get("reservation_headroom_usd", -1))) > 1e-12
        or combined > hard_cap + 1e-12
    ):
        raise ProtocolError("Stability replication is not reconciled under the cumulative USD 20 cap")

    analysis = spec.get("analysis") or {}
    if (
        int(analysis.get("bootstrap_resamples", -1)) != 10_000
        or int(analysis.get("bootstrap_seed", -1)) != 20260804
        or analysis.get("inspect_outcomes_only_after_both_runs_complete") is not True
        or analysis.get("primary_stability_report")
        != "side-by-side original and replication estimates; do not pool as independent samples"
    ):
        raise ProtocolError("Stability analysis plan changed")

    overlay = copy.deepcopy(base)
    overlay["protocol_id"] = STABILITY_PROTOCOL_ID
    overlay["inference"]["request_seed"] = request_seed
    overlay["model_snapshot"] = spec["model_snapshot"]
    overlay["publication"] = copy.deepcopy(spec["publication"])
    overlay["results"] = copy.deepcopy(spec["results"])
    overlay["budget"] = {
        "hard_cap_usd": hard_cap,
        "prior_failed_attempt_spend_usd": prior,
        "prior_failed_frozen_study_allowance_usd": 0.0,
        "format_probe_prior_attempt_allowance_usd": 0.0,
        "format_probe_actual_spend_usd": 0.0,
        "study_maximum_reservation_usd": study,
    }
    overlay["stability_replication"] = {
        "claims_scope": spec["claims_scope"],
        "spec_fingerprint": fingerprint(spec),
        "study_type": spec["study_type"],
    }
    return overlay, base, spec


class StabilityRunner(CapabilityRunner):
    """CapabilityRunner initialized from a validated replication overlay."""

    def __init__(self, spec_path: str | Path = DEFAULT_STABILITY_SPEC, *, env_factory=None):
        self.protocol, self.base_protocol, self.stability_spec = load_stability_protocol(spec_path)
        if tuple(self.protocol["models"]) != tuple(TIERS):
            raise StopExperiment("Stability command requires control, Luna, and Terra")
        self.publication = public_head_preflight(self.protocol)
        self.protocol_path = Path(self.base_protocol["_path"])
        self.manifest = load_manifest(self.base_protocol)
        self.env_factory = env_factory or HarmonizedEnvFactory()
        validate_manifest_against_sources(self.base_protocol, self.manifest, self.env_factory)
        self.schedule = normalized_execution_schedule(self.manifest)
        self.items = {
            (dataset, str(item["example_id"])): item
            for dataset in DATASETS
            for item in self.manifest["datasets"][dataset]["examples"]
        }
        self.snapshot_path = resolve_path(self.protocol_path, str(self.protocol["model_snapshot"]))
        validate_live_catalog(self.snapshot_path)
        self.snapshot = _load_json(self.snapshot_path)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=str(DEFAULT_STABILITY_SPEC))
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    protocol, base, _ = load_stability_protocol(args.spec)
    publication = public_head_preflight(protocol)
    repo = Path(publication["repo"])
    run_root_probe = str(protocol["results"]["root"]).rstrip("/") + "/.ignore-probe"
    _git(repo, "check-ignore", "-q", "--no-index", run_root_probe)
    manifest = load_manifest(base)
    snapshot_path = resolve_path(Path(base["_path"]), str(protocol["model_snapshot"]))
    preflight = {
        "catalog": validate_live_catalog(snapshot_path),
        "credential_available": bool(os.getenv("OPENROUTER_API_KEY")),
        "cumulative_budget": cumulative_budget_contract(protocol),
        "original_request_seed": int(base["inference"]["request_seed"]),
        "publication": publication,
        "replication_request_seed": int(protocol["inference"]["request_seed"]),
        "run_root_ignored": True,
        "scheduled_episode_count": len(normalized_execution_schedule(manifest)),
    }
    if args.preflight_only:
        print(json.dumps(preflight, sort_keys=True))
        return
    if not preflight["credential_available"]:
        raise SystemExit("OPENROUTER_API_KEY is unavailable; no provider calls made")
    StabilityRunner(args.spec).run()


if __name__ == "__main__":
    main()

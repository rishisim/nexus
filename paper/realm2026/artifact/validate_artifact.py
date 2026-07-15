#!/usr/bin/env python3
"""Offline anonymity, safety, and integrity checks for the review artifact."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".json", ".md", ".py", ".txt", ".tex", ".yaml", ".yml", ".sha256"}
FORBIDDEN_NAME = re.compile(r"(^|/)(?:results?|outcomes?|traces?|logs?|build|dist|final)(?:/|$)|\.(?:pdf|aux|bbl|blg|log|fls|fdb_latexmk|synctex\.gz)$", re.I)
ABSOLUTE_PATH = re.compile(r"(?:/Users/|/home/|/var/|/private/var/|[A-Za-z]:\\\\)")
SECRET = re.compile(r"(?:sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{15,}|(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,})", re.I)
URL = re.compile(r"https?://[^\s)\]>]+", re.I)
ALLOWED_URL = re.compile(r"https?://(?:openrouter\.ai|github\.com/acl-org|json-schema\.org)(?:/.*)?$", re.I)
GIT_COMMIT = re.compile(r"\b[0-9a-f]{40}\b", re.I)
SCORE_ROW_KEYS = {
    "study",
    "dataset",
    "example_id",
    "system",
    "status",
    "primary_metric",
    "primary_score",
    "exact_match",
    "f1",
    "llm_calls",
    "retrieval_operations",
    "retry_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_usd",
    "cost_source",
    "latency_ms",
    "route",
    "resolved_model",
}


def fail(rule: str, path: Path, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    raise AssertionError(f"{rule}: {path.relative_to(ROOT)}{suffix}")


def tracked_paths() -> set[Path]:
    output = subprocess.check_output(["git", "ls-files", "--", str(ARTIFACT.relative_to(ROOT))], cwd=ROOT, text=True)
    return {ROOT / line.strip() for line in output.splitlines() if line.strip()}


def main() -> int:
    tracked = tracked_paths()
    package_files = {
        p for p in ARTIFACT.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    }
    if not package_files <= tracked:
        missing = sorted(str(p.relative_to(ROOT)) for p in package_files - tracked)
        raise AssertionError(f"untracked artifact files: {missing}")

    for path in sorted(tracked):
        relative = path.relative_to(ARTIFACT).as_posix()
        if FORBIDDEN_NAME.search(relative):
            fail("forbidden_build_or_outcome_filename", path)
        if path.suffix.lower() not in TEXT_SUFFIXES:
            fail("unexpected_binary_or_archive", path)
        if path == Path(__file__).resolve():
            # The audit's own regex literals necessarily mention the patterns
            # it is designed to detect; audit all other package text.
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            if ABSOLUTE_PATH.search(line):
                fail("local_absolute_path", path, f"line {line_number}")
            if SECRET.search(line):
                fail("raw_secret", path, f"line {line_number}")
            if GIT_COMMIT.search(line):
                fail("identity_linkable_git_commit", path, f"line {line_number}")
            for url in URL.findall(line):
                if not ALLOWED_URL.fullmatch(url.rstrip(".,'\"")):
                    fail("unapproved_or_deanonymizing_url", path, f"line {line_number}")

    manifest_path = ARTIFACT / "manifest.json"
    checksums_path = ARTIFACT / "checksums.sha256"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "realm-anonymous-artifact-v1"
    assert manifest["partition"] == "development_only"
    assert manifest["sealed_final_partition"] == "excluded"
    assert manifest["provider_calls"] is False
    assert manifest["source_freeze"] == "anonymous-review-source-freeze-v1"
    assert "source_commit" not in manifest
    listed = {entry["path"]: entry["sha256"] for entry in manifest["entries"]}
    assert "checksums.sha256" not in listed
    for relative, expected in listed.items():
        path = ARTIFACT / relative
        assert path.is_file(), f"missing manifest entry: {relative}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"manifest hash mismatch: {relative}"

    checksum_lines = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        checksum_lines[relative] = digest
    assert set(checksum_lines) == set(listed) | {"manifest.json"}
    for relative, expected in checksum_lines.items():
        assert hashlib.sha256((ARTIFACT / relative).read_bytes()).hexdigest() == expected, f"checksum mismatch: {relative}"

    for path in sorted((ARTIFACT / "development_manifests").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "final" not in payload, f"final partition present: {path.name}"
        assert payload["artifact_partition"] == "development_only"
        assert payload["final_partition"] == "excluded"
        assert len(payload["development"]["examples"]) == 50

    ledger = json.loads(
        (ARTIFACT / "snapshots/score_ledger.json").read_text(encoding="utf-8")
    )
    rows = ledger["rows"]
    assert ledger["schema_version"] == "realm-anonymous-score-ledger-v1"
    assert ledger["row_count"] == len(rows) == 1050
    assert all(set(row) == SCORE_ROW_KEYS for row in rows)
    assert all(row["status"] == "success" for row in rows)

    original = [row for row in rows if row["study"] == "original_development"]
    replication = [
        row for row in rows if row["study"] == "second_family_replication"
    ]
    assert len(original) == 900
    assert len(replication) == 150

    paired = json.loads(
        (ARTIFACT / "snapshots/paired_statistics.json").read_text(encoding="utf-8")
    )
    primary = [
        row
        for row in original
        if row["dataset"] in {"finqa", "tatqa", "convfinqa"}
    ]
    for system, expected in paired["headlines"]["primary_macro"].items():
        dataset_means = []
        for dataset in ("finqa", "tatqa", "convfinqa"):
            values = [
                row["primary_score"]
                for row in primary
                if row["system"] == system and row["dataset"] == dataset
            ]
            assert len(values) == 50
            dataset_means.append(sum(values) / len(values))
        observed = sum(dataset_means) / len(dataset_means)
        assert abs(observed - expected) < 1e-12

    objective = [
        row
        for row in original
        if row["dataset"] in {"financebench", "finqa", "tatqa", "convfinqa"}
        and row["system"] in {"nexus", "react"}
    ]
    pairs: dict[tuple[str, str], dict[str, float]] = {}
    for row in objective:
        pairs.setdefault((row["dataset"], row["example_id"]), {})[row["system"]] = row[
            "exact_match"
        ]
    assert len(pairs) == 200
    assert all(set(pair) == {"nexus", "react"} for pair in pairs.values())
    patterns = {
        "both_correct": 0,
        "both_wrong": 0,
        "static_only_correct": 0,
        "react_only_correct": 0,
    }
    for pair in pairs.values():
        static = bool(pair["nexus"])
        react = bool(pair["react"])
        if static and react:
            patterns["both_correct"] += 1
        elif static:
            patterns["static_only_correct"] += 1
        elif react:
            patterns["react_only_correct"] += 1
        else:
            patterns["both_wrong"] += 1
    for key, observed in patterns.items():
        assert observed == paired["complementarity"]["aggregate"][key]

    replication_summary = json.loads(
        (ARTIFACT / "snapshots/second_family_replication_v1.json").read_text(
            encoding="utf-8"
        )
    )
    for system, expected in replication_summary["overall"]["macro_quality"].items():
        dataset_means = []
        for dataset in ("finqa", "tatqa", "convfinqa"):
            values = [
                row["primary_score"]
                for row in replication
                if row["system"] == system and row["dataset"] == dataset
            ]
            assert len(values) == 25
            dataset_means.append(sum(values) / len(values))
        observed = sum(dataset_means) / len(dataset_means)
        assert abs(observed - expected) < 1e-12

    replication_pairs: dict[tuple[str, str], dict[str, float]] = {}
    for row in replication:
        replication_pairs.setdefault(
            (row["dataset"], row["example_id"]), {}
        )[row["system"]] = row["exact_match"]
    assert len(replication_pairs) == 75
    assert all(
        set(pair) == {"nexus", "react"}
        for pair in replication_pairs.values()
    )
    replication_patterns = {
        "both_correct": 0,
        "both_wrong": 0,
        "left_only_correct": 0,
        "right_only_correct": 0,
    }
    for pair in replication_pairs.values():
        static = bool(pair["nexus"])
        react = bool(pair["react"])
        if static and react:
            replication_patterns["both_correct"] += 1
        elif static:
            replication_patterns["left_only_correct"] += 1
        elif react:
            replication_patterns["right_only_correct"] += 1
        else:
            replication_patterns["both_wrong"] += 1
    expected_patterns = replication_summary["overall"]["complementarity_exact"]
    for key, observed in replication_patterns.items():
        assert observed == expected_patterns[key]

    readme = (ARTIFACT / "README.md").read_text(encoding="utf-8").lower()
    for required in ("sealed final partition is excluded", "provider-free", "no final outcomes"):
        assert required in readme, f"missing safety statement: {required}"
    print(
        f"PASS: {len(package_files)} tracked artifact files and {len(rows)} "
        "sanitized score rows; offline recomputation, integrity, and anonymity checks complete"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)

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

    readme = (ARTIFACT / "README.md").read_text(encoding="utf-8").lower()
    for required in ("sealed final partition is excluded", "provider-free", "no final outcomes"):
        assert required in readme, f"missing safety statement: {required}"
    print(f"PASS: {len(package_files)} tracked artifact files; offline integrity and anonymity checks complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)

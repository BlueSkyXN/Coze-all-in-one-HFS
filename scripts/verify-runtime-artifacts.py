#!/usr/bin/env python3
"""Verify a local Coze runtime artifact set before it is published."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "hfs" / "bin" / "bootstrap_runtime.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("coze_runtime_bootstrap", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    args = parser.parse_args()

    bootstrap = load_bootstrap()
    try:
        raw = args.manifest.read_bytes()
        source_ref, artifacts, build_source = bootstrap.validate_manifest(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, bootstrap.BootstrapError) as exc:
        print(f"runtime artifact validation failed: {exc}", file=sys.stderr)
        return 1

    build_source_path = args.artifacts_dir / build_source["artifact"]
    if not build_source_path.is_file() or build_source_path.parent != args.artifacts_dir:
        print("BUILD_SOURCE.json is missing or escapes artifact directory", file=sys.stderr)
        return 1
    if digest(build_source_path) != build_source["sha256"]:
        print("BUILD_SOURCE.json integrity mismatch", file=sys.stderr)
        return 1
    try:
        bootstrap.validate_build_source(build_source_path, source_ref)
    except bootstrap.BootstrapError as exc:
        print(f"BUILD_SOURCE.json validation failed: {exc}", file=sys.stderr)
        return 1

    for artifact in artifacts:
        path = args.artifacts_dir / artifact["artifact"]
        if not path.is_file() or path.parent != args.artifacts_dir:
            print(f"runtime artifact is missing or escapes artifact directory: {artifact['artifact']}", file=sys.stderr)
            return 1
        if path.stat().st_size != artifact["size_bytes"] or digest(path) != artifact["sha256"]:
            print(f"runtime artifact integrity mismatch: {artifact['artifact']}", file=sys.stderr)
            return 1
        try:
            bootstrap.validate_component_archive(path, artifact["component"])
        except (OSError, bootstrap.BootstrapError) as exc:
            print(f"runtime artifact archive validation failed: {artifact['artifact']}: {exc}", file=sys.stderr)
            return 1

    print(f"runtime artifacts verified for immutable source commit {source_ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

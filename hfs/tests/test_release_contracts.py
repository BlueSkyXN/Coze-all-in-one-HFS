from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPORTER_PATH = ROOT / "scripts" / "export_hfs_space_bundle.py"
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-hfs-formal.yml"
PRODUCER_WORKFLOW = ROOT / ".github" / "workflows" / "build-pinned-coze.yml"
SOURCE_COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    text=True,
).strip()


def load_exporter():
    spec = importlib.util.spec_from_file_location("coze_hfs_bundle_exporter", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class BundleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.exporter = load_exporter()

    def make_bundle(self, directory: Path, profile_name: str = "formal") -> Path:
        config = self.exporter.load_config()
        profile = config["profiles"][profile_name]
        source_entries = []

        for source_path, bundle_path in config["source_to_bundle"].items():
            payload = (ROOT / source_path).read_bytes()
            target = directory / bundle_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            mode = 0o755 if os.access(ROOT / source_path, os.X_OK) else 0o644
            target.chmod(mode)
            source_entries.append(
                {
                    "source_path": source_path,
                    "bundle_path": bundle_path,
                    "mode": f"{mode:04o}",
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                }
            )

        manifest_source = profile["manifest"]
        if manifest_source not in config["source_to_bundle"]:
            payload = (ROOT / manifest_source).read_bytes()
            target = directory / "hfs-dev.toml"
            target.write_bytes(payload)
            target.chmod(0o644)
            source_entries.append(
                {
                    "source_path": manifest_source,
                    "bundle_path": "hfs-dev.toml",
                    "mode": "0644",
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                }
            )

        dockerfile = (directory / "Dockerfile").read_text(encoding="utf-8")
        runtime_source = re.search(r"(?m)^ARG COZE_SOURCE_COMMIT=([0-9a-f]{40})$", dockerfile)
        self.assertIsNotNone(runtime_source)
        evidence = {
            "schema_version": 1,
            "lane": "artifact",
            "version_source": "commit",
            "source_kind": "git-commit",
            "wrapper_source_commit": SOURCE_COMMIT,
            "wrapper_source_repository": config["wrapper_repository"],
            "runtime_source_commit": runtime_source.group(1),
            "runtime_source_repository": "https://github.com/coze-dev/coze-studio",
            "target_space": profile["space"],
            "manifest_profile": manifest_source,
            "profile": profile_name,
            "generated_at": "2026-07-29T00:00:00Z",
            "source_files": source_entries,
        }
        (directory / "BUILD_SOURCE.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.rewrite_checksums(directory)
        return directory

    def rewrite_checksums(self, bundle: Path) -> None:
        expected = self.exporter.expected_paths(self.exporter.load_config())
        lines = [
            f"{sha256((bundle / relative).read_bytes())}  {relative}\n"
            for relative in sorted(expected - {"SHA256SUMS"})
        ]
        (bundle / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")

    def test_profiles_fix_formal_and_candidate_spaces(self) -> None:
        profiles = self.exporter.load_config()["profiles"]
        self.assertEqual(
            profiles,
            {
                "formal": {
                    "manifest": "hfs-dev.toml",
                    "space": "BlueSkyXN/Coze-all-in-one-HFS",
                },
                "candidate": {
                    "manifest": "hfs-dev.candidate.toml",
                    "space": "BlueSkyXN/Coze-all-in-one-HFS-v2-candidate",
                },
            },
        )

    def test_verify_accepts_complete_formal_and_candidate_bundles(self) -> None:
        for profile in ("formal", "candidate"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                bundle = self.make_bundle(Path(temporary), profile)
                self.exporter.verify_bundle(bundle, profile)

    def test_verify_rejects_forged_source_inventory_even_with_fresh_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            evidence_path = bundle / "BUILD_SOURCE.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["source_files"][0]["sha256"] = "f" * 64
            evidence_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.rewrite_checksums(bundle)

            with self.assertRaisesRegex(self.exporter.BundleError, "source file inventory"):
                self.exporter.verify_bundle(bundle, "formal")

    def test_verify_rejects_coordinated_payload_inventory_and_checksum_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            config = self.exporter.load_config()
            _source_path, bundle_path = next(iter(config["source_to_bundle"].items()))
            target = bundle / bundle_path
            forged_payload = target.read_bytes() + b"\nforged\n"
            target.write_bytes(forged_payload)

            evidence_path = bundle / "BUILD_SOURCE.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["source_files"][0]["bytes"] = len(forged_payload)
            evidence["source_files"][0]["sha256"] = sha256(forged_payload)
            evidence_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.rewrite_checksums(bundle)

            with self.assertRaisesRegex(self.exporter.BundleError, "wrapper source commit"):
                self.exporter.verify_bundle(bundle, "formal")


class WorkflowContractTests(unittest.TestCase):
    def test_formal_workflow_uses_immutable_readback_and_runtime_gate(self) -> None:
        workflow = FORMAL_WORKFLOW.read_text(encoding="utf-8")
        for required in (
            'HF_CLI_VERSION: "1.5.0"',
            'HF_CLI_CLICK_VERSION: "8.3.1"',
            "huggingface_hub==${HF_CLI_VERSION}",
            "click==${HF_CLI_CLICK_VERSION}",
            "python3 -m huggingface_hub.cli.hf --help",
            "python3 -m huggingface_hub.cli.hf upload --help",
            "deployed_revision = info.sha",
            "revision=deployed_revision",
            "hf_hub_download",
            'runtime.stage == "RUNNING"',
            'runtime.raw.get("sha") == deployed_revision',
        ):
            self.assertIn(required, workflow)
        self.assertGreaterEqual(workflow.count("export_hfs_space_bundle.py verify"), 3)

    def test_artifact_workflow_pins_the_complete_module_cli_runtime(self) -> None:
        workflow = PRODUCER_WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "huggingface_hub==1.5.0",
            "click==8.3.1",
            "python3 -m huggingface_hub.cli.hf version",
            "python3 -m huggingface_hub.cli.hf buckets cp",
        ):
            self.assertIn(required, workflow)

    def test_release_promotion_binds_release_target_to_build_source(self) -> None:
        workflow = PRODUCER_WORKFLOW.read_text(encoding="utf-8")
        promotion = workflow.split("  promote-release:", 1)[1]
        for required in (
            "targetCommitish",
            "BUILD_SOURCE",
            "wrapper_ref",
            "release target commit does not match BUILD_SOURCE wrapper_ref",
        ):
            self.assertIn(required, promotion)


if __name__ == "__main__":
    unittest.main()

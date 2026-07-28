import hashlib
import importlib.util
import io
import sys
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hfs" / "bin" / "bootstrap_runtime.py"


def load_module():
    spec = importlib.util.spec_from_file_location("coze_bootstrap_runtime_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


bootstrap = load_module()
SOURCE_REF = "a" * 40


def manifest(server_archive: Path, web_archive: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_kind": "commit",
        "source_ref": SOURCE_REF,
        "generated_at": "2026-07-26T00:00:00Z",
        "build_source": bootstrap.expected_build_source_name(SOURCE_REF),
        "build_source_sha256": "d" * 64,
        "artifacts": [
            {
                "component": "server",
                "artifact": f"coze-server-app-{SOURCE_REF}.tar.gz",
                "sha256": hashlib.sha256(server_archive.read_bytes()).hexdigest(),
                "size_bytes": server_archive.stat().st_size,
            },
            {
                "component": "web",
                "artifact": f"coze-web-dist-{SOURCE_REF}.tar.gz",
                "sha256": hashlib.sha256(web_archive.read_bytes()).hexdigest(),
                "size_bytes": web_archive.stat().st_size,
            },
        ],
    }


def build_source_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "upstream_repository": bootstrap.UPSTREAM_REPOSITORY,
        "source_kind": "commit",
        "source_ref": SOURCE_REF,
        "generated_at": "2026-07-26T00:00:00Z",
        "wrapper_repository": bootstrap.WRAPPER_REPOSITORY,
        "wrapper_ref": "b" * 40,
        "workflow_run_id": "123456",
        "components": [
            {
                "component": component,
                "upstream_repository": bootstrap.UPSTREAM_REPOSITORY,
                "source_ref": SOURCE_REF,
                "dockerfile": bootstrap.COMPONENTS[component]["dockerfile"],
                "dockerfile_sha256": "c" * 64,
            }
            for component in ("server", "web")
        ],
    }


def write_archive(path: Path, members: dict[str, tuple[bytes, int]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, (content, mode) in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            entry.mode = mode
            archive.addfile(entry, io.BytesIO(content))


class BootstrapRuntimeTests(unittest.TestCase):
    def test_hf_xet_redirect_strips_bearer_and_rejects_other_targets(self):
        handler = bootstrap.SafeArtifactRedirect()
        request = bootstrap.urllib.request.Request(
            "https://huggingface.co/buckets/BlueSkyXN/hfs-dist/resolve/coze/manifest.json",
            headers={"Authorization": "Bearer test-token", "User-Agent": "test"},
        )
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://cas-bridge.xethub.hf.co/xet-object?signature=test",
        )
        self.assertIsNotNone(redirected)
        self.assertEqual(redirected.get_header("Authorization"), None)
        self.assertEqual(redirected.get_header("User-agent"), "coze-hfs-runtime-bootstrap/1")

        regional = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://cas-server.xethub.hf.co/xet-object?signature=test",
        )
        self.assertIsNotNone(regional)

        with self.assertRaises(bootstrap.urllib.error.HTTPError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://example.com/exfiltrate",
            )
        with self.assertRaises(bootstrap.urllib.error.HTTPError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://evilxethub.hf.co/exfiltrate",
            )

    def test_bearer_downloads_are_restricted_to_huggingface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "payload"
            with self.assertRaisesRegex(
                bootstrap.BootstrapError,
                "bearer-authenticated runtime downloads must use huggingface.co",
            ):
                bootstrap.download("https://example.com/artifact", destination, "test-token")

    def test_manifest_requires_two_checksummed_commit_named_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            server = root / "server.tar.gz"
            web = root / "web.tar.gz"
            write_archive(server, {"opencoze": (b"binary", 0o755)})
            write_archive(web, {"index.html": (b"<!doctype html>", 0o644)})
            source_ref, artifacts, build_source = bootstrap.validate_manifest(manifest(server, web))

        self.assertEqual(source_ref, SOURCE_REF)
        self.assertEqual(build_source["artifact"], bootstrap.expected_build_source_name(SOURCE_REF))
        self.assertEqual({item["component"] for item in artifacts}, {"server", "web"})

    def test_manifest_rejects_non_immutable_source_ref_and_unsafe_artifact_name(self):
        data = {
            "schema_version": 1,
            "source_kind": "commit",
            "source_ref": "v0.5.1",
            "generated_at": "2026-07-26T00:00:00Z",
            "artifacts": [],
        }
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_manifest(data)

    def test_manifest_rejects_shared_build_source_and_component_name_swaps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            server = root / "server.tar.gz"
            web = root / "web.tar.gz"
            write_archive(server, {"opencoze": (b"binary", 0o755)})
            write_archive(web, {"index.html": (b"<!doctype html>", 0o644)})
            data = manifest(server, web)
            data["build_source"] = "BUILD_SOURCE.json"
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_manifest(data)

            data = manifest(server, web)
            data["artifacts"][0]["artifact"] = f"coze-web-dist-{SOURCE_REF}.tar.gz"
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_manifest(data)

    def test_build_source_requires_complete_immutable_component_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / bootstrap.expected_build_source_name(SOURCE_REF)
            payload = build_source_payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            bootstrap.validate_build_source(path, SOURCE_REF)

            payload["components"] = payload["components"][:1]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_build_source(path, SOURCE_REF)

    def test_manifest_url_rejects_credentials_query_and_non_https(self):
        for url in (
            "http://example.invalid/manifest.json",
            "https://token@example.invalid/manifest.json",
            "https://example.invalid/manifest.json?token=unsafe",
            "https://example.invalid/manifest.json#fragment",
        ):
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.require_https_url(url, "test")

    def test_tar_validation_rejects_path_escape_and_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                escape = tarfile.TarInfo("../escape")
                escape.size = 1
                bundle.addfile(escape, io.BytesIO(b"x"))
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_tar_members(archive)

    def test_tar_validation_rejects_privileged_and_duplicate_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                first = tarfile.TarInfo("opencoze")
                first.size = 1
                first.mode = 0o4755
                bundle.addfile(first, io.BytesIO(b"x"))
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_component_archive(archive, "server")

            with tarfile.open(archive, "w:gz") as bundle:
                for _ in range(2):
                    duplicate = tarfile.TarInfo("opencoze")
                    duplicate.size = 1
                    duplicate.mode = 0o755
                    bundle.addfile(duplicate, io.BytesIO(b"x"))
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_component_archive(archive, "server")

    def test_install_component_extracts_only_valid_server_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "server.tar.gz"
            destination = root / "app"
            write_archive(archive, {"opencoze": (b"binary", 0o755), "assets/data": (b"ok", 0o644)})

            bootstrap.install_component(archive, "server", destination)

            self.assertEqual((destination / "opencoze").read_bytes(), b"binary")
            self.assertTrue((destination / "opencoze").stat().st_mode & 0o111)

    def test_pair_install_restores_both_previous_payloads_when_second_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            server_destination = root / "app"
            web_destination = root / "web"
            server_destination.mkdir()
            web_destination.mkdir()
            (server_destination / "old").write_text("server", encoding="utf-8")
            (web_destination / "old").write_text("web", encoding="utf-8")
            server_parent = root / "server-stage-parent"
            web_parent = root / "web-stage-parent"
            server_stage = server_parent / "server"
            web_stage = web_parent / "web"
            server_stage.mkdir(parents=True)
            web_stage.mkdir(parents=True)
            (server_stage / "new").write_text("server", encoding="utf-8")
            (web_stage / "new").write_text("web", encoding="utf-8")
            real_replace = os.replace

            def fail_web_stage(source, destination):
                if Path(source) == web_stage and Path(destination) == web_destination:
                    raise OSError("simulated web replacement failure")
                return real_replace(source, destination)

            with mock.patch.object(bootstrap.os, "replace", side_effect=fail_web_stage):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.commit_prepared_components(
                        [
                            ("server", server_parent, server_stage, server_destination),
                            ("web", web_parent, web_stage, web_destination),
                        ]
                    )

            self.assertEqual((server_destination / "old").read_text(encoding="utf-8"), "server")
            self.assertEqual((web_destination / "old").read_text(encoding="utf-8"), "web")

    def test_provenance_excludes_source_url_and_persists_checksums(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifacts = [{"component": "server", "artifact": "server.tar.gz", "sha256": "b" * 64, "size_bytes": 1}]
            bootstrap.write_provenance(
                root,
                "c" * 64,
                SOURCE_REF,
                {"artifact": bootstrap.expected_build_source_name(SOURCE_REF), "sha256": "d" * 64},
                artifacts,
            )
            payload = (root / "runtime-provenance.json").read_text(encoding="utf-8")

        self.assertIn(SOURCE_REF, payload)
        self.assertIn("manifest_sha256", payload)
        self.assertNotIn("https://", payload)


if __name__ == "__main__":
    unittest.main()

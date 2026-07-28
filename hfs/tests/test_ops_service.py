import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ops_service = load_module("coze_ops_service_under_test", ROOT / "hfs" / "bin" / "ops_service.py")


class QuietHandler(ops_service.Handler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass


class OpsServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        self.original_data_dir = ops_service.DATA_DIR
        self.original_log_dir = ops_service.LOG_DIR
        self.original_runtime_provenance_file = ops_service.RUNTIME_PROVENANCE_FILE
        self.original_tcp_check = ops_service.tcp_check
        self.runtime_provenance_dir = tempfile.TemporaryDirectory()
        ops_service.RUNTIME_PROVENANCE_FILE = Path(self.runtime_provenance_dir.name) / "runtime-provenance.json"
        ops_service.RUNTIME_PROVENANCE_FILE.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "manifest_sha256": "a" * 64,
                    "source_kind": "commit",
                    "source_ref": "b" * 40,
                    "build_source": {"artifact": f"BUILD_SOURCE-{'b' * 40}.json", "sha256": "c" * 64},
                    "artifacts": [
                        {"component": "server", "artifact": f"coze-server-app-{'b' * 40}.tar.gz", "sha256": "d" * 64, "size_bytes": 1},
                        {"component": "web", "artifact": f"coze-web-dist-{'b' * 40}.tar.gz", "sha256": "e" * 64, "size_bytes": 1},
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
        ops_service.DATA_DIR = self.original_data_dir
        ops_service.LOG_DIR = self.original_log_dir
        ops_service.RUNTIME_PROVENANCE_FILE = self.original_runtime_provenance_file
        ops_service.tcp_check = self.original_tcp_check
        self.runtime_provenance_dir.cleanup()

    def test_health_payload_ok_includes_minio_by_default(self):
        ops_service.tcp_check = lambda host, port, timeout=1.0: True
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            os.environ["ENABLE_LOCAL_MINIO"] = "1"
            os.environ["CODE_RUNNER_TYPE"] = "sandbox"

            code, payload = ops_service.health_payload()

        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["code_runner_type"], "sandbox")
        self.assertTrue(payload["checks"]["minio"])
        self.assertTrue(all(payload["checks"].values()))

    def test_health_payload_can_omit_local_minio(self):
        ops_service.tcp_check = lambda host, port, timeout=1.0: True
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            os.environ["ENABLE_LOCAL_MINIO"] = "0"

            code, payload = ops_service.health_payload()

        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("minio", payload["checks"])

    def test_health_payload_degrades_when_a_dependency_fails(self):
        def fake_tcp_check(host, port, timeout=1.0):
            return port != 8888

        ops_service.tcp_check = fake_tcp_check
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            os.environ["ENABLE_LOCAL_MINIO"] = "1"

            code, payload = ops_service.health_payload()

        self.assertEqual(code, 503)
        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["checks"]["coze_server"])

    def test_health_payload_fails_closed_without_verified_runtime_provenance(self):
        ops_service.tcp_check = lambda host, port, timeout=1.0: True
        ops_service.RUNTIME_PROVENANCE_FILE.unlink()
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            code, payload = ops_service.health_payload()

        self.assertEqual(code, 503)
        self.assertFalse(payload["checks"]["runtime_provenance"])

    def test_health_payload_fails_when_required_persistence_is_not_mounted(self):
        ops_service.tcp_check = lambda host, port, timeout=1.0: True
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            os.environ["PERSISTENCE_REQUIRED"] = "true"
            with mock.patch.object(ops_service.os.path, "ismount", return_value=False):
                code, payload = ops_service.health_payload()

        self.assertEqual(code, 503)
        self.assertFalse(payload["checks"]["persistent_data"])
        self.assertEqual(payload["persistence"], {"required": True, "mounted": False})

    def test_health_payload_reports_required_persistent_mount(self):
        ops_service.tcp_check = lambda host, port, timeout=1.0: True
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            os.environ["PERSISTENCE_REQUIRED"] = "true"
            with mock.patch.object(ops_service.os.path, "ismount", return_value=True):
                code, payload = ops_service.health_payload()

        self.assertEqual(code, 200)
        self.assertTrue(payload["checks"]["persistent_data"])
        self.assertEqual(payload["persistence"], {"required": True, "mounted": True})

    def test_handler_returns_404_for_unknown_route(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/missing")
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 404)
        self.assertEqual(body, {"status": "not_found"})

    def test_safe_log_filename_rejects_escape_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = root / "logs"
            outside = root / "outside"
            logs.mkdir()
            outside.mkdir()
            (outside / "secret.log").write_text("secret", encoding="utf-8")
            (logs / "escape.log").symlink_to(outside / "secret.log")
            ops_service.LOG_DIR = logs

            self.assertEqual(ops_service.safe_log_filename("inside.log"), "inside.log")
            self.assertIsNone(ops_service.safe_log_filename("/data/logs/nginx.log"))
            self.assertIsNone(ops_service.safe_log_filename("../nginx.log"))
            self.assertIsNone(ops_service.safe_log_filename("escape.log"))

    def test_process_matching_does_not_need_supervisor_control_socket(self):
        self.assertEqual(ops_service.process_names_for("/app/runtime/opencoze"), ["coze-server"])
        self.assertEqual(ops_service.process_names_for("python3 /opt/coze-hfs/bin/ops_service.py"), ["ops-service"])
        self.assertEqual(ops_service.process_names_for("unrelated-worker"), [])

    def test_version_payload_exposes_checksum_provenance_without_runtime_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provenance = Path(tmpdir) / "runtime-provenance.json"
            provenance.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "manifest_sha256": "a" * 64,
                        "source_kind": "commit",
                        "source_ref": "b" * 40,
                        "build_source": {"artifact": f"BUILD_SOURCE-{'b' * 40}.json", "sha256": "c" * 64},
                        "artifacts": [
                            {"component": "server", "artifact": f"coze-server-app-{'b' * 40}.tar.gz", "sha256": "d" * 64, "size_bytes": 1},
                            {"component": "web", "artifact": f"coze-web-dist-{'b' * 40}.tar.gz", "sha256": "e" * 64, "size_bytes": 1},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            ops_service.RUNTIME_PROVENANCE_FILE = provenance
            payload = ops_service.version_payload()

        runtime = payload["coze"]["runtime_provenance"]
        self.assertTrue(runtime["available"])
        self.assertEqual(runtime["source_ref"], "b" * 40)
        self.assertNotIn("url", json.dumps(runtime))

    def test_ops_dashboard_requires_token_for_protected_endpoint(self):
        os.environ["OPS_TOKEN"] = "test-ops-token-that-is-long-enough"
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/_ops/health")
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 401)
        self.assertEqual(body["status"], "unauthorized")

    def test_explicit_ops_header_takes_precedence_over_gateway_bearer(self):
        token = "test-ops-token-that-is-long-enough"
        os.environ["OPS_TOKEN"] = token
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/_ops/version",
            headers={"X-Ops-Token": token, "Authorization": "Bearer hf-gateway-token"},
        )
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(body["coze"]["runtime_provenance"]["source_ref"], "b" * 40)

    def test_ops_dashboard_rejects_short_token_configuration(self):
        os.environ["OPS_TOKEN"] = "too-short"

        self.assertEqual(ops_service.ops_lock_reason(), "OPS_TOKEN must contain at least 24 characters")

    def test_ops_query_token_is_rejected_without_setting_cookie(self):
        os.environ["OPS_TOKEN"] = "test-ops-token-that-is-long-enough"
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/_ops/?token=test-ops-token-that-is-long-enough")
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        cookie = response.getheader("Set-Cookie")
        conn.close()

        self.assertEqual(response.status, 400)
        self.assertEqual(body["status"], "bad_request")
        self.assertIsNone(cookie)


if __name__ == "__main__":
    unittest.main()

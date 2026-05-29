import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
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
        self.original_tcp_check = ops_service.tcp_check

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
        ops_service.DATA_DIR = self.original_data_dir
        ops_service.tcp_check = self.original_tcp_check

    def test_health_payload_ok_includes_minio_by_default(self):
        ops_service.tcp_check = lambda host, port, timeout=1.0: True
        with tempfile.TemporaryDirectory() as tmpdir:
            ops_service.DATA_DIR = Path(tmpdir)
            os.environ["ENABLE_LOCAL_MINIO"] = "1"

            code, payload = ops_service.health_payload()

        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "ok")
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


if __name__ == "__main__":
    unittest.main()

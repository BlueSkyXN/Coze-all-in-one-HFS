import hashlib
import hmac
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
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


admin_service = load_module("coze_admin_service_under_test", ROOT / "hfs" / "bin" / "admin_service.py")


class QuietHandler(admin_service.Handler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass


class AdminServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        admin_service.LOGIN_FAILURES_BY_IP.clear()
        admin_service.LOGIN_FAILURES_GLOBAL.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        os.environ["ADMIN_TOKEN"] = "test-admin-token-that-is-long-enough"
        os.environ["ADMIN_AUDIT_LOG"] = str(Path(self.tmpdir.name) / "admin-audit.jsonl")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
        admin_service.LOGIN_FAILURES_BY_IP.clear()
        admin_service.LOGIN_FAILURES_GLOBAL.clear()

    def test_admin_is_default_off(self):
        os.environ.pop("ADMIN_ENABLED", None)

        self.assertFalse(admin_service.admin_enabled())
        self.assertEqual(admin_service.admin_available(), (False, "admin is disabled"))

    def test_enabled_admin_requires_token(self):
        os.environ["ADMIN_ENABLED"] = "true"
        os.environ.pop("ADMIN_TOKEN", None)

        available, reason = admin_service.admin_available()

        self.assertFalse(available)
        self.assertIn("ADMIN_TOKEN", reason)

    def test_enabled_admin_rejects_short_or_reused_token(self):
        os.environ["ADMIN_ENABLED"] = "true"
        os.environ["ADMIN_TOKEN"] = "too-short"
        self.assertEqual(admin_service.admin_available(), (False, "ADMIN_TOKEN must contain at least 24 characters"))

        os.environ["ADMIN_TOKEN"] = "shared-token-that-is-long-enough"
        os.environ["OPS_TOKEN"] = "shared-token-that-is-long-enough"
        self.assertEqual(admin_service.admin_available(), (False, "ADMIN_TOKEN must not reuse OPS_TOKEN"))

    def test_parse_session_accepts_signed_session_and_rejects_tampering(self):
        os.environ["ADMIN_ENABLED"] = "true"
        cookie_value, _csrf, expires_at = admin_service.make_session()

        parsed = admin_service.parse_session(cookie_value)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.kind, "cookie")
        self.assertEqual(parsed.expires_at, expires_at)
        self.assertIsNone(admin_service.parse_session(cookie_value + "tampered"))

    def test_csrf_key_prefers_admin_csrf_key_then_secret_key(self):
        os.environ["ADMIN_ENABLED"] = "true"
        os.environ["ADMIN_CSRF_KEY"] = "csrf-key"
        cookie_value, csrf_token, _expires_at = admin_service.make_session()
        expires_raw, nonce, _signature = cookie_value.split(".", 2)
        expected = hmac.new(
            b"csrf-key",
            f"csrf|{expires_raw}|{nonce}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(csrf_token, expected)

        os.environ.pop("ADMIN_CSRF_KEY")
        os.environ["SECRET_KEY"] = "runtime-secret"
        cookie_value, csrf_token, _expires_at = admin_service.make_session()
        expires_raw, nonce, _signature = cookie_value.split(".", 2)
        derived_key = hmac.new(b"runtime-secret", b"coze-hfs-admin-csrf", hashlib.sha256).hexdigest()
        expected = hmac.new(
            derived_key.encode("utf-8"),
            f"csrf|{expires_raw}|{nonce}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(csrf_token, expected)

    def test_parse_session_rejects_expired_session(self):
        os.environ["ADMIN_ENABLED"] = "true"
        nonce = "nonce"
        expires_at = int(time.time()) - 1
        signature = admin_service.sign_message("session", str(expires_at), nonce)

        self.assertIsNone(admin_service.parse_session(f"{expires_at}.{nonce}.{signature}"))

    def test_restart_service_requires_whitelist_and_confirm(self):
        os.environ["ADMIN_ENABLED"] = "true"
        auth = admin_service.AuthContext(kind="header", csrf_token="")

        with self.assertRaises(admin_service.AdminError):
            admin_service.restart_service({"service": "admin-service", "confirm": True}, auth)
        with self.assertRaises(admin_service.AdminError):
            admin_service.restart_service({"service": "coze-server"}, auth)

    def test_audit_redacts_sensitive_details(self):
        payload = admin_service.redact_sensitive_details(
            {"token": "secret", "nested": {"authorization": "bearer secret", "safe": "value"}}
        )

        self.assertEqual(payload["token"], "[redacted]")
        self.assertEqual(payload["nested"]["authorization"], "[redacted]")
        self.assertEqual(payload["nested"]["safe"], "value")

    def test_handler_returns_404_when_admin_disabled(self):
        os.environ.pop("ADMIN_ENABLED", None)
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/_admin/api/status")
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 404)
        self.assertEqual(body, {"status": "not_found"})

    def test_login_sets_cookie_and_status_accepts_header_token(self):
        os.environ["ADMIN_ENABLED"] = "true"
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        payload = json.dumps({"token": "test-admin-token-that-is-long-enough"})
        conn.request("POST", "/_admin/api/login", body=payload, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        cookie = response.getheader("Set-Cookie")
        conn.close()

        self.assertEqual(response.status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("coze_admin_session", cookie)
        self.assertNotIn("test-admin-token-that-is-long-enough", json.dumps(body))

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/_admin/api/status",
            headers={"X-Admin-Token": "test-admin-token-that-is-long-enough"},
        )
        response = conn.getresponse()
        status_body = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 200)
        self.assertTrue(status_body["ok"])


if __name__ == "__main__":
    unittest.main()

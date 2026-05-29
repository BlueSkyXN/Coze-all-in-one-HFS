#!/usr/bin/env python3
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOST = os.environ.get("OPS_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPS_PORT", "8081"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data/coze"))


def tcp_check(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def health_payload() -> tuple[int, dict]:
    checks = {
        "mariadb": tcp_check("127.0.0.1", int(os.environ.get("MYSQL_PORT", "3306"))),
        "redis": tcp_check("127.0.0.1", 6379),
        "nats": tcp_check("127.0.0.1", 4222),
        "etcd": tcp_check("127.0.0.1", 2379),
        "elasticsearch": tcp_check("127.0.0.1", 9200),
        "milvus": tcp_check("127.0.0.1", 19530),
        "coze_server": tcp_check("127.0.0.1", 8888),
        "data_dir": DATA_DIR.exists() and os.access(DATA_DIR, os.W_OK),
    }
    if os.environ.get("ENABLE_LOCAL_MINIO", "1") == "1":
        checks["minio"] = tcp_check("127.0.0.1", 9000)
    status = "ok" if all(checks.values()) else "degraded"
    code = 200 if status == "ok" else 503
    return code, {
        "status": status,
        "service": "coze-all-in-one-hfs",
        "checks": checks,
        "data_dir": str(DATA_DIR),
        "public_url": os.environ.get("COZE_PUBLIC_URL") or os.environ.get("SPACE_HOST"),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print("[ops] " + fmt % args, flush=True)

    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in {
            "/healthz",
            "/readyz",
            "/status",
            "/_ops/healthz",
            "/_ops/readyz",
            "/_ops/status",
        }:
            self.send_json(404, {"status": "not_found"})
            return
        code, payload = health_payload()
        self.send_json(code, payload)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[ops] listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
